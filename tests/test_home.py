"""`op` with no arguments: the one screen a person needs (approve, reject, advance the stage, connect a channel).

Run from the repository root:  python3 -m unittest discover -s tests
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from _tty import TtyProcess

OP = Path(__file__).resolve().parents[1] / 'skills' / 'jangin' / 'scripts' / 'op.py'

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


class Home(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='op home 한글 ')
        self.project = Path(self.temp.name).resolve() / 'bakery'
        self.project.mkdir()
        self.env = {**os.environ, 'HOME': str(self.project.parent), 'OPERATOR_SECRET_BACKEND': 'file'}
        self.env.pop('OPERATOR_WEBHOOK_URL', None)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, '-I', str(OP), *args], cwd=self.project, env=self.env,
                              capture_output=True, text=True)

    def home(self, keys, env=None):
        """Run `op` in a terminal and type `keys` (one answer per line)."""
        p = TtyProcess([sys.executable, '-I', str(OP)], self.project, env or self.env)
        try:
            os.write(p._master, ''.join(k + '\n' for k in keys).encode())
            out, err = p.communicate(60)
        finally:
            p.close()
        return p.returncode, out, err

    def add(self, name, text):
        (self.project / name).write_text(text, encoding='utf-8')
        r = self.cli('pending', 'add', name)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def queue(self, status):
        return sorted(p.name[:4] for p in (self.project / '.operator' / status).glob('*.md'))

    def test_outside_a_project_it_explains_how_to_start(self):
        r = self.cli()
        self.assertEqual(r.returncode, 0)
        self.assertIn('아직 jangin 프로젝트가 아니다', r.stdout)

    def test_without_a_terminal_it_only_lists(self):
        self.cli('init', '--stage', 'operate')
        self.add('a.md', '---\ntype: post\nchannel: x\naction: echo posted\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n')
        r = self.cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('확인할 것 1건', r.stdout)
        self.assertIn('`op`', r.stdout)
        self.assertEqual(self.queue('pending'), ['0001'])

    def test_approve_sends_and_reject_records_the_reason(self):
        self.cli('init', '--stage', 'operate')
        self.add('a.md', '---\ntype: post\nchannel: linkedin\naction: echo posted\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n')
        self.add('b.md', '---\ntype: post\nchannel: linkedin\naction: echo posted2\n---\n두 번째 소식입니다. 예약 페이지가 열렸어요 https://example.com\n')
        code, out, err = self.home(['a', 'r', '너무 딱딱함'])
        self.assertEqual(code, 0, out + err)
        self.assertIn('✓ 승인', out)
        self.assertEqual(self.queue('sent'), ['0001'])
        self.assertEqual(self.queue('rejected'), ['0002'])
        self.assertIn('너무 딱딱함', (self.project / '.operator' / 'feedback.md').read_text(encoding='utf-8'))

    def test_skip_and_quit_leave_items_pending(self):
        self.cli('init', '--stage', 'operate')
        self.add('a.md', '---\ntype: post\nchannel: linkedin\naction: echo posted\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n')
        self.add('b.md', '---\ntype: post\nchannel: linkedin\naction: echo posted2\n---\n두 번째 소식입니다. 예약 페이지가 열렸어요 https://example.com\n')
        code, out, _ = self.home(['s', 'q'])
        self.assertEqual(code, 0)
        self.assertEqual(self.queue('pending'), ['0001', '0002'])

    def test_stage_advance_is_just_another_item(self):
        self.cli('init')
        self.cli('stage', 'doc')
        (self.project / '.operator' / 'stages' / 'discover.md').write_text(DISCOVER, encoding='utf-8')
        code, out, err = self.home(['a'])
        self.assertEqual(code, 0, out + err)
        self.assertIn('다음 단계로: 발견 → 검증', out)
        self.assertIn('"stage": "validate"', (self.project / '.operator' / 'stage.json').read_text(encoding='utf-8'))
        self.assertIn('terminal', (self.project / '.operator' / 'stage.json').read_text(encoding='utf-8'))

    def test_unconnected_channel_is_offered_at_approval(self):
        self.cli('init', '--stage', 'operate')
        self.add('w.md', '---\ntype: post\nchannel: webhook\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n')
        code, out, _ = self.home(['a', 'n'])
        self.assertIn('아직 연결되지 않았다', out)
        self.assertEqual(self.queue('pending'), ['0001'])   # declined → untouched
        env = {**self.env, 'OPERATOR_SECRET_VALUE': 'http://127.0.0.1:9/hook'}
        code, out, err = self.home(['a', 'y'], env)
        self.assertIn('OPERATOR_WEBHOOK_URL 저장', out, out + err)
        self.assertEqual(self.queue('pending'), [])
        self.assertTrue(self.queue('approved') or self.queue('sent'))   # nothing listens on :9, so it stays approved

    def test_failed_send_comes_back_as_a_retry(self):
        self.cli('init', '--stage', 'operate')
        self.add('a.md', '---\ntype: post\nchannel: linkedin\naction: "false"\n---\n오늘 베타를 열었습니다. 지금 써보세요 https://example.com\n')
        self.home(['a'])
        self.assertEqual(self.queue('approved'), ['0001'])
        r = self.cli()
        self.assertIn('다시 보내기', r.stdout)


if __name__ == '__main__':
    unittest.main()
