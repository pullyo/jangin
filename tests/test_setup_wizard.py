"""`operator setup` 한국어 마법사와 install.sh 가 만드는 `operator` 명령.

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
WIZ = ROOT / 'hermes' / 'operator' / 'setup_wizard.py'
spec = importlib.util.spec_from_file_location('setup_wizard', WIZ)
sw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sw)


class FakeHermes:
    def __init__(self, **info):
        self.state = {'model': 'gpt-6-sol', 'provider': 'openai-codex', 'plugins': ['operator'], 'hooks': [],
                      'telegram': False, 'telegram_users': '', 'allow_all': False, 'operator_users': '', 'messengers': []}
        self.state.update(info)
        self.calls = []

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
        self.state['plugins'].append('operator')
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
        for h in ('◆ operator 플러그인', '◆ 프로젝트 폴더', '◆ 승인 방식', '◆ 메신저 승인', '◆ 두 번째 잠금 (셸 훅)', '◆ Operator 설정 완료'):
            self.assertIn(h, self.ui.out)
        self.assertTrue(any('☤ Operator Setup' in l for l in self.ui.out))

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

    def test_needs_a_terminal(self):
        r = subprocess.run([sys.executable, '-I', str(WIZ)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)
        self.assertIn('터미널', r.stdout)


class PluginSettingsTests(unittest.TestCase):
    def test_idea_uses_the_approval_mode_chosen_in_setup(self):
        with tempfile.TemporaryDirectory(prefix='op wizard 한글 ') as tmp:
            spec2 = importlib.util.spec_from_file_location('op_commands', ROOT / 'hermes' / 'operator' / 'commands.py')
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
        return subprocess.run(['sh', str(ROOT / 'hermes' / 'operator' / 'install.sh'), *args], env=self.env, capture_output=True, text=True)

    def test_profile_install_creates_operator_command_that_routes_setup_to_the_wizard(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cmd = self.home / '.local' / 'bin' / 'operator'
        self.assertTrue(cmd.exists())
        plug = self.home / '.hermes' / 'profiles' / 'operator' / 'plugins' / 'operator'
        self.assertTrue((plug / 'setup_wizard.py').exists())
        subprocess.run([str(cmd), 'chat', '-q', 'hi'], env=self.env, capture_output=True, text=True)
        subprocess.run([str(cmd), 'setup', 'model'], env=self.env, capture_output=True, text=True)
        subprocess.run([str(cmd), 'setup', '--hermes'], env=self.env, capture_output=True, text=True)
        o = subprocess.run([str(cmd), 'setup', '--operator-only'], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertIn('터미널', o.stdout)
        w = subprocess.run([str(cmd), 'setup'], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertIn('터미널', w.stdout)   # 마법사가 받았다 (터미널이 없어서 안내만)
        log = self.log.read_text().splitlines()
        self.assertIn('-p operator chat -q hi', log)
        self.assertIn('-p operator setup model', log)
        self.assertIn('-p operator setup', log)       # --hermes 는 원래 마법사

    def test_test_home_install_does_not_touch_the_operator_command(self):
        r = self.install('--home', str(self.home / 'test-home'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.home / '.local' / 'bin' / 'operator').exists())

    def test_default_home_install_points_the_command_at_the_default_profile(self):
        r = self.install('--home', str(self.home / '.hermes'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.home / '.local' / 'bin' / 'operator').read_text()
        self.assertIn('-p "default"', text)


if __name__ == '__main__':
    unittest.main()
