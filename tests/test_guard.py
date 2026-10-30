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

from _tty import TtyProcess, run_tty

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
        run(['init', '--stage', 'operate', '--send', 'agent'], self.project)
        (self.project / 'd.md').write_text('---\ntype: post\nchannel: x\naction: echo post-to-x\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n', encoding='utf-8')
        (self.project / 'n.md').write_text('---\ntype: post\nchannel: x\n---\n액션 없는 초안입니다. 지금 써보세요 https://example.com\n', encoding='utf-8')
        self.assertEqual(run(['pending', 'add', 'd.md'], self.project).returncode, 0)   # 0001 with action
        self.assertEqual(run(['pending', 'add', 'n.md'], self.project).returncode, 0)   # 0002 without action

    def tearDown(self):
        self.temp.cleanup()

    def approve(self, *args):
        """A person approving in their own terminal."""
        return run_tty([sys.executable, '-I', str(OP), 'pending', 'approve', *args], self.project, dict(os.environ))

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
        self.assertEqual(self.approve('0001').returncode, 0)
        other = run(['send', '0001', '--', 'echo', 'SOMETHING-ELSE'], self.project)
        self.assertEqual(other.returncode, 6, other.stderr)
        self.assertTrue(list((self.project / '.operator' / 'approved').glob('0001-*.md')))
        same = run(['send', '0001'], self.project)
        self.assertEqual(same.returncode, 0, same.stderr)
        self.assertIn('post-to-x', same.stdout)
        self.assertTrue(list((self.project / '.operator' / 'sent').glob('0001-*.md')))

    def test_ticket_without_action_cannot_be_sent_until_a_human_sets_one(self):
        self.approve('0002')
        self.assertEqual(run(['send', '0002', '--', 'echo', 'x'], self.project).returncode, 6)
        (self.project / 'n.md').write_text('---\ntype: post\nchannel: x\n---\n두 번째 액션 없는 초안입니다. https://example.com\n', encoding='utf-8')
        run(['pending', 'add', 'n.md'], self.project)   # 0003
        self.approve('0003', '--action', 'echo human-chosen')
        sent = run(['send', '0003'], self.project)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertIn('human-chosen', sent.stdout)

    def test_action_cannot_smuggle_queue_commands(self):
        (self.project / 'e.md').write_text('---\ntype: post\nchannel: x\naction: op pending approve 0002\n---\n승인 명령을 숨긴 초안입니다. https://example.com\n', encoding='utf-8')
        run(['pending', 'add', 'e.md'], self.project)   # 0003
        self.approve('0003')
        self.assertEqual(run(['send', '0003'], self.project).returncode, 6)


import http.server
import threading
import urllib.request as _ur


class _Recorder(http.server.BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode()
        _Recorder.calls.append((self.path, self.headers.get('Authorization'), body))
        self.send_response(201 if self.path.endswith('/2/tweets') else 200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        reply = {'data': {'id': '111'}} if 'tweets' in self.path else {'id': 'c-1'}
        self.wfile.write(json.dumps(reply).encode())


class DeliverServeFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='op deliver 한글 ')
        self.project = Path(self.temp.name).resolve()
        run(['init', '--stage', 'operate', '--send', 'agent'], self.project)
        _Recorder.calls = []
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Recorder)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.env = {**os.environ, 'HOME': str(self.project),
                    'OPERATOR_X_API': base, 'OPERATOR_THREADS_API': base, 'X_USER_ACCESS_TOKEN': 'secret-x-token',
                    'THREADS_USER_ID': '42', 'THREADS_ACCESS_TOKEN': 'secret-threads', 'OPERATOR_WEBHOOK_URL': base + '/hook'}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def op(self, *args, env=None, human=False):
        argv = [sys.executable, '-I', str(OP), *args]
        if human:   # in a terminal, the way a person types it
            return run_tty(argv, self.project, env or self.env)
        return subprocess.run(argv, cwd=self.project, env=env or self.env, capture_output=True, text=True)

    def add(self, channel, text='오늘 베타를 열었습니다. 지금 써보세요 https://example.com'):
        draft = self.project / f'{channel}.md'
        draft.write_text(f'---\ntype: post\nchannel: {channel}\n---\n{text}\n', encoding='utf-8')
        return self.op('pending', 'add', str(draft))

    def ticket(self, status, item_id):
        return next((self.project / '.operator' / status).glob(item_id + '-*.md')).read_text(encoding='utf-8')

    def test_supported_channel_gets_deliver_action_and_send_posts_to_x(self):
        self.add('x')
        self.assertIn('action: op deliver 0001', self.ticket('pending', '0001'))
        self.op('pending', 'approve', '0001', human=True)
        sent = self.op('send', '0001')
        self.assertEqual(sent.returncode, 0, sent.stdout + sent.stderr)
        self.assertIn('x 게시 완료 id=111', sent.stdout)
        path, auth, body = _Recorder.calls[0]
        self.assertEqual(path, '/2/tweets')
        self.assertEqual(auth, 'Bearer secret-x-token')
        self.assertEqual(json.loads(body)['text'], '오늘 베타를 열었습니다. 지금 써보세요 https://example.com')
        self.assertNotIn('secret-x-token', self.ticket('sent', '0001'))

    def test_threads_uses_container_then_publish(self):
        self.add('threads')
        self.op('pending', 'approve', '0001', human=True)
        sent = self.op('send', '0001')
        self.assertEqual(sent.returncode, 0, sent.stdout + sent.stderr)
        self.assertEqual([c[0] for c in _Recorder.calls], ['/v1.0/42/threads', '/v1.0/42/threads_publish'])

    def test_deliver_cannot_run_outside_send_and_is_guarded(self):
        self.add('x')
        self.op('pending', 'approve', '0001', human=True)
        self.assertEqual(self.op('deliver', '0001').returncode, 6)
        self.assertEqual(_Recorder.calls, [])
        self.assertEqual(self.op('guard', 'check', 'op deliver 0001').returncode, 1)
        self.assertEqual(self.op('guard', 'check', 'OPERATOR_SEND_TICKET=0001 op deliver 0001').returncode, 1)

    def test_missing_token_fails_without_printing_secrets_and_ticket_stays_approved(self):
        env = {k: v for k, v in self.env.items() if k != 'X_USER_ACCESS_TOKEN'}
        self.add('x')
        self.op('pending', 'approve', '0001', env=env, human=True)
        sent = self.op('send', '0001', env=env)
        self.assertNotEqual(sent.returncode, 0)
        self.assertIn('X_USER_ACCESS_TOKEN', sent.stdout)
        self.assertIn('0001', ''.join(p.name for p in (self.project / '.operator' / 'approved').iterdir()))
        check = self.op('deliver', '--check', env=env)
        self.assertIn('x', check.stdout)
        self.assertNotIn('secret', check.stdout)

    def test_reject_writes_feedback_for_the_next_draft(self):
        self.add('x')
        self.op('pending', 'reject', '0001', '--reason', '톤이 딱딱함', human=True)
        feedback = (self.project / '.operator' / 'feedback.md').read_text(encoding='utf-8')
        self.assertIn('톤이 딱딱함', feedback)
        self.assertIn('post/x', feedback)
        self.assertIn('톤이 딱딱함', self.op('feedback').stdout)
        self.assertIn('거절 기록: 1건', self.op('status').stdout)

    def test_serve_needs_token_and_approves_through_the_same_rules(self):
        self.add('x')
        self.add('webhook', '웹훅으로 보낼 두 번째 초안입니다 https://example.com')
        proc = TtyProcess([sys.executable, '-I', str(OP), 'serve', '--port', '0'], self.project, self.env)
        try:
            line = proc.readline()
            self.assertIn('승인 페이지: http://127.0.0.1:', line)
            url = line.split('승인 페이지: ', 1)[1].strip()
            base, token = url.split('/?t=')
            with self.assertRaises(Exception):
                _ur.urlopen(base + '/?t=wrong', timeout=5)
            page = _ur.urlopen(url, timeout=5).read().decode()
            self.assertIn('승인 대기 2건', page)
            self.assertIn('op deliver 0001', page)
            _ur.urlopen(_ur.Request(base + '/decide', data=('t=' + token + '&id=0001&d=approve&reason=').encode(), method='POST'), timeout=5).read()
            _ur.urlopen(_ur.Request(base + '/decide', data=('t=' + token + '&id=0002&d=reject&reason=%EB%84%88%EB%AC%B4+%EA%B8%B8%EB%8B%A4').encode(), method='POST'), timeout=5).read()
            self.assertTrue(list((self.project / '.operator' / 'approved').glob('0001-*.md')))
            self.assertTrue(list((self.project / '.operator' / 'rejected').glob('0002-*.md')))
            self.assertIn('너무 길다', (self.project / '.operator' / 'feedback.md').read_text(encoding='utf-8'))
            with self.assertRaises(Exception):
                _ur.urlopen(_ur.Request(base + '/decide', data=b't=wrong&id=0001&d=approve', method='POST'), timeout=5)
        finally:
            proc.close()

    def test_serve_refuses_without_a_terminal(self):
        self.assertEqual(self.op('serve').returncode, 7)
