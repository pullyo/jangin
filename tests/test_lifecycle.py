"""Stage model, human-side sending, secrets, X token refresh, X connect and Telegram approval.

Run from the repository root:  python3 -m unittest discover -s tests
Everything talks to local fake servers. HOME points at a temporary folder and secrets use the file backend,
so the real keychain and real accounts are never touched.
"""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

OP = Path(__file__).resolve().parents[1] / 'skills' / 'operator' / 'scripts' / 'op.py'


class Fake(http.server.BaseHTTPRequestHandler):
    """Records calls and answers from a per-test script: routes[(method, path-suffix)] -> list of (status, json)."""
    calls, routes = [], {}

    def log_message(self, *a):
        pass

    def _answer(self, method):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n).decode() if n else ''
        Fake.calls.append((method, self.path, self.headers.get('Authorization'), body))
        for (m, suffix), answers in Fake.routes.items():
            if m == method and urllib.parse.urlsplit(self.path).path.endswith(suffix):
                status, payload = answers.pop(0) if len(answers) > 1 else answers[0]
                break
        else:
            status, payload = 200, {'ok': True}
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self._answer('POST')

    def do_GET(self):
        self._answer('GET')


class Base(unittest.TestCase):
    stage, send = 'operate', 'human'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='op lifecycle 한글 ')
        self.project = Path(self.temp.name).resolve() / 'proj'
        self.project.mkdir()
        Fake.calls, Fake.routes = [], {}
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.agent = {k: v for k, v in os.environ.items() if k != 'OPERATOR_ALLOW_NONINTERACTIVE_APPROVE'}
        self.agent.update(HOME=str(self.project.parent), OPERATOR_SECRET_BACKEND='file', OPERATOR_SECURITY_BIN='/nonexistent',
                          OPERATOR_X_API=self.base, OPERATOR_TELEGRAM_API=self.base, OPERATOR_WEBHOOK_URL=self.base + '/hook')
        self.human = {**self.agent, 'OPERATOR_ALLOW_NONINTERACTIVE_APPROVE': '1'}
        args = ['init'] + (['--stage', self.stage] if self.stage else []) + ['--send', self.send]
        self.assertEqual(self.op(*args).returncode, 0)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def op(self, *args, human=False, env=None):
        return subprocess.run([sys.executable, '-I', str(OP), *args], cwd=self.project,
                              env=env or (self.human if human else self.agent), capture_output=True, text=True)

    def write(self, rel, text):
        p = self.project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def queue(self, status):
        return sorted(p.name[:4] for p in (self.project / '.operator' / status).glob('*.md'))


DISCOVER = """# 발견
## 문제
동네 빵집 사장님이 전화로 예약을 받느라 손님 응대를 못 한다.
## 고객
마포구 1인 운영 빵집 사장님. 상인회 단톡방에서 만난다.
## 제안
월 1만 원 예약 페이지. 문자 한 통으로 확인. 수수료 없음.
## 성공 지표
첫 달 유료 가입 사장님 3명.
"""


def validate_doc(decision):
    return f"""# 검증
## 근거
https://a.example.com 수수료 불만. https://b.example.com 커뮤니티 글. https://c.example.com 경쟁사 월 2만 원.
## 결정
단순하고 수수료가 없으면 차별점이 된다.
결정: {decision}
"""


class StageTests(Base):
    stage = None   # a brand-new project starts at discover

    def test_new_project_starts_at_discover_and_blocks_posts(self):
        self.assertIn('발견', self.op('stage').stdout)
        self.write('p.md', '---\ntype: post\nchannel: x\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n')
        self.assertEqual(self.op('pending', 'add', 'p.md').returncode, 8)
        self.write('r.md', '---\ntype: research\n---\n' + '조사 내용 ' * 50 + '\nhttps://a.example https://b.example https://c.example\n')
        self.assertEqual(self.op('pending', 'add', 'r.md').returncode, 0)

    def test_only_a_human_moves_the_stage_and_only_when_checks_pass(self):
        self.op('stage', 'doc')
        self.assertEqual(self.op('stage', 'check').returncode, 1)              # empty template fails
        self.assertEqual(self.op('stage', 'advance').returncode, 7)            # agent shell: no terminal
        self.assertEqual(self.op('stage', 'advance', human=True).returncode, 1)   # human, but checks fail
        self.write('.operator/stages/discover.md', DISCOVER)
        self.assertEqual(self.op('stage', 'check').returncode, 0)
        self.assertEqual(self.op('stage', 'advance', human=True).returncode, 0)
        st = json.loads((self.project / '.operator' / 'stage.json').read_text(encoding='utf-8'))
        self.assertEqual(st['stage'], 'validate')
        self.assertTrue(st['history'][-1]['doc_sha256'])
        self.assertTrue(list((self.project / '.operator' / 'stages' / 'history').glob('*-discover.md')))

    def test_validate_decision_picks_the_next_stage(self):
        self.write('.operator/stages/discover.md', DISCOVER)
        self.op('stage', 'advance', human=True)
        self.write('.operator/stages/validate.md', validate_doc('중단'))
        self.assertEqual(self.op('stage', 'advance', human=True).returncode, 1)
        self.write('.operator/stages/validate.md', validate_doc('수정'))
        self.op('stage', 'advance', human=True)
        self.assertIn('발견 (discover)', self.op('stage').stdout)
        self.op('stage', 'advance', human=True)
        self.write('.operator/stages/validate.md', validate_doc('진행'))
        self.op('stage', 'advance', human=True)
        self.assertIn('만들기 (build)', self.op('stage').stdout)

    def test_build_milestones_must_really_pass(self):
        self.op('stage', 'set', 'build', human=True)
        self.assertNotEqual(self.op('milestone', 'add', '폼', '--test', 'true').returncode, 0)
        self.assertEqual(self.op('milestone', 'add', '예약 폼', '--test', 'test -f form.html').returncode, 0)
        self.assertEqual(self.op('milestone', 'done', '1').returncode, 1)
        self.write('.operator/stages/build.md', '# 만들기\n## 범위\n예약 폼과 문자 알림만. 결제는 뺀다.\n')
        self.assertEqual(self.op('stage', 'advance', human=True).returncode, 1)
        self.write('form.html', '<form></form>')
        self.assertEqual(self.op('milestone', 'done', '1').returncode, 0)
        self.assertEqual(self.op('stage', 'advance', human=True).returncode, 0)
        self.assertIn('운영 (operate)', self.op('stage').stdout)

    def test_learn_needs_metrics_and_a_next_stage_line(self):
        self.op('stage', 'set', 'learn', human=True)
        self.write('.operator/stages/learn.md', '# 배우기\n## 결과\n가입 1명. 목표 3명에 못 미쳤다.\n## 다음\n카카오톡 알림을 원한다는 답이 많았다.\n다음 단계: 만들기\n')
        self.assertEqual(self.op('stage', 'check').returncode, 1)
        self.assertEqual(self.op('metric', 'add', 'signups', '1', '--source', '관리자 화면').returncode, 0)
        self.assertEqual(self.op('stage', 'advance', human=True).returncode, 0)
        self.assertIn('만들기 (build)', self.op('stage').stdout)
        self.assertIn('signups = 1', self.op('metric', 'list').stdout)

    def test_back_needs_a_reason_that_the_agent_then_sees(self):
        self.op('stage', 'set', 'build', human=True)
        self.assertNotEqual(self.op('stage', 'back', '--to', 'discover', human=True).returncode, 0)
        self.assertEqual(self.op('stage', 'back', '--to', 'discover', '--reason', '고객층이 틀렸다', human=True).returncode, 0)
        self.assertIn('고객층이 틀렸다', self.op('stage').stdout)

    def test_agent_cannot_edit_stage_state_or_rerun_init_to_skip(self):
        for cmd in ['echo {} > .operator/stage.json', 'cp x .operator/milestones.json', 'op stage advance', 'op stage set operate',
                    'python3 -c "open(\'.operator/metrics.jsonl\',\'a\')"']:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.op('guard', 'check', cmd).returncode, 1)
        r = subprocess.run([sys.executable, '-I', str(OP), 'guard', '--format', 'claude'], cwd=self.project, env=self.agent, text=True,
                           capture_output=True, input=json.dumps({'tool_name': 'Write', 'cwd': str(self.project),
                                                                  'tool_input': {'file_path': '.operator/stage.json', 'content': '{}'}}))
        self.assertEqual(r.returncode, 2)
        self.op('init', '--stage', 'operate')
        self.assertIn('발견', self.op('stage').stdout)


class HumanSendTests(Base):
    def setUp(self):
        super().setUp()
        Fake.routes = {('POST', '/hook'): [(200, {})]}
        self.write('w.md', '---\ntype: post\nchannel: webhook\n---\n웹훅으로 보낼 초안입니다 https://example.com\n')
        self.assertEqual(self.op('pending', 'add', 'w.md').returncode, 0)

    def test_agent_cannot_send_in_human_mode(self):
        self.op('pending', 'approve', '0001', '--no-send', human=True)
        r = self.op('send', '0001')
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertEqual([c for c in Fake.calls if c[1] == '/hook'], [])

    def test_human_approval_sends_right_away(self):
        r = self.op('pending', 'approve', '0001', human=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.queue('sent'), ['0001'])
        self.assertEqual(json.loads(Fake.calls[-1][3])['text'], '웹훅으로 보낼 초안입니다 https://example.com')


class SecretTests(Base):
    def test_file_backend_keeps_values_out_of_output_and_reach(self):
        env = {**self.human, 'OPERATOR_SECRET_VALUE': 'tok-123'}
        self.assertEqual(self.op('secret', 'set', 'X_USER_ACCESS_TOKEN', env=env).returncode, 0)
        envfile = self.project.parent / '.config' / 'operator' / 'env'
        self.assertIn('X_USER_ACCESS_TOKEN=tok-123', envfile.read_text())
        self.assertEqual(oct(envfile.stat().st_mode & 0o777), '0o600')
        listing = self.op('secret', 'list').stdout + self.op('deliver', '--check').stdout
        self.assertNotIn('tok-123', listing)
        self.assertEqual(self.op('secret', 'set', 'X_USER_ACCESS_TOKEN', env={**self.agent, 'OPERATOR_SECRET_VALUE': 'x'}).returncode, 7)
        for cmd in [f'cat {envfile}', 'cat ~/.config/operator/env', 'security find-generic-password -s operator -w', 'printenv',
                    'op secret set X_CLIENT_ID']:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.op('guard', 'check', cmd).returncode, 1)
        for cmd in ['python3 -m venv env', 'source env/bin/activate', 'npm run dev', '/usr/bin/env python3 x.py']:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.op('guard', 'check', cmd).returncode, 0)
        for cmd in ['env', 'env | grep TOKEN', 'ls && env > /tmp/e', 'set | grep X_']:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.op('guard', 'check', cmd).returncode, 1)
        r = subprocess.run([sys.executable, '-I', str(OP), 'guard'], cwd=self.project, env=self.agent, text=True, capture_output=True,
                           input=json.dumps({'tool_name': 'Read', 'cwd': str(self.project), 'tool_input': {'file_path': str(envfile)}}))
        self.assertEqual(r.returncode, 2)

    def test_keychain_value_goes_through_stdin_not_argv(self):
        log = self.project.parent / 'security.log'
        fake = self.write('fake-security', f'#!/bin/sh\necho "ARGS $*" >> "{log}"\ncat >> "{log}"\n')
        fake.chmod(0o755)
        env = {**self.human, 'OPERATOR_SECURITY_BIN': str(fake), 'OPERATOR_SECRET_VALUE': 'kc-secret"9'}
        self.assertEqual(self.op('secret', 'set', 'THREADS_ACCESS_TOKEN', '--keychain', env=env).returncode, 0)
        text = log.read_text()
        self.assertIn('ARGS -i', text)
        self.assertNotIn('kc-secret', text.splitlines()[0])
        self.assertIn('-T "" -w "kc-secret\\"9"', text)
        idx = json.loads((self.project.parent / '.config' / 'operator' / 'secrets.json').read_text())
        self.assertEqual(idx['THREADS_ACCESS_TOKEN'], 'keychain')


class XRefreshTests(Base):
    def test_expired_token_is_refreshed_once_and_stored(self):
        env = {**self.human, 'OPERATOR_SECRET_VALUE': ''}
        for name, value in [('X_USER_ACCESS_TOKEN', 'old-access'), ('X_REFRESH_TOKEN', 'old-refresh'), ('X_CLIENT_ID', 'cid')]:
            self.op('secret', 'set', name, env={**env, 'OPERATOR_SECRET_VALUE': value})
        Fake.routes = {('POST', '/2/tweets'): [(401, {'title': 'Unauthorized'}), (201, {'data': {'id': '777'}})],
                       ('POST', '/2/oauth2/token'): [(200, {'access_token': 'new-access', 'refresh_token': 'new-refresh'})]}
        self.write('x.md', '---\ntype: post\nchannel: x\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n')
        self.op('pending', 'add', 'x.md')
        r = self.op('pending', 'approve', '0001', human=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('x 게시 완료 id=777', r.stdout)
        auths = [c[2] for c in Fake.calls if c[1] == '/2/tweets']
        self.assertEqual(auths, ['Bearer old-access', 'Bearer new-access'])
        token_call = next(c for c in Fake.calls if c[1] == '/2/oauth2/token')
        self.assertIn('grant_type=refresh_token', token_call[3])
        self.assertIn('refresh_token=old-refresh', token_call[3])
        stored = (self.project.parent / '.config' / 'operator' / 'env').read_text()
        self.assertIn('X_REFRESH_TOKEN=new-refresh', stored)
        self.assertNotIn('new-access', r.stdout + ''.join(p.read_text() for p in (self.project / '.operator' / 'sent').glob('*.md')))

    def test_connect_x_runs_pkce_and_stores_tokens(self):
        self.op('secret', 'set', 'X_CLIENT_ID', env={**self.human, 'OPERATOR_SECRET_VALUE': 'cid'})
        Fake.routes = {('POST', '/2/oauth2/token'): [(200, {'access_token': 'acc', 'refresh_token': 'ref'})]}
        env = {**self.human, 'OPERATOR_X_AUTHORIZE': self.base + '/authorize'}
        proc = subprocess.Popen([sys.executable, '-I', str(OP), 'connect', 'x', '--port', '0', '--no-browser', '--timeout', '20'],
                                cwd=self.project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            proc.stdout.readline()
            url = proc.stdout.readline().strip()
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertEqual(q['code_challenge_method'], ['S256'])
            self.assertIn('offline.access', q['scope'][0])
            with self.assertRaises(Exception):
                urllib.request.urlopen(q['redirect_uri'][0] + '?code=evil&state=wrong', timeout=5)
            urllib.request.urlopen(q['redirect_uri'][0] + '?code=good&state=' + q['state'][0], timeout=5).read()
            out, err = proc.communicate(timeout=20)
        finally:
            proc.kill()
        self.assertEqual(proc.returncode, 0, err)
        body = next(c for c in Fake.calls if c[1] == '/2/oauth2/token')[3]
        self.assertIn('code=good', body)
        self.assertIn('code_verifier=', body)
        self.assertIn('X_REFRESH_TOKEN=ref', (self.project.parent / '.config' / 'operator' / 'env').read_text())


class TelegramTests(Base):
    def setUp(self):
        super().setUp()
        for name, value in [('TELEGRAM_BOT_TOKEN', 'bot123'), ('TELEGRAM_CHAT_ID', '42')]:
            self.op('secret', 'set', name, env={**self.human, 'OPERATOR_SECRET_VALUE': value})
        self.write('p.md', '---\ntype: post\nchannel: x\naction: echo posted-by-telegram\n---\n텔레그램으로 승인할 초안입니다 https://example.com\n')
        self.write('q.md', '---\ntype: post\nchannel: x\naction: echo second\n---\n두 번째 초안입니다. 거절될 예정 https://example.com\n')
        self.op('pending', 'add', 'p.md')
        self.op('pending', 'add', 'q.md')

    def updates(self, *items):
        Fake.routes[('POST', '/getUpdates')] = [(200, {'ok': True, 'result': list(items)})]

    def run_once(self):
        return self.op('telegram', '--once', human=True)

    def test_button_from_the_right_chat_approves_and_sends(self):
        self.updates({'update_id': 1, 'callback_query': {'id': 'c1', 'data': 'a:0001', 'from': {'id': 42},
                                                        'message': {'message_id': 9, 'chat': {'id': 42}}}})
        r = self.run_once()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.queue('sent'), ['0001'])
        cards = [json.loads(c[3]) for c in Fake.calls if c[1].endswith('/sendMessage')]
        self.assertTrue(any('텔레그램으로 승인할 초안' in m['text'] and m['reply_markup'] for m in cards))
        self.assertTrue(all('/botbot123/' in c[1] for c in Fake.calls))
        self.assertNotIn('bot123', r.stdout + r.stderr)

    def test_other_chats_are_ignored(self):
        self.updates({'update_id': 1, 'callback_query': {'id': 'c1', 'data': 'a:0001', 'from': {'id': 7},
                                                        'message': {'message_id': 9, 'chat': {'id': 7}}}},
                     {'update_id': 2, 'message': {'chat': {'id': 7}, 'text': '/approve 0002'}})
        self.run_once()
        self.assertEqual(self.queue('pending'), ['0001', '0002'])

    def test_reject_button_then_reason_reaches_feedback(self):
        self.updates({'update_id': 1, 'callback_query': {'id': 'c1', 'data': 'r:0002', 'from': {'id': 42},
                                                        'message': {'message_id': 9, 'chat': {'id': 42}}}},
                     {'update_id': 2, 'message': {'chat': {'id': 42}, 'text': '너무 홍보 같다'}})
        self.run_once()
        self.assertEqual(self.queue('rejected'), ['0002'])
        self.assertIn('너무 홍보 같다', (self.project / '.operator' / 'feedback.md').read_text(encoding='utf-8'))

    def test_needs_a_terminal(self):
        self.assertEqual(self.op('telegram', '--once').returncode, 7)


if __name__ == '__main__':
    unittest.main()
