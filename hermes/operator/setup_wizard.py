#!/usr/bin/env python3
"""operator setup — Operator(Hermes 배포판) 의 한국어 설정 마법사.

`operator setup` 이 이 파일을 실행한다. 표준 라이브러리만 쓰는 시스템 python3 로 돌고, Hermes 설정을
바꿀 때는 Hermes 자신의 함수(hermes_cli.config, agent.shell_hooks)를 Hermes 파이썬으로 불러 쓴다.

순서
  1. Hermes 기본 설정   원래 Hermes 마법사를 그대로 돌린다 (모델, 터미널, 메신저, 도구). 엔터 = 지금 값 유지
  2. operator 플러그인  켜져 있는지 확인하고 꺼져 있으면 켠다
  3. 프로젝트 폴더      /idea 로 만드는 프로젝트가 들어갈 폴더
  4. 승인 방식          새 프로젝트가 사람의 결정을 어디서 받을지 (데스크톱+메신저 / 메신저만)
  5. 메신저 승인        operator 명령을 칠 수 있는 사람을 본인으로 좁힌다
  6. 두 번째 잠금       플러그인이 꺼져도 막는 셸 훅

`operator setup --operator-only` 는 1단계를 건너뛰고, `operator setup --hermes` 는 원래 Hermes 마법사만 연다.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 이 플러그인의 명령 본체와 같은 위치 규칙: 설치된 플러그인 안의 skill/ 사본, 아니면 저장소의 원본
OP_PY_CANDIDATES = (os.path.join(HERE, "skill", "scripts", "op.py"),
                    os.path.join(HERE, "..", "..", "skills", "operator", "scripts", "op.py"))


def hermes_home(profile):
    base = os.environ.get("HERMES_HOME_ROOT") or os.path.join(os.path.expanduser("~"), ".hermes")
    if os.environ.get("HERMES_HOME") and profile in (None, "", "default"):
        return os.environ["HERMES_HOME"]
    return base if profile in (None, "", "default") else os.path.join(base, "profiles", profile)


def settings_path(home):
    """플러그인과 마법사가 같이 쓰는 설정 파일. commands.settings_file() 과 같은 규칙."""
    return os.path.join(home, "plugin-data", "operator", "settings.json")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------- Hermes 연결
class Hermes:
    """Hermes 설정을 읽고 바꾸는 창구. 값(토큰)은 이 프로세스로 가져오지 않고 있는지 여부만 돌려받는다."""

    def __init__(self, profile, home):
        self.profile, self.home = profile, home
        self.bin = shutil.which("hermes") or os.path.join(os.path.expanduser("~"), ".local", "bin", "hermes")
        self.agent_dir = os.environ.get("HERMES_AGENT_DIR") or os.path.join(os.path.expanduser("~"), ".hermes", "hermes-agent")
        self._py = None

    def python(self):
        """hermes_cli 를 가져올 수 있는 파이썬 (Hermes 가 설치한 가상 환경)."""
        if self._py is None:
            self._py = ""
            root = os.path.join(os.path.expanduser("~"), ".hermes")
            for py in sorted(glob.glob(os.path.join(root, "installs", "*", "environments", "*", "venv", "bin", "python3")), reverse=True) \
                    + glob.glob(os.path.join(self.agent_dir, "venv", "bin", "python3")) + glob.glob(os.path.join(self.agent_dir, ".venv", "bin", "python3")):
                r = subprocess.run([py, "-c", "import hermes_cli.config"], cwd=self.agent_dir, capture_output=True, text=True,
                                   env=self._env())
                if r.returncode == 0:
                    self._py = py
                    break
        return self._py

    def _env(self):
        env = dict(os.environ, HERMES_HOME=self.home)
        env["PYTHONPATH"] = self.agent_dir
        return env

    def call(self, code, *args):
        """Hermes 파이썬에서 code 를 실행하고 마지막 줄의 JSON 을 돌려준다."""
        py = self.python()
        if not py:
            raise RuntimeError("Hermes 파이썬을 찾지 못했다")
        r = subprocess.run([py, "-c", code, *args], cwd=self.agent_dir, capture_output=True, text=True, env=self._env())
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        if r.returncode != 0 or not lines:
            raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else f"exit {r.returncode}")
        return json.loads(lines[-1])

    def run_setup(self, section=None):
        """Hermes 마법사를 사용자의 터미널에 그대로 띄운다."""
        cmd = [self.bin, "-p", self.profile or "default", "setup"] + ([section] if section else [])
        return subprocess.call(cmd)

    def info(self):
        return self.call(r"""
import json
from hermes_cli.config import load_config, get_env_value
from hermes_cli import auth
c = load_config()
m = c.get("model") or {}
prov = auth.get_active_provider() if hasattr(auth, "get_active_provider") else None
hooks = ((c.get("hooks") or {}).get("pre_tool_call") or [])
def has(k):
    v = get_env_value(k)
    return bool(v and str(v).strip())
print(json.dumps({
  "model": m.get("default") if isinstance(m, dict) else m,
  "provider": prov or (m.get("provider") if isinstance(m, dict) else None),
  "plugins": list(((c.get("plugins") or {}).get("enabled")) or []),
  "hooks": [h.get("command") for h in hooks if isinstance(h, dict)],
  "telegram": has("TELEGRAM_BOT_TOKEN"),
  "telegram_users": (get_env_value("TELEGRAM_ALLOWED_USERS") or "").strip(),
  "allow_all": (get_env_value("GATEWAY_ALLOW_ALL_USERS") or "").strip().lower() in ("1", "true", "yes"),
  "operator_users": (get_env_value("OPERATOR_ALLOWED_USERS") or "").strip(),
  "messengers": sorted(k.split("_")[0].lower() for k in ("TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN") if has(k)),
}))
""")

    def enable_plugin(self):
        return subprocess.call([self.bin, "-p", self.profile or "default", "plugins", "enable", "operator"]) == 0

    def set_env(self, key, value):
        return self.call(r"""
import json, sys
from hermes_cli.config import save_env_value
save_env_value(sys.argv[1], sys.argv[2])
print(json.dumps({"ok": True}))
""", key, value)

    def add_guard_hook(self, command):
        """config.yaml 의 hooks.pre_tool_call 에 셸 훅을 넣고(이미 있으면 그대로), 이 명령을 허락 목록에 올린다."""
        return self.call(r"""
import json, sys
from hermes_cli.config import load_config, save_config
from agent import shell_hooks
cmd = sys.argv[1]
c = load_config()
hooks = c.setdefault("hooks", {}) or {}
c["hooks"] = hooks
lst = hooks.setdefault("pre_tool_call", []) or []
hooks["pre_tool_call"] = lst
if not any(isinstance(h, dict) and h.get("command") == cmd for h in lst):
    lst.append({"matcher": "terminal|write_file|patch|read_file|execute_code", "command": cmd, "timeout": 20, "fail_closed": True})
    save_config(c)
consented = shell_hooks.record_consent_from_config(load_config(), accept_hooks=True)
print(json.dumps({"ok": True, "consented": [s.command for s in consented]}))
""", command)


# ---------------------------------------------------------------- 마법사
class Wizard:
    def __init__(self, hermes, home, ask=input, say=print, run_hermes=True):
        self.h, self.home, self.ask, self.say = hermes, home, ask, say
        self.run_hermes = run_hermes
        self.s = load_json(settings_path(home), {})
        self.summary = []

    def save(self):
        save_json(settings_path(self.home), self.s)

    # 입력 도우미
    def yes(self, q, default=False):
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            a = self.ask(f"  {q} {hint} ").strip().lower()
            if not a:
                return default
            if a in ("y", "yes", "예", "네", "ㅇ"):
                return True
            if a in ("n", "no", "아니오", "아니요", "ㄴ"):
                return False
            self.say("  y 또는 n 으로 답해 주세요.")

    def choose(self, q, options, default=1):
        for i, o in enumerate(options, 1):
            self.say(f"    {i}. {o}")
        while True:
            a = self.ask(f"  {q} [기본 {default}] ").strip()
            if not a:
                return default
            if a.isdigit() and 1 <= int(a) <= len(options):
                return int(a)
            self.say(f"  1~{len(options)} 중 번호로 골라 주세요.")

    def step(self, n, title):
        self.say("")
        self.say(f"[{n}/6] {title}")

    # 단계
    def run(self):
        self.say("┌──────────────────────────────────────────────┐")
        self.say("│  Operator 설정                                │")
        self.say("│  아이디어 구상 → 개발 → 배포 관리를 돕는 비서 │")
        self.say("│  Ctrl+C 로 언제든 멈출 수 있습니다.           │")
        self.say("└──────────────────────────────────────────────┘")
        self.say(f"  설정 위치: {self.home}")
        try:
            info = self.h.info()
        except Exception as e:
            self.say(f"  Hermes 설정을 읽지 못했습니다 ({e}). 먼저 `hermes setup` 을 한 번 실행해 주세요.")
            return 1
        info = self.hermes_base(info)
        self.plugin(info)
        self.folder()
        strict = self.approval()
        info = self.messenger(info, strict)
        self.guard_hook(info)
        self.save()
        self.say("")
        self.say("완료했습니다.")
        for line in self.summary:
            self.say(f"  · {line}")
        self.say("")
        self.say("다음: Hermes 앱에서 새 대화를 열고  /idea 동네 빵집 예약 페이지  처럼 시작하세요.")
        self.say("      휴대폰에서는 연결한 메신저에서 같은 명령을 씁니다. 승인은 /ok <번호>, 대기 목록은 /inbox.")
        return 0

    def hermes_base(self, info):
        self.step(1, "Hermes 기본 설정 (모델·터미널·메신저·도구)")
        if not self.run_hermes:
            self.say(f"  건너뜁니다. 지금 모델: {info.get('model') or '기본값'} ({info.get('provider') or '로그인 없음'})")
        else:
            self.say("  먼저 원래 Hermes 설정 마법사를 그대로 진행합니다 (영어 화면).")
            self.say("  순서: 모델과 로그인 → 터미널 실행 방식 → 메신저 연결 → 도구.")
            self.say("  질문마다 엔터를 누르면 지금 값이 그대로 유지됩니다. 끝나면 operator 설정으로 돌아옵니다.")
            if info.get("provider"):
                self.say(f"  지금 모델: {info.get('model') or '기본값'} ({info['provider']})")
                go = self.yes("Hermes 기본 설정을 진행할까요? (n = 지금 값 그대로 두고 operator 설정으로)", True)
            else:
                self.say("  아직 모델 로그인이 없어서 반드시 진행합니다.")
                self.say("  처음이면 Quick Setup(Nous Portal 무료 로그인) 이나 이미 쓰는 ChatGPT·Claude 구독을 고르면 됩니다.")
                go = True
            if go:
                code = self.h.run_setup()
                if code not in (0, None):
                    self.say("  Hermes 설정이 중간에 끝났습니다. 거기까지 저장된 값으로 operator 설정을 이어 갑니다.")
                info = self.h.info()
        self.summary.append(f"모델: {info.get('model') or '기본값'} ({info.get('provider') or '로그인 없음'})")
        if info.get("messengers"):
            self.summary.append(f"메신저: {', '.join(info['messengers'])}")
        return info

    def plugin(self, info):
        self.step(2, "operator 플러그인")
        if "operator" in (info.get("plugins") or []):
            self.say("  켜져 있습니다.")
        else:
            self.say("  꺼져 있어서 켭니다.")
            if not self.h.enable_plugin():
                self.say("  켜지 못했습니다. 나중에 `operator plugins enable operator` 로 켜 주세요.")
        self.summary.append("operator 플러그인: 켜짐")

    def folder(self):
        self.step(3, "프로젝트 폴더")
        self.say("  /idea 로 만드는 프로젝트가 이 폴더 아래에 하나씩 생깁니다.")
        cur = self.s.get("folder") or os.path.join(os.path.expanduser("~"), "operator-projects")
        a = self.ask(f"  폴더 [엔터 = {cur}] ").strip()
        path = os.path.abspath(os.path.expanduser(a or cur))
        os.makedirs(path, exist_ok=True)
        self.s["folder"] = path
        self.save()
        self.summary.append(f"프로젝트 폴더: {path}")

    def approval(self):
        self.step(4, "승인 방식")
        self.say("  승인(/ok), 단계 넘기기(/advance) 같은 사람의 결정을 어디서 받을지 정합니다.")
        self.say("  데스크톱 앱에서 친 명령은 같은 컴퓨터의 다른 프로그램이 흉내 낼 수 있어서,")
        self.say("  실제 계정을 연결할 거라면 휴대폰 메신저에서만 받는 쪽이 더 안전합니다.")
        cur = self.s.get("human_via") or ["local", "messenger"]
        default = 2 if cur == ["messenger"] else 1
        n = self.choose("고르세요", ["데스크톱 앱과 메신저 둘 다 (편함, 기본)", "메신저만 (엄격, 메신저 연결 필요)"], default)
        self.s["human_via"] = ["messenger"] if n == 2 else ["local", "messenger"]
        self.save()
        self.summary.append("승인 방식: " + ("메신저만" if n == 2 else "데스크톱 앱과 메신저") + " (새로 만드는 프로젝트부터 적용)")
        return n == 2

    def messenger(self, info, strict):
        self.step(5, "메신저 승인")
        if not info.get("messengers"):
            self.say("  연결된 메신저가 없습니다. 연결하면 밖에서도 휴대폰으로 승인할 수 있습니다.")
            if strict:
                self.say("  승인 방식을 '메신저만' 으로 골라서, 메신저가 없으면 승인할 방법이 없습니다.")
                if self.yes("지금 Hermes 메신저 설정으로 연결할까요?", True):
                    self.h.run_setup("gateway")
                    info = self.h.info()
            else:
                self.say("  나중에 연결하려면: operator setup gateway  (텔레그램이 가장 쉽습니다)")
        if not info.get("messengers"):
            self.summary.append("메신저 승인: 없음" + (" (메신저만 승인으로 골라서 지금은 승인할 수 없음)" if strict else ""))
            return info
        if info.get("allow_all"):
            self.say("  ! 게이트웨이가 모든 사용자를 받도록 설정돼 있습니다 (GATEWAY_ALLOW_ALL_USERS). 누구나 /ok 를 칠 수 있습니다.")
        users = info.get("operator_users") or ""
        tg = info.get("telegram_users") or ""
        if tg:
            self.say(f"  텔레그램 허용 사용자: {tg}")
        if users:
            self.say(f"  operator 명령 허용 사용자: {users}")
        else:
            self.say("  operator 명령(/ok, /advance 등)을 칠 수 있는 사람을 본인 한 명으로 좁히는 것을 권합니다.")
            guess = tg.strip() if tg and "," not in tg else ""
            a = self.ask(f"  본인 메신저 사용자 ID [엔터 = {guess or '건너뛰기'}] ").strip() or guess
            if a:
                self.h.set_env("OPERATOR_ALLOWED_USERS", a)
                users = a
                self.say("  저장했습니다. Hermes 게이트웨이를 다시 시작하면 적용됩니다 (`operator gateway restart`).")
        self.summary.append("메신저 승인: " + (f"operator 허용 사용자 {users}" if users else "허용 사용자 미지정 (게이트웨이 허용 사용자 전원)"))
        return info

    def guard_hook(self, info):
        self.step(6, "두 번째 잠금 (셸 훅)")
        self.say("  기본 잠금은 operator 플러그인입니다. 셸 훅을 더하면 플러그인이 꺼지거나 깨져도")
        self.say("  배포·게시·삭제 같은 명령을 막습니다. op.py 를 못 찾으면 막는 쪽으로 동작합니다.")
        op_py = next((os.path.abspath(p) for p in OP_PY_CANDIDATES if os.path.isfile(p)), None)
        if not op_py:
            self.say("  op.py 를 찾지 못해 건너뜁니다. 설치 스크립트를 다시 실행해 주세요.")
            self.summary.append("두 번째 잠금: 건너뜀 (op.py 없음)")
            return
        cmd = f'python3 -I "{op_py}" guard --format hermes'
        if cmd in (info.get("hooks") or []):
            self.say("  이미 걸려 있습니다.")
            self.summary.append("두 번째 잠금: 켜짐")
            return
        if self.yes("셸 훅을 걸까요?", True):
            try:
                self.h.add_guard_hook(cmd)
                self.say("  걸었습니다. 실행 중인 Hermes 는 30초 안에 다시 읽습니다.")
                self.summary.append("두 번째 잠금: 켜짐")
            except Exception as e:
                self.say(f"  걸지 못했습니다 ({e}). {os.path.join(HERE, 'config.example.yaml')} 의 hooks 부분을 직접 넣어 주세요.")
                self.summary.append("두 번째 잠금: 실패")
        else:
            self.summary.append("두 번째 잠금: 끔")


def main(argv=None):
    p = argparse.ArgumentParser(prog="operator setup", description="Operator 설정 마법사")
    p.add_argument("--profile", default=os.environ.get("OPERATOR_HERMES_PROFILE", "default"))
    p.add_argument("--hermes", action="store_true", help="원래 Hermes 설정 마법사만 연다")
    p.add_argument("--operator-only", action="store_true", help="Hermes 기본 설정을 건너뛰고 operator 단계만")
    args, rest = p.parse_known_args(argv)
    home = hermes_home(args.profile)
    h = Hermes(args.profile, home)
    if args.hermes:
        return subprocess.call([h.bin, "-p", args.profile, "setup", *rest])
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("operator setup 은 질문에 답하는 대화형 마법사라 터미널에서 실행해야 합니다.")
        return 2
    try:
        return Wizard(h, home, run_hermes=not args.operator_only).run()
    except (KeyboardInterrupt, EOFError):
        print("\n설정을 멈췄습니다. 이미 답한 단계까지만 저장됐습니다.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
