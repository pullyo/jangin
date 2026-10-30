"""hermes/jangin: the slash-command core, tested without Hermes.

The live check against a real Hermes install is hermes/check_live.py (manual; it needs Hermes' own Python).
"""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OP = ROOT / 'skills' / 'jangin' / 'scripts' / 'op.py'

DISCOVER = (ROOT / 'tests' / 'test_authority.py').read_text(encoding='utf-8').split('DISCOVER = """', 1)[1].split('"""', 1)[0]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='op plugin 한글 ')
        self.base = Path(self.temp.name).resolve()
        self.old_home = os.environ.get('HOME')
        os.environ['HOME'] = str(self.base / 'home')
        (self.base / 'home').mkdir()
        self.commands = load('operator_commands_under_test', ROOT / 'hermes' / 'jangin' / 'commands.py')
        self.op = self.commands.op
        self.plugin = self.commands.Plugin(str(self.base / 'plugin-data'))
        self.plugin.run('setup', f'folder "{self.base / "projects"}"')
        self.out = self.plugin.run('idea', '동네 빵집 예약 페이지')
        self.project = next((self.base / 'projects').iterdir())
        self.od = str(self.project / '.operator')

    def tearDown(self):
        os.environ['HOME'] = self.old_home
        self.temp.cleanup()

    def desktop(self, name, args=''):
        return self.plugin.run(name, args, platform='desktop')

    def phone(self, name, args='', user='42'):
        return self.plugin.run(name, args, platform='telegram', user_id=user, from_messenger=True)

    def add(self, text, kind='post', channel='webhook', action=None):
        p = self.project / 'draft.md'
        head = f'---\ntype: {kind}\n' + (f'channel: {channel}\n' if channel else '') + (f'action: {action}\n' if action else '') + '---\n'
        p.write_text(head + text + '\n', encoding='utf-8')
        meta = self.op.queue_items(self.od)
        old_cwd = os.getcwd()
        os.chdir(self.project)
        try:
            self.op.cmd_pending(['add', str(p)])
        finally:
            os.chdir(old_cwd)
        return [it['id'] for it in self.op.queue_items(self.od) if it not in meta][-1]

    def test_idea_makes_a_hermes_project_that_refuses_the_terminal(self):
        self.assertIn('새 프로젝트', self.out)
        self.assertEqual(self.op.human_via(self.od), ['local', 'messenger'])
        self.assertEqual(self.op.current_stage(self.od), 'discover')
        self.assertIn('아이디어 (사용자가 처음 한 말): 동네 빵집 예약 페이지', (self.project / '.operator/stages/discover.md').read_text(encoding='utf-8'))
        self.assertIn(str(self.project), json.loads((self.base / 'home/.config/operator/projects.json').read_text()))
        with self.assertRaises(self.op.OpError):
            self.op.pending_decide(self.od, '0001', 'approve', self.op.Authority('terminal'))

    def test_stage_flow_records_who_moved_it(self):
        self.assertIn('아직', self.desktop('stage'))
        self.assertIn('통과하지 못한 항목', self.desktop('advance'))
        (self.project / '.operator/stages/discover.md').write_text(DISCOVER, encoding='utf-8')
        self.assertIn('/advance', self.desktop('stage'))
        self.assertIn('발견 → 검증', self.phone('advance'))
        st = json.loads((self.project / '.operator/stage.json').read_text(encoding='utf-8'))
        self.assertEqual(st['history'][-1]['by'], 'messenger:hermes:telegram:42')
        self.assertEqual(self.desktop('back', '발견'), self.commands.HELP['back'])
        self.assertIn('검증 → 발견', self.desktop('back', '발견 고객이 너무 넓다'))
        self.assertIn('고객이 너무 넓다', self.desktop('stage'))

    def test_ok_from_the_phone_sends_in_the_gateway(self):
        self.op.stage_move(self.od, 'set', self.op.Authority('local'), to='operate')
        iid = self.add('알림으로 보낼 초안입니다 https://example.com', action='echo sent-by-plugin')
        self.assertIn(f'/ok {iid}', self.desktop('inbox'))
        self.plugin._secrets = {}   # tokens were unlocked earlier; the webhook action needs none
        out = self.phone('ok', iid)
        self.assertIn('발송 완료', out)
        self.assertEqual([it['id'] for it in self.op.queue_items(self.od, ('sent',))], [iid])
        meta = self.op.queue_items(self.od, ('sent',))[0]['meta']
        self.assertEqual(meta['decided_by'], 'messenger:hermes:telegram:42')

    def test_reject_reason_and_aliases(self):
        self.add('조사 내용 ' * 50 + '\nhttps://a.example https://b.example https://c.example', kind='research', channel=None)
        self.assertIn('0001', self.plugin.run('jangin', 'queue', platform='desktop'))
        self.assertIn('거절했습니다', self.phone('reject', '0001 출처가 블로그뿐이다'))
        self.assertIn('출처가 블로그뿐이다', (self.project / '.operator/feedback.md').read_text(encoding='utf-8'))
        self.assertIn('/ok <번호>', self.plugin.run('jangin', 'help'))

    def test_messenger_only_project_and_allowlist(self):
        g = json.loads((self.project / '.operator/guard.json').read_text(encoding='utf-8'))
        g['human_via'] = ['messenger']
        (self.project / '.operator/guard.json').write_text(json.dumps(g), encoding='utf-8')
        (self.project / '.operator/stages/discover.md').write_text(DISCOVER, encoding='utf-8')
        self.assertIn('messenger 경로로만', self.desktop('advance'))
        strict = self.commands.Plugin(str(self.base / 'plugin-data'), allowed_users=['42'])
        self.assertIn('권한이 없습니다', strict.run('advance', '', platform='telegram', user_id='7', from_messenger=True))
        self.assertIn('발견 → 검증', strict.run('advance', '', platform='telegram', user_id='42', from_messenger=True))

    def test_plugin_hook_knows_the_session_folder(self):
        # The shell hook only sees the gateway's folder; the plugin hook gets the session cwd from Hermes.
        self.assertIn('승인 게이트', self.plugin.guard('terminal', {'command': 'wrangler deploy'}, str(self.project)))
        self.assertIsNone(self.plugin.guard('terminal', {'command': 'npm run build'}, str(self.project)))
        self.assertIn('승인 게이트', self.plugin.guard('write_file', {'path': '.operator/stage.json', 'content': '{}'}, str(self.project)))
        self.assertIn('승인 게이트', self.plugin.guard('read_file', {'path': str(self.base / 'home/.config/operator/env')}, '/'))
        self.assertIn('승인 게이트', self.plugin.guard('execute_code', {'code': 'import op; op.pending_decide(d, "0001", "approve", op.Authority("local"))'}, str(self.project)))
        self.assertIsNone(self.plugin.guard('web_search', {'query': 'git push'}, str(self.project)))
        # no session folder (e.g. outside a turn): registered projects' rules apply
        self.assertIn('승인 게이트', self.plugin.guard('terminal', {'command': 'wrangler deploy'}, ''))
        self.assertIsNone(self.plugin.guard('terminal', {'command': 'ls'}, ''))


if __name__ == '__main__':
    unittest.main()
