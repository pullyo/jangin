"""Authority: where a human decision comes from, and that the CLI has no switch that turns an agent into a human.

Run from the repository root:  python3 -m unittest discover -s tests
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from _tty import run_tty

OP = Path(__file__).resolve().parents[1] / 'skills' / 'jangin' / 'scripts' / 'op.py'


def load_op():
    spec = importlib.util.spec_from_file_location('op_under_test', OP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


op = load_op()

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


class Base(unittest.TestCase):
    send = 'agent'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='op authority 한글 ')
        self.project = Path(self.temp.name).resolve() / 'proj'
        self.project.mkdir()
        self.env = {**os.environ, 'HOME': str(self.project.parent), 'OPERATOR_SECRET_BACKEND': 'file'}
        self.cli('init', '--stage', 'operate', '--send', self.send)
        self.od = str(self.project / '.operator')
        (self.project / 'd.md').write_text('---\ntype: post\nchannel: x\naction: echo posted\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n', encoding='utf-8')
        self.assertEqual(self.cli('pending', 'add', 'd.md').returncode, 0)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, env=None, tty=False):
        argv = [sys.executable, '-I', str(OP), *args]
        if tty:
            return run_tty(argv, self.project, env or self.env)
        return subprocess.run(argv, cwd=self.project, env=env or self.env, capture_output=True, text=True)

    def guard_json(self, **over):
        p = self.project / '.operator' / 'guard.json'
        g = json.loads(p.read_text(encoding='utf-8'))
        g.update(over)
        p.write_text(json.dumps(g), encoding='utf-8')

    def queue(self, status):
        return sorted(p.name[:4] for p in (self.project / '.operator' / status).glob('*.md'))


class CliTests(Base):
    def test_the_old_environment_switch_no_longer_makes_a_human(self):
        env = {**self.env, 'OPERATOR_ALLOW_NONINTERACTIVE_APPROVE': '1', 'OPERATOR_SECRET_VALUE': 'x'}
        for args in [('pending', 'approve', '0001'), ('stage', 'set', 'learn'), ('secret', 'set', 'X_CLIENT_ID'), ('serve',)]:
            with self.subTest(args=args):
                self.assertEqual(self.cli(*args, env=env).returncode, 7)
        self.assertEqual(self.queue('pending'), ['0001'])

    def test_terminal_decision_is_recorded_with_its_route(self):
        self.assertEqual(self.cli('pending', 'approve', '0001', '--no-send', tty=True).returncode, 0)
        ticket = next((self.project / '.operator' / 'approved').glob('0001-*.md')).read_text(encoding='utf-8')
        self.assertIn('decided_by: terminal', ticket)
        self.assertIn('사람의 결정 경로: terminal, local, messenger', self.cli('status').stdout)

    def test_hermes_project_refuses_even_a_real_terminal(self):
        self.guard_json(human_via=['local', 'messenger'])
        for args in [('pending', 'approve', '0001'), ('pending', 'reject', '0001', '--reason', 'x'), ('stage', 'set', 'learn'),
                     ('serve',), ('telegram',)]:
            with self.subTest(args=args):
                r = self.cli(*args, tty=True)
                self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertEqual(self.queue('pending'), ['0001'])
        self.assertIn('사람의 결정 경로: local, messenger', self.cli('status').stdout)

    def test_guard_blocks_calling_the_human_api_from_a_one_liner(self):
        for cmd in ["python3 -c \"import op; op.pending_decide('x', '0001', 'approve', op.Authority('messenger'))\"",
                    "python3 -c 'from op import *; stage_move(d, \"set\", Authority(\"messenger\"), to=\"operate\")'"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.cli('guard', 'check', cmd).returncode, 1)


class ApiTests(Base):
    def test_plugin_authority_approves_and_rejects_through_the_api(self):
        auth = op.Authority('messenger', 'hermes:telegram:42')
        res = op.pending_decide(self.od, '0001', 'approve', auth)
        self.assertEqual(res['meta']['status'], 'approved')
        self.assertEqual(res['meta']['decided_by'], 'messenger:hermes:telegram:42')
        self.assertIsNone(res['sent'])   # agent send mode: the agent runs op send later
        (self.project / 'e.md').write_text('---\ntype: post\nchannel: x\n---\n두 번째 초안입니다. 지금 써보세요 https://example.com\n', encoding='utf-8')
        self.cli('pending', 'add', 'e.md')
        op.pending_decide(self.od, '0002', 'reject', auth, note='너무 홍보 같다')
        self.assertEqual(self.queue('rejected'), ['0002'])
        self.assertIn('너무 홍보 같다', (self.project / '.operator' / 'feedback.md').read_text(encoding='utf-8'))

    def test_api_refuses_without_authority_or_on_a_closed_route(self):
        with self.assertRaises(op.OpError) as e:
            op.pending_decide(self.od, '0001', 'approve', None)
        self.assertEqual(e.exception.code, 7)
        self.guard_json(human_via=['messenger'])
        for kind in ('terminal', 'local'):
            with self.assertRaises(op.OpError) as e:
                op.pending_decide(self.od, '0001', 'approve', op.Authority(kind))
            self.assertEqual(e.exception.code, 7)
        with self.assertRaises(ValueError):
            op.Authority('plugin')
        self.assertEqual(self.queue('pending'), ['0001'])

    def test_stage_move_checks_and_records_the_route(self):
        auth = op.Authority('local', 'hermes:desktop')
        op.stage_move(self.od, 'set', auth, to='discover')
        with self.assertRaises(op.StageBlocked) as e:
            op.stage_move(self.od, 'advance', auth)
        self.assertTrue(any(not c[1] for c in e.exception.checks))
        (self.project / '.operator' / 'stages' / 'discover.md').write_text(DISCOVER, encoding='utf-8')
        self.assertTrue(op.stage_overview(self.od)['ready'])
        res = op.stage_move(self.od, 'advance', auth)
        self.assertEqual((res['from'], res['to']), ('discover', 'validate'))
        with self.assertRaises(op.OpError):
            op.stage_move(self.od, 'back', auth, to='discover')   # no reason
        st = json.loads((self.project / '.operator' / 'stage.json').read_text(encoding='utf-8'))
        self.assertEqual(st['history'][-1]['by'], 'local:hermes:desktop')

    def test_status_and_queue_reads_need_no_authority(self):
        s = op.status_summary(self.od)
        self.assertEqual(s['counts']['pending'], 1)
        self.assertEqual([it['id'] for it in op.queue_items(self.od)], ['0001'])


class HumanSendApiTests(Base):
    send = 'human'

    def test_approval_through_the_api_runs_the_action_in_the_caller(self):
        res = op.pending_decide(self.od, '0001', 'approve', op.Authority('local', 'hermes:cli'), secrets_env={})
        self.assertEqual(res['sent'][0], 0)
        self.assertEqual(self.queue('sent'), ['0001'])


if __name__ == '__main__':
    unittest.main()
