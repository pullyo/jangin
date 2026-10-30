#!/usr/bin/env python3
"""operator setup — Operator(Hermes 배포판) 설정 마법사. Hermes 설정 마법사와 같은 모양으로 돈다.

`operator setup` 이 이 파일을 실행한다. 두 부분으로 나뉜다.

  바깥(시스템 python3): 인자를 읽고, hermes_cli 를 가져올 수 있는 Hermes 파이썬을 찾아 `--inside` 로 자신을 다시 실행한다.
  안쪽(Hermes 파이썬): Hermes 마법사의 화면 부품(hermes_cli.setup 의 print_header, prompt, prompt_choice,
                       prompt_yes_no, 왼쪽 화살표로 돌아가기)을 그대로 써서 operator 단계를 묻는다.

순서
  ☤ Hermes 기본 설정   원래 Hermes 마법사(모델·로그인, 터미널, 메신저, 도구)를 그대로 돌린다. 엔터 = 지금 값 유지
  ◆ operator 플러그인  켜져 있는지 확인하고 꺼져 있으면 켠다
  ◆ 프로젝트 폴더      /idea 로 만드는 프로젝트가 들어갈 폴더
  ◆ 승인 방식          새 프로젝트가 사람의 결정을 어디서 받을지 (데스크톱+메신저 / 메신저만)
  ◆ 메신저 승인        operator 명령을 칠 수 있는 사람을 본인으로 좁힌다
  ◆ 도구               컴퓨터 화면 조작, 브라우저 자동 조작, X 검색, 칸반을 켜고 끈다 (Hermes `tools` 명령으로)
  ◆ 두 번째 잠금       플러그인이 꺼져도 막는 셸 훅

`operator setup --operator-only` 는 Hermes 기본 설정을 건너뛰고, `operator setup --hermes` 는 원래 Hermes 마법사만 연다.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OP_PY_CANDIDATES = (os.path.join(HERE, "skill", "scripts", "op.py"),
                    os.path.join(HERE, "..", "..", "skills", "operator", "scripts", "op.py"))
APPROVAL_CHOICES = (["local", "messenger"], ["messenger"])
APPROVAL_LABELS = ("데스크톱 앱과 메신저 둘 다 (편함)", "메신저만 (엄격, 메신저 연결 필요)")

# (Hermes 도구 이름, 화면 이름, 권장, 설명). 권장은 설명에만 쓰고, 엔터는 지금 값을 유지한다.
TOOL_CHOICES = (
    ("computer_use", "컴퓨터 화면 조작", False,
     "이 맥의 앱 화면을 클릭하고 입력합니다. operator 가드를 거치지 않아 승인 없이 게시·배포 버튼을 누를 수 있습니다. 권장: 끄기."),
    ("browser", "브라우저 자동 조작", True,
     "만든 사이트를 열어 확인할 때 씁니다. 웹사이트의 게시 버튼도 누를 수 있고 operator 가드는 클릭을 검사하지 않습니다. 권장: 켜기, 대신 결과를 확인하세요."),
    ("x_search", "X 검색", True,
     "검증·배우기 단계에서 사람들이 실제로 남긴 글을 찾습니다. xAI 로그인이 필요할 수 있습니다. 권장: 켜기."),
    ("kanban", "칸반 (여러 작업 나눠 돌리기)", False,
     "만들기 단계에서 마일스톤 여러 개를 따로 돌릴 때 씁니다. 처음에는 꺼 둬도 됩니다."),
)


def hermes_home(profile):
    base = os.path.join(os.path.expanduser("~"), ".hermes")
    if profile in (None, "", "default"):
        return os.environ.get("HERMES_HOME") or base
    return os.path.join(base, "profiles", profile)


def settings_path(home):
    """플러그인(commands.Plugin)과 같이 쓰는 설정 파일."""
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


# 셸 훅은 게이트웨이가 셸 없이 실행한다. 데스크톱 앱이 띄운 게이트웨이는 PATH 가 최소라서 `python3` 가
# macOS 의 /usr/bin/python3 (Xcode 라이선스 동의 전에는 실행 안 됨) 로 잡힐 수 있고, fail_closed 훅이 실패하면
# 모든 도구 호출이 막힌다. 그래서 실제로 실행되는 파이썬의 절대 경로를 쓴다. 버전이 바뀌어도 남는 링크를 먼저 고른다.
PYTHON_CANDIDATES = ("/usr/local/bin/python3", "/opt/homebrew/bin/python3",
                     "/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/usr/bin/python3")


def stable_python():
    env_py = os.environ.get("OPERATOR_PYTHON")
    for py in ([env_py] if env_py else []) + list(PYTHON_CANDIDATES) + [sys.executable]:
        if py and os.path.isfile(py) and os.access(py, os.X_OK):
            try:
                if subprocess.run([py, "-I", "-c", "import json, re"], capture_output=True, timeout=20).returncode == 0:
                    return py
            except (OSError, subprocess.TimeoutExpired):
                continue
    return None


def guard_command():
    op_py = next((os.path.abspath(p) for p in OP_PY_CANDIDATES if os.path.isfile(p)), None)
    py = stable_python()
    return f'"{py}" -I "{op_py}" guard --format hermes' if op_py and py else None


def is_operator_guard(cmd):
    return isinstance(cmd, str) and "op.py" in cmd and "guard --format hermes" in cmd


# ---------------------------------------------------------------- 화면: Hermes 마법사 부품
class HermesUI:
    """hermes_cli.setup 의 화면 부품을 그대로 쓴다. 같은 색, 같은 메뉴, Esc 취소, 왼쪽 화살표로 이전 질문."""

    def __init__(self):
        from hermes_cli import setup as S
        from hermes_cli import cli_output as O
        self.S, self.O = S, O
        self.Cancelled = getattr(S, "_SetupCancelled", KeyboardInterrupt)

    def banner(self, *lines):
        self.S._print_banner(*lines)

    def header(self, title):
        self.S.print_header(title)

    def info(self, *lines):
        self.S._info(*lines)

    def success(self, text):
        self.O.print_success(text)

    def warn(self, text):
        self.O.print_warning(text)

    def ask(self, question, default=None):
        return self.S.prompt(question, default)

    def choose(self, question, options, default=0, description=None):
        return self.S.prompt_choice(question, list(options), default, description=description)

    def yes(self, question, default=True, description=None):
        return self.S.prompt_yes_no(question, default, description=description)

    def run_steps(self, steps):
        with self.S._setup_navigation_scope():
            self.S._run_setup_steps(steps)


# ---------------------------------------------------------------- Hermes 설정 읽기·쓰기 (안쪽에서, Hermes 함수로)
class HermesBackend:
    def __init__(self, profile, hermes_bin):
        self.profile, self.bin = profile or "default", hermes_bin

    def info(self):
        from hermes_cli.config import load_config, get_env_value
        from hermes_cli import auth
        c = load_config()
        m = c.get("model") or {}

        def has(k):
            v = get_env_value(k)
            return bool(v and str(v).strip())

        prov = auth.get_active_provider() if hasattr(auth, "get_active_provider") else None
        return {
            "model": m.get("default") if isinstance(m, dict) else m,
            "provider": prov or (m.get("provider") if isinstance(m, dict) else None),
            "plugins": list(((c.get("plugins") or {}).get("enabled")) or []),
            "hooks": [h.get("command") for h in ((c.get("hooks") or {}).get("pre_tool_call") or []) if isinstance(h, dict)],
            "telegram_users": (get_env_value("TELEGRAM_ALLOWED_USERS") or "").strip(),
            "allow_all": (get_env_value("GATEWAY_ALLOW_ALL_USERS") or "").strip().lower() in ("1", "true", "yes"),
            "operator_users": (get_env_value("OPERATOR_ALLOWED_USERS") or "").strip(),
            "messengers": sorted(k.split("_")[0].lower() for k in ("TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN") if has(k)),
        }

    def run_setup(self, section=None):
        return subprocess.call([self.bin, "-p", self.profile, "setup"] + ([section] if section else []))

    def enable_plugin(self):
        return subprocess.call([self.bin, "-p", self.profile, "plugins", "enable", "operator"]) == 0

    def set_env(self, key, value):
        from hermes_cli.config import save_env_value
        save_env_value(key, value)

    def tool_states(self, platform="cli"):
        """`hermes tools list` 의 ✓ enabled / ✗ disabled 줄을 읽는다. {이름: 켜짐}"""
        r = subprocess.run([self.bin, "-p", self.profile, "tools", "list", "--platform", platform], capture_output=True, text=True)
        out = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] in ("enabled", "disabled"):
                out[parts[2]] = parts[1] == "enabled"
        return out

    def set_tool(self, name, on, platform="cli"):
        return subprocess.call([self.bin, "-p", self.profile, "tools", "enable" if on else "disable", "--platform", platform, name],
                               stdout=subprocess.DEVNULL) == 0

    def add_guard_hook(self, cmd):
        from hermes_cli.config import load_config, save_config
        from agent import shell_hooks
        c = load_config()
        hooks = c.get("hooks") if isinstance(c.get("hooks"), dict) else {}
        lst = hooks.get("pre_tool_call") if isinstance(hooks.get("pre_tool_call"), list) else []
        # 예전 형식(맨 `python3`)의 operator 훅은 지우고 새 명령 하나만 남긴다
        stale = [h for h in lst if isinstance(h, dict) and is_operator_guard(h.get("command")) and h.get("command") != cmd]
        if stale:
            lst = [h for h in lst if h not in stale]
            hooks["pre_tool_call"], c["hooks"] = lst, hooks
            save_config(c)
            for h in stale:
                try:
                    shell_hooks.revoke(h["command"]) if hasattr(shell_hooks, "revoke") else None
                except Exception:
                    pass
        if not any(isinstance(h, dict) and h.get("command") == cmd for h in lst):
            lst.append({"matcher": "terminal|write_file|patch|read_file|execute_code", "command": cmd, "timeout": 20, "fail_closed": True})
            hooks["pre_tool_call"], c["hooks"] = lst, hooks
            save_config(c)
        shell_hooks.record_consent_from_config(load_config(), accept_hooks=True)


# ---------------------------------------------------------------- 마법사 본체 (화면·저장소와 무관한 순서와 규칙)
class OperatorSetup:
    def __init__(self, ui, backend, home, run_hermes=True):
        self.ui, self.h, self.home, self.run_hermes = ui, backend, home, run_hermes
        self.s = load_json(settings_path(home), {})
        self.info = {}
        self.summary = {}

    def save(self):
        save_json(settings_path(self.home), self.s)

    def run(self):
        self.info = self.h.info()
        if self.run_hermes:
            self.hermes_base()
        else:
            self.summary["모델"] = f"{self.info.get('model') or '기본값'} ({self.info.get('provider') or '로그인 없음'})"
        self.ui.banner("│             ☤ Operator Setup                            │",
                       "├─────────────────────────────────────────────────────────┤",
                       "│  idea → build → ship. Hermes settings stay as they are. │",
                       "│  Press Ctrl+C at any time to exit.                      │")
        self.ui.info(f"설정 파일:  {settings_path(self.home)}",
                     "질문마다 지금 값이 기본으로 보입니다. 엔터를 누르면 그대로 유지됩니다.",
                     "왼쪽 화살표로 이전 질문, Esc 로 취소합니다.")
        self.ui.run_steps([("operator 플러그인", self.plugin), ("프로젝트 폴더", self.folder), ("승인 방식", self.approval),
                           ("메신저 승인", self.messenger), ("도구", self.tools), ("두 번째 잠금", self.guard_hook)])
        self.save()
        self.ui.header("Operator 설정 완료")
        for k in ("모델", "operator 플러그인", "프로젝트 폴더", "승인 방식", "메신저 승인", "도구", "두 번째 잠금"):
            if k in self.summary:
                self.ui.success(f"{k}: {self.summary[k]}")
        self.ui.info(None, "다음: Hermes 앱에서 새 대화를 열고  /idea 동네 빵집 예약 페이지  처럼 시작하세요.",
                     "휴대폰에서는 연결한 메신저에서 같은 명령을 씁니다. 승인 /ok <번호>, 대기 목록 /inbox.")
        return 0

    def hermes_base(self):
        info = self.info
        if info.get("provider"):
            go = self.ui.yes("먼저 Hermes 기본 설정(모델·터미널·메신저·도구)을 진행할까요?", True,
                             description=f"지금 모델: {info.get('model') or '기본값'} ({info['provider']}). "
                                         "Hermes 마법사의 질문마다 엔터를 누르면 지금 값이 유지됩니다.")
        else:
            self.ui.info("아직 모델 로그인이 없어서 Hermes 기본 설정부터 진행합니다.")
            go = True
        if go:
            self.h.run_setup()
            self.info = self.h.info()
        self.summary["모델"] = f"{self.info.get('model') or '기본값'} ({self.info.get('provider') or '로그인 없음'})"

    def plugin(self):
        self.ui.header("operator 플러그인")
        if "operator" in (self.info.get("plugins") or []):
            self.ui.info("켜져 있습니다.")
        elif self.h.enable_plugin():
            self.ui.success("operator 플러그인을 켰습니다.")
        else:
            self.ui.warn("켜지 못했습니다. 나중에 `operator plugins enable operator` 로 켜 주세요.")
        self.summary["operator 플러그인"] = "켜짐"

    def folder(self):
        self.ui.header("프로젝트 폴더")
        self.ui.info("/idea 로 만드는 프로젝트가 이 폴더 아래에 하나씩 생깁니다.")
        cur = self.s.get("folder") or os.path.join(os.path.expanduser("~"), "operator-projects")
        path = os.path.abspath(os.path.expanduser(self.ui.ask("프로젝트 폴더", cur) or cur))
        os.makedirs(path, exist_ok=True)
        self.s["folder"] = path
        self.save()
        self.summary["프로젝트 폴더"] = path

    def approval(self):
        self.ui.header("승인 방식")
        cur = self.s.get("human_via") or APPROVAL_CHOICES[0]
        default = 1 if cur == APPROVAL_CHOICES[1] else 0
        self.ui.info("데스크톱 앱에서 친 명령은 같은 컴퓨터의 다른 프로그램이 흉내 낼 수 있습니다.",
                     "실제 계정을 연결한다면 휴대폰 메신저에서만 받는 쪽이 안전합니다.")
        n = self.ui.choose("사람의 결정(/ok, /advance)을 어디서 받을까요?", APPROVAL_LABELS, default,
                           description="데스크톱 앱에서 친 명령은 같은 컴퓨터의 다른 프로그램이 흉내 낼 수 있습니다. "
                                       "실제 계정을 연결한다면 휴대폰 메신저에서만 받는 쪽이 안전합니다.")
        self.s["human_via"] = list(APPROVAL_CHOICES[n])
        self.save()
        self.summary["승인 방식"] = ("메신저만" if n == 1 else "데스크톱 앱과 메신저") + " (새 프로젝트부터)"

    def messenger(self):
        self.ui.header("메신저 승인")
        strict = self.s.get("human_via") == APPROVAL_CHOICES[1]
        info = self.info
        if not info.get("messengers"):
            self.ui.info("연결된 메신저가 없습니다. 연결하면 밖에서도 휴대폰으로 승인할 수 있습니다.")
            if strict and self.ui.yes("Hermes 메신저 설정을 열까요?", True,
                                      description="승인 방식을 '메신저만' 으로 골라서, 메신저가 없으면 승인할 방법이 없습니다."):
                self.h.run_setup("gateway")
                info = self.info = self.h.info()
            elif not strict:
                self.ui.info("나중에 연결하려면: operator setup gateway  (텔레그램이 가장 쉽습니다)")
        if not info.get("messengers"):
            self.summary["메신저 승인"] = "메신저 없음" + (" — 메신저만 승인이라 지금은 승인할 수 없음" if strict else "")
            return
        if info.get("allow_all"):
            self.ui.warn("게이트웨이가 모든 사용자를 받습니다 (GATEWAY_ALLOW_ALL_USERS). 누구나 /ok 를 칠 수 있습니다.")
        if info.get("telegram_users"):
            self.ui.info(f"텔레그램 허용 사용자: {info['telegram_users']}")
        cur = info.get("operator_users") or ""
        guess = cur or (info.get("telegram_users") if "," not in (info.get("telegram_users") or "") else "")
        self.ui.info("operator 명령(/ok, /advance 등)을 칠 수 있는 사람을 본인 한 명으로 좁히는 것을 권합니다.")
        users = (self.ui.ask("operator 명령 허용 사용자 ID", guess or None) or "").strip()
        if users and users != cur:
            self.h.set_env("OPERATOR_ALLOWED_USERS", users)
            self.ui.success("저장했습니다. `operator gateway restart` 후 적용됩니다.")
        self.summary["메신저 승인"] = f"{', '.join(info['messengers'])}, 허용 사용자 {users or '지정 안 함'}"

    def tools(self):
        self.ui.header("도구")
        states = self.h.tool_states("cli")
        if not states:
            self.ui.warn("Hermes 도구 목록을 읽지 못해 건너뜁니다. 나중에 `operator tools` 로 바꿀 수 있습니다.")
            self.summary["도구"] = "건너뜀"
            return
        if states.get("web") is False:
            if self.ui.yes("웹 검색이 꺼져 있습니다. 켤까요?", True, description="발견·검증 단계의 조사에 꼭 필요합니다."):
                self.h.set_tool("web", True)
        self.ui.info("Hermes 터미널·데스크톱 앱(cli)에 적용합니다. 질문마다 엔터를 누르면 지금 값이 유지됩니다.")
        on_list = []
        for name, label, recommended, why in TOOL_CHOICES:
            if name not in states:
                continue
            cur = states[name]
            self.ui.info(None, f"{label}: {why}")   # 전체 화면 메뉴가 아닐 때도 설명이 보이게
            want = self.ui.yes(f"{label} — 지금 {'켜짐' if cur else '꺼짐'}. 켤까요?", cur, description=why)
            if want != cur:
                if self.h.set_tool(name, want):
                    self.ui.success(f"{label}: {'켰습니다' if want else '껐습니다'}")
                else:
                    self.ui.warn(f"{label}: 바꾸지 못했습니다. `operator tools {'enable' if want else 'disable'} {name}`")
                    want = cur
            if want:
                on_list.append(label)
        if "브라우저 자동 조작" in on_list or "컴퓨터 화면 조작" in on_list:
            self.ui.info("참고: 브라우저와 컴퓨터 조작은 operator 승인 큐를 거치지 않습니다. 결과를 꼭 확인하세요.")
        self.summary["도구"] = "켜짐 " + (", ".join(on_list) if on_list else "없음 (선택 도구 기준)")

    def guard_hook(self):
        self.ui.header("두 번째 잠금 (셸 훅)")
        cmd = guard_command()
        if not cmd:
            self.ui.warn("op.py 를 찾지 못해 건너뜁니다. 설치 스크립트를 다시 실행해 주세요.")
            self.summary["두 번째 잠금"] = "건너뜀"
            return
        if cmd in (self.info.get("hooks") or []):
            self.ui.info("이미 걸려 있습니다.")
            self.summary["두 번째 잠금"] = "켜짐"
            return
        self.ui.info("기본 잠금은 operator 플러그인입니다. 셸 훅은 플러그인이 꺼지거나 깨졌을 때를 위한 두 번째 잠금입니다.")
        if self.ui.yes("셸 훅을 걸까요?", True,
                       description="기본 잠금은 operator 플러그인입니다. 셸 훅을 더하면 플러그인이 꺼지거나 깨져도 "
                                   "배포·게시·삭제 명령을 막습니다. op.py 를 못 찾으면 막는 쪽으로 동작합니다."):
            try:
                self.h.add_guard_hook(cmd)
                self.ui.success("셸 훅을 걸었습니다. 실행 중인 Hermes 는 30초 안에 다시 읽습니다.")
                self.summary["두 번째 잠금"] = "켜짐"
            except Exception as e:
                self.ui.warn(f"걸지 못했습니다 ({e.__class__.__name__}). {os.path.join(HERE, 'config.example.yaml')} 의 hooks 부분을 직접 넣어 주세요.")
                self.summary["두 번째 잠금"] = "실패"
        else:
            self.summary["두 번째 잠금"] = "끔"


# ---------------------------------------------------------------- 실행
def find_hermes_python(agent_dir):
    root = os.path.join(os.path.expanduser("~"), ".hermes")
    cands = sorted(glob.glob(os.path.join(root, "installs", "*", "environments", "*", "venv", "bin", "python3")), reverse=True)
    cands += glob.glob(os.path.join(agent_dir, "venv", "bin", "python3")) + glob.glob(os.path.join(agent_dir, ".venv", "bin", "python3"))
    env = dict(os.environ, PYTHONPATH=agent_dir)
    for py in cands:
        if subprocess.run([py, "-c", "import hermes_cli.setup"], cwd=agent_dir, env=env, capture_output=True).returncode == 0:
            return py
    return None


def inside(args):
    """Hermes 파이썬 안에서 돈다."""
    ui = HermesUI()
    backend = HermesBackend(args.profile, os.environ.get("OPERATOR_HERMES_BIN") or shutil.which("hermes") or "hermes")
    try:
        return OperatorSetup(ui, backend, hermes_home(args.profile), run_hermes=not args.operator_only).run()
    except ui.Cancelled:
        ui.info(None, "설정을 취소했습니다. 이미 답한 단계까지만 저장됐습니다.")
        return 130
    except (KeyboardInterrupt, EOFError):
        print("\n설정을 멈췄습니다. 이미 답한 단계까지만 저장됐습니다.")
        return 130


def main(argv=None):
    p = argparse.ArgumentParser(prog="operator setup", description="Operator 설정 마법사")
    p.add_argument("--profile", default=os.environ.get("OPERATOR_HERMES_PROFILE", "default"))
    p.add_argument("--hermes", action="store_true", help="원래 Hermes 설정 마법사만 연다")
    p.add_argument("--operator-only", action="store_true", help="Hermes 기본 설정을 건너뛰고 operator 단계만")
    p.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args, rest = p.parse_known_args(argv)
    if args.inside:
        return inside(args)
    hermes_bin = shutil.which("hermes") or os.path.join(os.path.expanduser("~"), ".local", "bin", "hermes")
    if args.hermes:
        return subprocess.call([hermes_bin, "-p", args.profile, "setup", *rest])
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("operator setup 은 질문에 답하는 대화형 마법사라 터미널에서 실행해야 합니다.")
        return 2
    agent_dir = os.environ.get("HERMES_AGENT_DIR") or os.path.join(os.path.expanduser("~"), ".hermes", "hermes-agent")
    py = find_hermes_python(agent_dir)
    if not py:
        print("Hermes 파이썬을 찾지 못했습니다. Hermes Agent 를 먼저 설치하거나 `hermes update` 를 실행해 주세요.")
        return 1
    env = dict(os.environ, PYTHONPATH=agent_dir, HERMES_HOME=hermes_home(args.profile), OPERATOR_HERMES_BIN=hermes_bin)
    cmd = [py, os.path.abspath(__file__), "--inside", "--profile", args.profile] + (["--operator-only"] if args.operator_only else [])
    os.chdir(agent_dir)
    os.execve(py, cmd, env)


if __name__ == "__main__":
    sys.exit(main())
