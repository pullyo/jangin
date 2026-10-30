"""op guard --format hermes: the payload Hermes' pre_tool_call shell hook sends, and the answer it understands.

Payload (agent/shell_hooks.py in Hermes 0.22): {"hook_event_name", "tool_name", "tool_input", "session_id", "cwd", "profile", "extra"}.
"cwd" is the gateway process's folder, not the session's. Blocking answer: exit 2 + {"action": "block", "message": ...}.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

OP = Path(__file__).resolve().parents[1] / 'skills' / 'operator' / 'scripts' / 'op.py'


class HermesGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='op hermes 한글 ')
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home'
        self.project = self.base / 'my project'
        self.gateway = self.base / 'gateway'   # where the Hermes gateway process runs
        for d in (self.home, self.project, self.gateway):
            d.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home)}
        subprocess.run([sys.executable, '-I', str(OP), 'init', '--stage', 'operate'], cwd=self.project, env=self.env, check=True,
                       capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def hook(self, tool_name, tool_input):
        payload = {'hook_event_name': 'pre_tool_call', 'tool_name': tool_name, 'tool_input': tool_input,
                   'session_id': 's1', 'cwd': str(self.gateway), 'profile': 'default', 'extra': {'task_id': 't'}}
        return subprocess.run([sys.executable, '-I', str(OP), 'guard', '--format', 'hermes'], cwd=self.gateway, env=self.env,
                              input=json.dumps(payload), capture_output=True, text=True)

    def assertBlocked(self, r):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        answer = json.loads(r.stdout)
        self.assertEqual(answer['action'], 'block')
        self.assertIn('operator 승인 게이트', answer['message'])

    def register(self):
        sys.path.insert(0, str(OP.parent))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location('op_reg', OP)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            sys.path.pop(0)
        old = os.environ.get('HOME')
        os.environ['HOME'] = str(self.home)
        try:
            mod.register_project(str(self.project))
        finally:
            os.environ['HOME'] = old

    def test_terminal_with_workdir_in_the_project_is_blocked(self):
        self.assertBlocked(self.hook('terminal', {'command': 'wrangler deploy', 'workdir': str(self.project)}))

    def test_allowed_call_exits_zero_with_no_output(self):
        r = self.hook('terminal', {'command': 'npm run build', 'workdir': str(self.project)})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ''))

    def test_file_tools_use_path_and_patch_v4a(self):
        self.assertBlocked(self.hook('write_file', {'path': str(self.project / '.operator' / 'stage.json'), 'content': '{}'}))
        self.assertBlocked(self.hook('patch', {'path': str(self.project / '.operator' / 'guard.json'), 'old_string': 'a', 'new_string': 'b'}))
        v4a = f'*** Begin Patch\n*** Update File: {self.project}/.operator/approved/0001-x.md\n@@\n-a\n+b\n*** End Patch\n'
        self.assertBlocked(self.hook('patch', {'mode': 'patch', 'patch': v4a}))
        self.assertBlocked(self.hook('read_file', {'path': str(self.home / '.config' / 'operator' / 'env')}))

    def test_execute_code_is_scanned(self):
        code = f"import subprocess\nsubprocess.run('cd \"{self.project}\" && git push', shell=True)"
        self.assertBlocked(self.hook('execute_code', {'code': code}))

    def test_without_workdir_only_registered_projects_are_assumed(self):
        # The hook cannot see the session folder: before registration a bare command is unknown territory.
        self.assertEqual(self.hook('terminal', {'command': 'wrangler deploy'}).returncode, 0)
        self.register()
        self.assertBlocked(self.hook('terminal', {'command': 'wrangler deploy'}))
        self.assertEqual(self.hook('terminal', {'command': 'ls'}).returncode, 0)
        # and the registry itself is out of the agent's reach
        self.assertBlocked(self.hook('write_file', {'path': str(self.home / '.config' / 'operator' / 'projects.json'), 'content': '[]'}))


if __name__ == '__main__':
    unittest.main()
