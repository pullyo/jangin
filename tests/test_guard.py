"""op guard: which operator projects a tool call can reach, and that each one's rules apply.

Run from the repository root:  python3 -m unittest discover -s tests
Every case feeds the hook JSON through the real `op.py guard` process, the way Claude Code / Codex do.
"""
import json
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
