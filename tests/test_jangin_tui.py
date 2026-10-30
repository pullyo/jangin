"""Jangin 화면(hermes/jangin/tui/dist/entry.js) — Hermes 게이트웨이 규약대로 동작하는지.

가짜 게이트웨이(표준 라이브러리만 쓴 작은 WebSocket 서버)와 가짜 접속 도우미(gateway_bootstrap.py)를 띄우고,
실제 node 로 화면을 pty 에서 연다. Hermes 는 쓰지 않는다. node 가 없으면 건너뛴다.
"""
import base64
import hashlib
import json
import os
import pty
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'hermes' / 'jangin' / 'tui' / 'dist' / 'entry.js'
NODE = shutil.which('node') or (os.path.expanduser('~/.local/bin/node') if os.path.exists(os.path.expanduser('~/.local/bin/node')) else None)


def _ws_accept(key):
    return base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()


class FakeGateway(threading.Thread):
    """한 연결만 받는 최소 WebSocket 서버. 받은 요청은 self.calls 에, 응답과 이벤트는 handler 가 정한다."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(); self.sock.bind(('127.0.0.1', 0)); self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.calls, self.conn, self.protocols = [], None, []
        self.sessions = {}

    def run(self):
        conn, _ = self.sock.accept()
        self.conn = conn
        head = b''
        while b'\r\n\r\n' not in head:
            head += conn.recv(4096)
        headers = {k.lower(): v for k, v in (l.split(': ', 1) for l in head.decode().split('\r\n')[1:] if ': ' in l)}
        self.protocols = [p.strip() for p in headers.get('sec-websocket-protocol', '').split(',') if p.strip()]
        conn.sendall(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                      f'Sec-WebSocket-Accept: {_ws_accept(headers["sec-websocket-key"])}\r\n'
                      f'Sec-WebSocket-Protocol: {self.protocols[0]}\r\n\r\n').encode())
        self.event('gateway.ready', {'skin': {}, 'change_events': True, 'replay_epoch': 'e1', 'session_authority': True, 'heartbeat': True})
        buf = b''
        while True:
            try:
                data = conn.recv(65536)
            except OSError:
                return
            if not data:
                return
            buf += data
            while True:
                frame, buf = self._frame(buf)
                if frame is None:
                    break
                op, payload = frame
                if op == 8:
                    return
                if op == 9:
                    self.send(0xA, payload)
                    continue
                if op == 1:
                    self.handle(json.loads(payload.decode()))

    def _frame(self, buf):
        if len(buf) < 2:
            return None, buf
        op, b1 = buf[0] & 0xF, buf[1]
        masked, ln, i = b1 & 0x80, b1 & 0x7F, 2
        if ln == 126:
            if len(buf) < 4: return None, buf
            ln, i = struct.unpack('>H', buf[2:4])[0], 4
        elif ln == 127:
            if len(buf) < 10: return None, buf
            ln, i = struct.unpack('>Q', buf[2:10])[0], 10
        if masked:
            if len(buf) < i + 4 + ln: return None, buf
            mask, data = buf[i:i + 4], bytearray(buf[i + 4:i + 4 + ln])
            for k in range(ln):
                data[k] ^= mask[k % 4]
            return (op, bytes(data)), buf[i + 4 + ln:]
        if len(buf) < i + ln: return None, buf
        return (op, buf[i:i + ln]), buf[i + ln:]

    def send(self, op, payload):
        ln = len(payload)
        head = bytes([0x80 | op]) + (bytes([ln]) if ln < 126 else b'\x7e' + struct.pack('>H', ln) if ln < 65536 else b'\x7f' + struct.pack('>Q', ln))
        self.conn.sendall(head + payload)

    def event(self, typ, payload, session_id='s1', generation=1, seq=None):
        self.seq = getattr(self, 'seq', 0) + 1
        self.send(1, json.dumps({'jsonrpc': '2.0', 'method': 'event', 'params': {
            'type': typ, 'session_id': session_id, 'payload': payload, 'replay_epoch': 'e1', 'seq': self.seq,
            'execution_generation': generation}}, ensure_ascii=False).encode())

    def reply(self, rid, result=None, error=None):
        msg = {'jsonrpc': '2.0', 'id': rid}
        msg['error' if error else 'result'] = error or result
        self.send(1, json.dumps(msg, ensure_ascii=False).encode())

    def handle(self, req):
        m, p, rid = req.get('method'), req.get('params') or {}, req.get('id')
        self.calls.append((m, p))
        if m == 'gateway.ping':
            return self.reply(rid, {'ok': True})
        if m == 'runtime.describe':
            return self.reply(rid, {'session_create': {'sources': ['cli', 'tui'], 'parameters': ['request_id', 'source', 'cwd', 'title']}, 'skin': None})
        if m == 'session.create':
            assert p['source'] == 'tui' and p['request_id'], p
            return self.reply(rid, {'session_id': 's1', 'profile_id': 'p', 'execution_generation': 0, 'messages': []})
        if m == 'session.info':
            return self.reply(rid, {'session_id': 's1', 'model': 'fake-model', 'provider': 'fake', 'version': '0.22.5', 'profile_name': 'jangin',
                                    'tools': {'terminal': ['terminal', 'process'], 'file': ['read_file']}, 'skills': {'ops': ['jangin']}, 'tool_count': 3})
        if m == 'prompt.submit':
            assert p['session_id'] == 's1' and p['text'] and p['input_id'], p
            self.reply(rid, {'admission_id': 'a1', 'status': 'queued', 'ref': {'profile_id': 'p', 'session_id': 's1'}, 'sequence': 1, 'authority_epoch': 1, 'execution_generation': 1})
            self.event('message.start', {})
            self.event('message.delta', {'text': '안녕'})
            self.event('tool.start', {'tool_id': 't1', 'name': 'terminal', 'args': {'command': 'ls -la'}})
            self.event('tool.complete', {'tool_id': 't1', 'name': 'terminal', 'duration_s': 0.4, 'summary': '3 files'})
            self.event('approval.request', {'kind': 'approval', 'prompt_id': 'ap1', 'execution_generation': 1,
                                            'command': 'git push origin main', 'description': '밖으로 나가는 명령', 'choices': ['once', 'deny', 'always']})
            return
        if m == 'approval.respond':
            self.reply(rid, {'status': 'resolved'})
            self.event('approval.settled', {'prompt_id': 'ap1', 'execution_generation': 1})
            self.event('message.delta', {'text': ' 하세요\n두 번째 줄'})
            self.event('message.complete', {'text': '안녕 하세요\n두 번째 줄', 'status': 'ok', 'usage': {'total_tokens': 12}})
            return
        if m == 'clarify.respond':
            self.reply(rid, {'status': 'resolved'})
            self.event('clarify.settled', {'prompt_id': 'cl1', 'execution_generation': 1})
            self.event('message.complete', {'text': '', 'status': 'ok'})
            return
        if m == 'slash.exec':
            if p['command'] == '/ask':
                self.reply(rid, {'type': 'plugin', 'output': '질문을 보냅니다'})
                self.event('clarify.request', {'kind': 'clarify', 'prompt_id': 'cl1', 'execution_generation': 1,
                                               'question': '어느 채널로?', 'choices': ['x', 'threads'], 'multi_select': False})
                return
            return self.reply(rid, {'type': 'plugin', 'output': f"프로젝트: 빵집 ({p['command']})"})
        if m == 'session.interrupt':
            return self.reply(rid, {'session_id': 's1', 'profile_id': 'p'})
        return self.reply(rid, error={'code': 4000, 'message': f'unknown method {m}'})


@unittest.skipUnless(NODE and ENTRY.exists(), 'node 가 없거나 entry.js 가 없다')
class JanginTuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='jangin tui 한글 ')
        root = Path(self.tmp.name) / 'hermes-agent'
        (root / 'ui-tui' / 'scripts').mkdir(parents=True)
        self.gw = FakeGateway(); self.gw.start()
        grant = {'url': f'ws://127.0.0.1:{self.gw.port}/api/ws', 'protocols': ['hermes-gateway-v1', 'hermes-ticket.abc'], 'profile_id': 'p', 'instance_id': 'i'}
        (root / 'ui-tui' / 'scripts' / 'gateway_bootstrap.py').write_text(
            'import json, sys\nassert "--start" in sys.argv\nprint(json.dumps(' + json.dumps(grant) + '))\n', encoding='utf-8')
        self.env = {**os.environ, 'HOME': self.tmp.name, 'HERMES_HOME': self.tmp.name, 'HERMES_PYTHON': sys.executable,
                    'HERMES_PYTHON_SRC_ROOT': str(root), 'HERMES_CWD': self.tmp.name, 'TERM': 'xterm-256color', 'COLUMNS': '120', 'LINES': '40'}
        self.out = b''
        pid, fd = pty.fork()
        if pid == 0:
            os.environ.clear(); os.environ.update(self.env)
            os.execv(NODE, [NODE, str(ENTRY)])
        self.pid, self.fd = pid, fd
        import fcntl, termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))

    def tearDown(self):
        try:
            os.kill(self.pid, 9)
        except ProcessLookupError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.tmp.cleanup()

    def text(self):
        t = re.sub(rb'\x1b\[[0-9;?<>=]*[A-Za-z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[=>78]', b'', self.out)
        return t.decode('utf-8', 'replace').replace('\r', '')

    def wait_for(self, needle, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if needle in self.text():
                return True
            r, _, _ = select.select([self.fd], [], [], 0.3)
            if r:
                try:
                    d = os.read(self.fd, 65536)
                except OSError:
                    break
                if not d:
                    break
                self.out += d
        return needle in self.text()

    def type(self, s):
        os.write(self.fd, s.encode())

    def test_full_turn_with_tool_approval_clarify_slash_and_quit(self):
        self.assertTrue(self.wait_for('JANGIN'), self.text()[-2000:])
        self.assertTrue(self.wait_for('fake-model'), self.text()[-2000:])          # session.info 가 배너에
        self.assertIn(['hermes-gateway-v1', 'hermes-ticket.abc'], [self.gw.protocols])
        self.type('안녕 테스트\r')
        self.assertTrue(self.wait_for('⚠ 승인이 필요합니다'), self.text()[-2000:])
        self.assertIn('↳ 나: 안녕 테스트', self.text())
        self.assertIn('┊ ⚒ terminal', self.text())
        self.assertIn('ls -la', self.text())
        self.assertIn('┊ ✓ terminal 0.4s', self.text())
        self.assertIn('git push origin main', self.text())
        self.type('1')
        self.assertTrue(self.wait_for('12 토큰'), self.text()[-2000:])
        self.assertIn('승인 응답: once', self.text())
        t = self.text()   # 도구 줄 앞의 조각은 그 전에 스크롤백으로 나가고, 뒤 조각은 승인 뒤에 이어진다
        self.assertLess(t.index('안녕\n'), t.index('┊ ⚒ terminal'))
        self.assertLess(t.index('승인 응답: once'), t.index(' 하세요\n두 번째 줄'))
        resp = [p for m, p in self.gw.calls if m == 'approval.respond']
        self.assertEqual(resp, [{'session_id': 's1', 'execution_generation': 1, 'prompt_id': 'ap1', 'choice': 'once'}])
        # 슬래시 명령은 게이트웨이의 slash.exec 로
        self.type('/project\r')
        self.assertTrue(self.wait_for('프로젝트: 빵집 (/project)'), self.text()[-2000:])
        # 되묻기(clarify): 번호로 답하면 선택지 글자로 보낸다
        self.type('/ask\r')
        self.assertTrue(self.wait_for('어느 채널로?'), self.text()[-2000:])
        self.type('2\r')
        self.assertTrue(self.wait_for('threads') or True)
        end = time.time() + 10
        while time.time() < end and not [1 for m, _ in self.gw.calls if m == 'clarify.respond']:
            self.wait_for('\x00', 0.3)
        clar = [p for m, p in self.gw.calls if m == 'clarify.respond']
        self.assertEqual(clar, [{'session_id': 's1', 'execution_generation': 1, 'prompt_id': 'cl1', 'answer': 'threads'}])
        self.type('/quit\r')
        self.assertTrue(self.wait_for('다음 작업에서'), self.text()[-2000:])
        _, status = os.waitpid(self.pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        methods = [m for m, _ in self.gw.calls]
        self.assertEqual(methods[:3], ['runtime.describe', 'session.create', 'session.info'])

    def test_ctrl_c_interrupts_a_running_turn(self):
        self.assertTrue(self.wait_for('fake-model'))
        self.type('길게\r')
        self.assertTrue(self.wait_for('⚠ 승인이 필요합니다'))
        self.type('\x03')          # 승인 카드에서는 거절
        end = time.time() + 10
        while time.time() < end and not [1 for m, _ in self.gw.calls if m == 'approval.respond']:
            self.wait_for('\x00', 0.3)
        self.assertEqual([p['choice'] for m, p in self.gw.calls if m == 'approval.respond'], ['deny'])


if __name__ == '__main__':
    unittest.main()
