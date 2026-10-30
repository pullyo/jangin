"""Run op.py the way a person does: inside a terminal (a pseudo-terminal), not a pipe.

Since 0.6 there is no environment variable that turns an agent's pipe into a "human". The terminal check is all the CLI has,
so the tests that play the human open a real pty for stdin and stdout. This is also exactly how `script -q /dev/null`
fakes a terminal, which is why the terminal route is documented as accident protection, not proof (see op.py Authority).
"""
import os
import pty
import subprocess
import threading
import time
import tty


class TtyProcess:
    """Popen with stdin/stdout on a pty. stdout is collected in the background; stderr stays a pipe."""

    def __init__(self, argv, cwd, env):
        master, slave = pty.openpty()
        tty.setraw(slave)   # keep "\n" as is (no "\r\n") and no echo
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                                     start_new_session=True)
        os.close(slave)
        self._master, self._buf, self._done = master, b'', threading.Event()
        self._lock = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            try:
                data = os.read(self._master, 65536)
            except OSError:
                data = b''
            with self._lock:
                if not data:
                    self._done.set()
                    self._lock.notify_all()
                    return
                self._buf += data
                self._lock.notify_all()

    def readline(self, timeout=20):
        deadline = time.time() + timeout
        with self._lock:
            while b'\n' not in self._buf and not self._done.is_set() and time.time() < deadline:
                self._lock.wait(0.1)
            line, sep, rest = self._buf.partition(b'\n')
            self._buf = rest
            return (line + sep).decode('utf-8', 'replace')

    def communicate(self, timeout=60):
        err = self.proc.stderr.read()
        self.proc.wait(timeout)
        self._done.wait(5)
        with self._lock:
            out, self._buf = self._buf, b''
        return out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')

    @property
    def returncode(self):
        return self.proc.returncode

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()

    def wait(self, timeout=None):
        return self.proc.wait(timeout)

    def close(self):
        self.kill()
        self.proc.wait()
        self.proc.stderr.close()
        try:
            os.close(self._master)
        except OSError:
            pass


def run_tty(argv, cwd, env, timeout=120):
    p = TtyProcess(argv, cwd, env)
    try:
        out, err = p.communicate(timeout)
    finally:
        p.close()
    return subprocess.CompletedProcess(argv, p.returncode, out, err)
