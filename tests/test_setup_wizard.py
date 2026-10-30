"""`jangin setup` 한국어 마법사와 install.sh 가 만드는 `jangin` 명령.

마법사는 가짜 Hermes 창구와 미리 정한 답으로 돌린다. 설치 스크립트는 임시 HOME 과 가짜 `hermes` 명령으로 돌린다.
실제 ~/.hermes 와 실제 Hermes 는 건드리지 않는다.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WIZ = ROOT / 'hermes' / 'jangin' / 'setup_wizard.py'
spec = importlib.util.spec_from_file_location('setup_wizard', WIZ)
sw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sw)


class FakeHermes:
    def __init__(self, **info):
        self.state = {'model': 'gpt-6-sol', 'provider': 'openai-codex', 'plugins': ['jangin'], 'hooks': [],
                      'telegram': False, 'telegram_users': '', 'allow_all': False, 'operator_users': '', 'messengers': []}
        self.tools = info.pop('tools', None)
        self.state.update(info)
        self.calls = []

    def tool_states(self, platform='cli'):
        return dict(self.tools or {})

    def set_tool(self, name, on, platform='cli'):
        self.calls.append(('tool', name, on))
        self.tools[name] = on
        return True

    def info(self):
        return dict(self.state)

    def run_setup(self, section=None):
        self.calls.append(('setup', section))
        if section in ('model', None):
            self.state['provider'] = self.state['provider'] or 'nous'
        if section == 'gateway':
            self.state.update(telegram=True, messengers=['telegram'], telegram_users='424242')
        return 0

    def enable_plugin(self):
        self.calls.append(('enable',))
        self.state['plugins'].append('jangin')
        return True

    def set_env(self, key, value):
        self.calls.append(('env', key, value))
        self.state['operator_users'] = value

    def add_guard_hook(self, cmd):
        self.calls.append(('hook', cmd))
        self.state['hooks'].append(cmd)


class FakeUI:
    """Hermes 화면 부품 대신. answers 를 순서대로 쓰고, '' 는 기본값(엔터)."""
    def __init__(self, answers):
        self.answers, self.out = list(answers), []

    def _next(self):
        return self.answers.pop(0)

    def banner(self, *lines): self.out.extend(lines)
    def header(self, t): self.out.append('◆ ' + t)
    def info(self, *lines): self.out.extend(l for l in lines if l)
    def success(self, t): self.out.append('✓ ' + t)
    def warn(self, t): self.out.append('! ' + t)

    def ask(self, q, default=None):
        a = self._next()
        return a if a != '' else (default or '')

    def choose(self, q, options, default=0, description=None):
        a = self._next()
        return default if a == '' else int(a)

    def yes(self, q, default=True, description=None):
        a = self._next()
        return default if a == '' else a == 'y'

    def run_steps(self, steps):
        for _, fn in steps:
            fn()


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='op wizard 한글 ')
        self.home = os.path.join(self.tmp.name, 'hermes-home')
        self.folder = os.path.join(self.tmp.name, 'projects')

    def tearDown(self):
        self.tmp.cleanup()

    def run_wizard(self, fake, answers, run_hermes=True):
        self.ui = FakeUI(answers)
        code = sw.OperatorSetup(self.ui, fake, self.home, run_hermes=run_hermes).run()
        self.assertEqual(self.ui.answers, [], '답이 남았다 = 질문 수가 예상과 다르다')
        return code, json.loads(Path(sw.settings_path(self.home)).read_text(encoding='utf-8'))

    def test_defaults_run_the_full_hermes_wizard_first_then_operator_steps(self):
        fake = FakeHermes()
        # Hermes 기본 설정 진행(엔터) · 폴더 · 승인 방식(엔터) · 셸 훅(엔터)
        code, s = self.run_wizard(fake, ['', self.folder, '', ''])
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls[0], ('setup', None))
        self.assertEqual([c[0] for c in fake.calls], ['setup', 'hook'])
        self.assertIn('guard --format hermes', fake.calls[1][1])
        self.assertEqual(s['folder'], self.folder)
        self.assertTrue(os.path.isdir(self.folder))
        self.assertEqual(s['human_via'], ['local', 'messenger'])
        for h in ('◆ jangin 플러그인', '◆ 프로젝트 폴더', '◆ 승인 방식', '◆ 메신저 승인', '◆ 두 번째 잠금 (셸 훅)', '◆ Jangin 설정 완료'):
            self.assertIn(h, self.ui.out)
        self.assertTrue(any('☤ Jangin Setup' in l for l in self.ui.out))

    def test_strict_mode_opens_messenger_setup_and_narrows_operator_users(self):
        fake = FakeHermes()
        # Hermes 건너뜀 · 폴더 · 메신저만(1) · 메신저 설정 열기(엔터) · 허용 사용자(엔터 = 텔레그램 허용 사용자) · 셸 훅 n
        code, s = self.run_wizard(fake, ['n', self.folder, '1', '', '', 'n'])
        self.assertEqual(s['human_via'], ['messenger'])
        self.assertIn(('setup', 'gateway'), fake.calls)
        self.assertIn(('env', 'OPERATOR_ALLOWED_USERS', '424242'), fake.calls)
        self.assertNotIn('hook', [c[0] for c in fake.calls])

    def test_no_login_runs_the_hermes_wizard_without_asking_and_enables_plugin(self):
        fake = FakeHermes(provider=None, plugins=[])
        self.run_wizard(fake, [self.folder, '', 'n'])
        self.assertEqual(fake.calls[0], ('setup', None))
        self.assertIn(('enable',), fake.calls)

    def test_existing_hook_is_not_added_twice(self):
        fake = FakeHermes(hooks=[sw.guard_command()])
        self.run_wizard(fake, ['n', self.folder, ''])
        self.assertNotIn('hook', [c[0] for c in fake.calls])

    def test_operator_only_skips_the_hermes_wizard(self):
        fake = FakeHermes()
        self.run_wizard(fake, [self.folder, '', 'n'], run_hermes=False)
        self.assertNotIn('setup', [c[0] for c in fake.calls])

    def test_rerun_keeps_previous_answers_as_defaults(self):
        fake = FakeHermes()
        self.run_wizard(fake, ['n', self.folder, '1', 'n', 'n'])
        code, s = self.run_wizard(FakeHermes(), ['n', '', '', 'n', 'n'])
        self.assertEqual(s['folder'], self.folder)
        self.assertEqual(s['human_via'], ['messenger'])

    def test_tools_step_toggles_only_what_changes(self):
        fake = FakeHermes(tools={'web': False, 'computer_use': True, 'browser': True, 'x_search': False, 'kanban': False})
        # Hermes n · 폴더 · 승인 엔터 · 웹 켤까요(엔터=Y) · 화면 조작 n · 브라우저 엔터(유지) · X 검색 y · 칸반 엔터(유지) · 셸 훅 n
        self.run_wizard(fake, ['n', self.folder, '', '', 'n', '', 'y', '', 'n'])
        tool_calls = [c for c in fake.calls if c[0] == 'tool']
        self.assertEqual(tool_calls, [('tool', 'web', True), ('tool', 'computer_use', False), ('tool', 'x_search', True)])
        self.assertIn('◆ 도구', self.ui.out)
        self.assertTrue(any('승인 큐를 거치지 않습니다' in l for l in self.ui.out))   # 브라우저가 켜져 있으면 알림

    def test_needs_a_terminal(self):
        r = subprocess.run([sys.executable, '-I', str(WIZ)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)
        self.assertIn('터미널', r.stdout)


class PluginSettingsTests(unittest.TestCase):
    def test_idea_uses_the_approval_mode_chosen_in_setup(self):
        with tempfile.TemporaryDirectory(prefix='op wizard 한글 ') as tmp:
            spec2 = importlib.util.spec_from_file_location('op_commands', ROOT / 'hermes' / 'jangin' / 'commands.py')
            mod = importlib.util.module_from_spec(spec2)
            spec2.loader.exec_module(mod)
            data = os.path.join(tmp, 'data')
            os.makedirs(data)
            Path(data, 'settings.json').write_text(json.dumps({'folder': os.path.join(tmp, 'projects'), 'human_via': ['messenger']}), encoding='utf-8')
            old_home = os.environ.get('HOME')
            os.environ['HOME'] = tmp
            try:
                plugin = mod.Plugin(data)
                plugin.run('idea', '동네 빵집 예약', platform='desktop')
                proj = next(Path(tmp, 'projects').iterdir())
                guard = json.loads((proj / '.operator' / 'guard.json').read_text(encoding='utf-8'))
                self.assertEqual(guard['human_via'], ['messenger'])
                self.assertIn('메신저만', plugin.run('setup', ''))
            finally:
                os.environ['HOME'] = old_home


class InstallCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='op install 한글 ')
        self.home = Path(self.tmp.name)
        self.bin = self.home / 'fakebin'
        self.bin.mkdir()
        self.log = self.home / 'hermes.log'
        fake = self.bin / 'hermes'
        fake.write_text('#!/bin/sh\n'
                        f'echo "$*" >> "{self.log}"\n'
                        'if [ "$1" = "profile" ] && [ "$2" = "create" ]; then mkdir -p "$HOME/.hermes/profiles/$3"; fi\n'
                        'exit 0\n', encoding='utf-8')
        fake.chmod(0o755)
        self.env = {**os.environ, 'HOME': str(self.home), 'PATH': f'{self.bin}:{os.path.dirname(sys.executable)}:/usr/bin:/bin'}

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, *args):
        return subprocess.run(['sh', str(ROOT / 'hermes' / 'jangin' / 'install.sh'), *args], env=self.env, capture_output=True, text=True)

    def test_profile_install_creates_operator_command_that_routes_setup_to_the_wizard(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cmd = self.home / '.local' / 'bin' / 'jangin'
        self.assertTrue(cmd.exists())
        plug = self.home / '.hermes' / 'profiles' / 'jangin' / 'plugins' / 'jangin'
        self.assertTrue((plug / 'setup_wizard.py').exists())
        self.assertTrue((self.home / '.hermes' / 'profiles' / 'jangin' / 'skins' / 'jangin.yaml').exists())
        self.assertIn('config set display.skin jangin', self.log.read_text())
        self.assertIn('config set display.interface tui', self.log.read_text())
        subprocess.run([str(cmd), 'chat', '-q', 'hi'], env=self.env, capture_output=True, text=True)
        subprocess.run([str(cmd), 'setup', 'model'], env=self.env, capture_output=True, text=True)
        subprocess.run([str(cmd), 'setup', '--hermes'], env=self.env, capture_output=True, text=True)
        o = subprocess.run([str(cmd), 'setup', '--jangin-only'], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertIn('터미널', o.stdout)
        w = subprocess.run([str(cmd), 'setup'], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertIn('터미널', w.stdout)   # 마법사가 받았다 (터미널이 없어서 안내만)
        log = self.log.read_text().splitlines()
        self.assertIn('-p jangin chat -q hi', log)
        self.assertIn('-p jangin setup model', log)
        self.assertIn('-p jangin setup', log)       # --hermes 는 원래 마법사

    def test_test_home_install_does_not_touch_the_operator_command(self):
        r = self.install('--home', str(self.home / 'test-home'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.home / '.local' / 'bin' / 'jangin').exists())

    def test_default_home_install_points_the_command_at_the_default_profile(self):
        r = self.install('--home', str(self.home / '.hermes'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.home / '.local' / 'bin' / 'jangin').read_text()
        self.assertIn('-p "default"', text)


class BootstrapTests(unittest.TestCase):
    """저장소 맨 위 install.sh (한 줄 설치) 와 `jangin update`. 저장소 사본(.git 없음)과 가짜 hermes 로 돈다."""

    def setUp(self):
        import shutil
        self.tmp = tempfile.TemporaryDirectory(prefix='op bootstrap 한글 ')
        self.home = Path(self.tmp.name)
        self.src = self.home / 'src'
        self.src.mkdir()
        for part in ('install.sh', 'hermes', 'skills'):
            (shutil.copytree if (ROOT / part).is_dir() else shutil.copy2)(ROOT / part, self.src / part)
        self.bin = self.home / 'fakebin'
        self.bin.mkdir()
        self.log = self.home / 'hermes.log'
        fake = self.bin / 'hermes'
        fake.write_text('#!/bin/sh\n'
                        f'echo "$*" >> "{self.log}"\n'
                        'if [ "$1" = "profile" ] && [ "$2" = "create" ]; then mkdir -p "$HOME/.hermes/profiles/$3"; fi\n'
                        'if [ "$1" = "--version" ]; then echo "Hermes Agent v0.0 (fake)"; fi\n'
                        'exit 0\n', encoding='utf-8')
        fake.chmod(0o755)
        self.env = {**os.environ, 'HOME': str(self.home), 'PATH': f'{self.bin}:{os.path.dirname(sys.executable)}:/usr/bin:/bin',
                    'OPERATOR_SOURCE': str(self.src), 'OPERATOR_NO_SETUP': '1'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_line_install_creates_the_operator_profile_and_command(self):
        r = subprocess.run(['sh', str(self.src / 'install.sh')], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('[1/4] Hermes Agent: 이미 설치됨', r.stdout)
        self.assertTrue((self.home / '.hermes' / 'profiles' / 'jangin' / 'plugins' / 'jangin' / 'setup_wizard.py').exists())
        self.assertTrue((self.home / '.local' / 'bin' / 'jangin').exists())
        self.assertIn('profile create jangin', self.log.read_text())
        self.assertFalse((self.home / '.hermes' / 'plugins' / 'jangin').exists())   # 기본 프로필은 건드리지 않는다

    def test_without_hermes_and_without_consent_it_stops(self):
        env = {**self.env, 'PATH': f'{os.path.dirname(sys.executable)}:/usr/bin:/bin'}
        r = subprocess.run(['sh', str(self.src / 'install.sh')], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 1)
        self.assertIn('Hermes Agent 가 아직 없습니다', r.stdout)
        self.assertFalse((self.home / '.hermes').exists())

    def test_operator_update_updates_hermes_and_reinstalls(self):
        subprocess.run(['sh', str(self.src / 'install.sh')], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        r = subprocess.run([str(self.home / '.local' / 'bin' / 'jangin'), 'update'], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('update', self.log.read_text().splitlines())
        self.assertIn('설치 완료', r.stdout)


if __name__ == '__main__':
    unittest.main()
