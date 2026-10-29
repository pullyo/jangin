"""op guard: which operator projects a tool call can reach, and that each one's rules apply.

Run from the repository root:  python3 -m unittest discover -s tests
Every case feeds the hook JSON through the real `op.py guard` process, the way Claude Code / Codex do.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

OP = Path(__file__).resolve().parents[1] / 'skills' / 'operator' / 'scripts' / 'op.py'


def run(args, cwd, stdin=None):
    return subprocess.run([sys.executable, '-I', str(OP), *args], cwd=cwd, input=stdin, capture_output=True, text=True)


class GuardReachTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='op guard 한글 ')
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / 'my project'
        self.outside = self.base / 'elsewhere'
        self.project.mkdir()
        self.outside.mkdir()
        self.assertEqual(run(['init'], self.project).returncode, 0)

    def tearDown(self):
        self.temp.cleanup()

    def hook(self, payload, cwd=None, fmt='claude'):
        return run(['guard', '--format', fmt], cwd or self.outside, json.dumps(payload))

    def test_session_inside_the_project_is_blocked_as_before(self):
        result = self.hook({'tool_name': 'Bash', 'tool_input': {'command': 'wrangler deploy'}}, cwd=self.project)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_hook_cwd_field_is_used_even_when_the_hook_process_runs_elsewhere(self):
        result = self.hook({'tool_name': 'Bash', 'cwd': str(self.project), 'tool_input': {'command': 'wrangler deploy'}})
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_cd_into_the_project_from_another_session_folder_is_blocked(self):
        for command in [f'cd "{self.project}" && wrangler deploy',
                        f"cd '{self.project}'; git push",
                        'cd "my project" && vercel deploy --prod',
                        f'pushd "{self.project}" && npm publish',
                        f'git -C "{self.project}" push origin main']:
            with self.subTest(command=command):
                base = self.base if 'my project"' in command and not command.startswith(('cd "/', "cd '/")) else self.outside
                result = self.hook({'tool_name': 'Bash', 'cwd': str(base), 'tool_input': {'command': command}})
                self.assertEqual(result.returncode, 2, command + '\n' + result.stderr)

    def test_chained_relative_cd_is_followed(self):
        result = self.hook({'tool_name': 'Bash', 'cwd': str(self.base / 'elsewhere'),
                            'tool_input': {'command': 'cd .. && cd "my project" && wrangler deploy'}})
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_codex_list_command_keeps_its_quoting(self):
        result = self.hook({'tool_name': 'shell', 'cwd': str(self.outside),
                            'tool_input': {'command': ['bash', '-lc', f'cd "{self.project}" && git push']}}, fmt='codex')
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_writing_into_the_project_queue_from_outside_is_blocked(self):
        target = self.project / '.operator' / 'pending' / '0001-post-x.md'
        result = self.hook({'tool_name': 'Write', 'cwd': str(self.outside), 'tool_input': {'file_path': str(target), 'content': 'x'}})
        self.assertEqual(result.returncode, 2, result.stderr)
        patch = f'*** Begin Patch\n*** Add File: {target}\n+x\n*** End Patch\n'
        result = self.hook({'tool_name': 'apply_patch', 'cwd': str(self.outside), 'tool_input': {'input': patch}}, fmt='codex')
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_unrelated_commands_and_folders_stay_untouched(self):
        for payload in [{'tool_name': 'Bash', 'cwd': str(self.outside), 'tool_input': {'command': 'wrangler deploy'}},
                        {'tool_name': 'Bash', 'cwd': str(self.outside), 'tool_input': {'command': f'cd "{self.project}" && ls'}},
                        {'tool_name': 'Bash', 'cwd': str(self.outside), 'tool_input': {'command': 'cd $HOME/x && git push'}}]:
            with self.subTest(payload=payload['tool_input']['command']):
                self.assertEqual(self.hook(payload).returncode, 0)
        self.assertFalse((self.outside / '.operator').exists())

    def test_the_project_log_records_the_session_cwd(self):
        self.hook({'tool_name': 'Bash', 'cwd': str(self.outside), 'tool_input': {'command': f'cd "{self.project}" && git push'}})
        last = json.loads((self.project / '.operator' / 'guard.log').read_text(encoding='utf-8').splitlines()[-1])
        self.assertTrue(last['deny'])
        self.assertEqual(last['cwd'], str(self.outside))

    def test_guard_check_accepts_a_cwd(self):
        self.assertEqual(run(['guard', 'check', '--cwd', str(self.outside), f'cd "{self.project}" && git push'], self.outside).returncode, 1)
        self.assertEqual(run(['guard', 'check', '--cwd', str(self.outside), 'git push'], self.outside).returncode, 0)


if __name__ == '__main__':
    unittest.main()


class ApprovalQueueIntegrityTests(unittest.TestCase):
    """The queue can only change through op itself, and op send runs only what a human approved."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='op queue 한글 ')
        self.project = Path(self.temp.name).resolve()
        run(['init'], self.project)
        (self.project / 'd.md').write_text('---\ntype: post\nchannel: x\naction: echo post-to-x\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n', encoding='utf-8')
        (self.project / 'n.md').write_text('---\ntype: post\nchannel: x\n---\n액션 없는 초안입니다. 지금 써보세요 https://example.com\n', encoding='utf-8')
        self.assertEqual(run(['pending', 'add', 'd.md'], self.project).returncode, 0)   # 0001 with action
        self.assertEqual(run(['pending', 'add', 'n.md'], self.project).returncode, 0)   # 0002 without action
        self.human = {**os.environ, 'OPERATOR_ALLOW_NONINTERACTIVE_APPROVE': '1'}

    def tearDown(self):
        self.temp.cleanup()

    def check(self, command):
        return run(['guard', 'check', command], self.project).returncode

    def test_shell_writes_into_the_queue_are_blocked_but_reads_pass(self):
        for command in ['mv .operator/pending/0001-post-x.md .operator/approved/', 'cp d.md .operator/approved/0002.md',
                        'echo "status: approved" > .operator/approved/0001.md', 'sed -i "" s/pending/approved/ .operator/pending/0001-post-x.md',
                        'python3 -c "open(\'.operator/approved/0001.md\',\'w\')"', 'rm -rf .operator', 'mv .operator .operator-bak',
                        f'cp d.md "{self.project}/.operator/approved/x.md"']:
            with self.subTest(command=command):
                self.assertEqual(self.check(command), 1)
        for command in ['ls .operator/pending', 'cat .operator/pending/0001-post-x.md', 'grep -r x .operator/approved',
                        'op pending list', 'op pending show 0001', 'rm -r .operator/tmp/x', 'rm -f build/tmp.txt']:
            with self.subTest(command=command):
                self.assertEqual(self.check(command), 0)

    def test_approve_needs_an_interactive_terminal(self):
        result = run(['pending', 'approve', '0001'], self.project)   # no TTY, like an agent's shell tool
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertTrue(list((self.project / '.operator' / 'pending').glob('0001-*.md')))

    def test_send_runs_only_the_approved_action(self):
        self.assertEqual(subprocess.run([sys.executable, '-I', str(OP), 'pending', 'approve', '0001'], cwd=self.project, env=self.human, capture_output=True, text=True).returncode, 0)
        other = run(['send', '0001', '--', 'echo', 'SOMETHING-ELSE'], self.project)
        self.assertEqual(other.returncode, 6, other.stderr)
        self.assertTrue(list((self.project / '.operator' / 'approved').glob('0001-*.md')))
        same = run(['send', '0001'], self.project)
        self.assertEqual(same.returncode, 0, same.stderr)
        self.assertIn('post-to-x', same.stdout)
        self.assertTrue(list((self.project / '.operator' / 'sent').glob('0001-*.md')))

    def test_ticket_without_action_cannot_be_sent_until_a_human_sets_one(self):
        subprocess.run([sys.executable, '-I', str(OP), 'pending', 'approve', '0002'], cwd=self.project, env=self.human, capture_output=True, text=True)
        self.assertEqual(run(['send', '0002', '--', 'echo', 'x'], self.project).returncode, 6)
        (self.project / 'n.md').write_text('---\ntype: post\nchannel: x\n---\n두 번째 액션 없는 초안입니다. https://example.com\n', encoding='utf-8')
        run(['pending', 'add', 'n.md'], self.project)   # 0003
        subprocess.run([sys.executable, '-I', str(OP), 'pending', 'approve', '0003', '--action', 'echo human-chosen'], cwd=self.project, env=self.human, capture_output=True, text=True)
        sent = run(['send', '0003'], self.project)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertIn('human-chosen', sent.stdout)

    def test_action_cannot_smuggle_queue_commands(self):
        (self.project / 'e.md').write_text('---\ntype: post\nchannel: x\naction: op pending approve 0002\n---\n승인 명령을 숨긴 초안입니다. https://example.com\n', encoding='utf-8')
        run(['pending', 'add', 'e.md'], self.project)   # 0003
        subprocess.run([sys.executable, '-I', str(OP), 'pending', 'approve', '0003'], cwd=self.project, env=self.human, capture_output=True, text=True)
        self.assertEqual(run(['send', '0003'], self.project).returncode, 6)
