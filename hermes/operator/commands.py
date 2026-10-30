"""operator 슬래시 명령의 본체. Hermes 와 상관없는 순수 파이썬이라 Hermes 없이 시험할 수 있다.

__init__.py 가 Hermes 에 명령을 등록하고, 사용자가 친 명령을 받으면 여기의 run() 을 부른다.
사람의 결정(/ok /reject /advance /back)은 여기서만 Authority 로 만들어진다:
  - 메신저(텔레그램 등)에서 온 명령: Hermes 가 SessionSource(사용자 ID)를 넘긴다 → messenger
  - Desktop·TUI·CLI 화면에서 온 명령: source 가 없다 → local (같은 사용자 프로세스가 로컬 소켓으로 흉내 낼 수 있다)
Hermes 0.22 에서 모델의 출력, cron 작업, 플러그인 주입 메시지는 슬래시 명령으로 다시 해석되지 않는다 (docs/hermes-design.md 7절).
이름은 Hermes 내장 명령(/approve /status /queue …)과 겹치지 않게 골랐다. 겹치면 Hermes 가 등록을 건너뛴다.
"""
import importlib.util
import os
import re
import shlex
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = ("idea", "project", "stage", "advance", "back", "inbox", "ok", "reject", "setup")
# /operator <하위 명령> 으로도 부를 수 있다. 다른 플러그인과 이름이 겹칠 때를 위한 길이다.
ALIASES = {"status": "project", "queue": "inbox", "approve": "ok", "help": "help"}
HELP = {
    "idea": "/idea <한 줄 아이디어> — 새 프로젝트를 만들고 발견 단계를 시작합니다",
    "project": "/project — 지금 프로젝트 상태",
    "stage": "/stage — 지금 단계, 할 일, 넘어가기 조건",
    "advance": "/advance — 검사를 통과했으면 다음 단계로 (사람만)",
    "back": "/back <단계> <이유> — 이전 단계로 되돌리기 (사람만)",
    "inbox": "/inbox [번호] — 승인 대기 목록, 번호를 주면 본문까지",
    "ok": "/ok <번호> — 승인. 발송 방식이 human 이면 바로 보냅니다 (사람만)",
    "reject": "/reject <번호> <이유> — 거절. 이유는 다음 초안에 반영됩니다 (사람만)",
    "setup": "/setup — 설정 보기 · /setup folder <경로> · /setup use <프로젝트> · /setup unlock",
}


def _load_op():
    """op.py 를 찾는다: 설치 스크립트가 플러그인 안에 둔 스킬 사본(skill/), 아니면 저장소 안의 원본."""
    for p in (os.environ.get("OPERATOR_OP_PY"), os.path.join(HERE, "skill", "scripts", "op.py"),
              os.path.join(HERE, "..", "..", "skills", "operator", "scripts", "op.py")):
        if p and os.path.isfile(p):
            spec = importlib.util.spec_from_file_location("operator_op", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError("op.py 를 찾지 못했다. 설치 스크립트(install.sh)를 다시 실행해 주세요.")


op = _load_op()


class Plugin:
    """명령 처리 상태. data_dir 에 settings.json (프로젝트 폴더, 지금 프로젝트) 을 둔다."""

    def __init__(self, data_dir, allowed_users=None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.allowed_users = set(allowed_users or [])
        self._secrets = None          # 사람이 /setup unlock 하거나 첫 승인 때 한 번 읽어 메모리에만 둔다
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 설정
    @property
    def settings_path(self):
        return os.path.join(self.data_dir, "settings.json")

    def settings(self):
        s = op.load_json(self.settings_path, {})
        s.setdefault("folder", os.path.join(os.path.expanduser("~"), "operator-projects"))
        s.setdefault("projects", {})
        return s

    def save(self, s):
        op.save_json(self.settings_path, s)

    def current(self):
        s = self.settings()
        root = s["projects"].get(s.get("current") or "")
        if not root or not os.path.isdir(os.path.join(root, op.OP_DIR_NAME)):
            raise op.OpError("지금 프로젝트가 없습니다. `/idea <한 줄 아이디어>` 로 시작하거나 `/setup use <폴더>` 로 고르세요.")
        return os.path.join(root, op.OP_DIR_NAME)

    # ------------------------------------------------------------ 진입점
    def run(self, name, raw_args, platform="", user_id="", from_messenger=False):
        """명령 하나를 처리하고 사용자에게 보여 줄 한국어 문자열을 돌려준다. 예외는 메시지로 바꾼다.
        from_messenger: Hermes 가 메신저 사용자(SessionSource)를 넘겼을 때만 True."""
        if name == "operator":
            sub, _, raw_args = (raw_args or "").strip().partition(" ")
            name = ALIASES.get(sub, sub)
            if name in ("", "help"):
                return "operator 명령\n" + "\n".join(HELP[n] for n in NAMES)
        if name not in NAMES:
            return f"모르는 명령: /{name}  (/operator help)"
        if from_messenger and self.allowed_users and str(user_id) not in self.allowed_users:
            return "이 계정은 operator 명령 권한이 없습니다."
        kind = "messenger" if from_messenger and user_id else "local"
        auth = op.Authority(kind, ":".join(x for x in ("hermes", platform, str(user_id)) if x))
        try:
            with self._lock:
                return getattr(self, "cmd_" + name)((raw_args or "").strip(), auth)
        except op.StageBlocked as e:
            return e.msg + "\n" + _checks(e.checks)
        except op.OpError as e:
            return e.msg

    # ------------------------------------------------------------ 명령
    def cmd_idea(self, args, auth):
        if not args:
            return HELP["idea"]
        s = self.settings()
        name = op.slugify(args, 40)
        root = os.path.join(os.path.expanduser(s["folder"]), name)
        n = 2
        while os.path.exists(os.path.join(root, op.OP_DIR_NAME)):
            root = os.path.join(os.path.expanduser(s["folder"]), f"{name}-{n}")
            n += 1
        os.makedirs(root, exist_ok=True)
        od, _ = op.init_project(root, stage="discover", send_mode="human", human_via_kinds=["local", "messenger"])
        doc = op.stage_doc(od, "discover")
        with open(doc, "w", encoding="utf-8") as f:
            f.write(op.STAGE_TEMPLATES["discover"].replace("# 발견\n", f"# 발견\n\n아이디어 (사용자가 처음 한 말): {' '.join(args.split())}\n", 1))
        key = os.path.basename(root)
        s["projects"][key], s["current"] = root, key
        self.save(s)
        op.register_project(root)
        return (f"새 프로젝트 '{key}' 를 만들었습니다: {root}\n"
                "단계: 발견 — 무엇을, 누구에게, 왜 팔지 정합니다.\n"
                "이제 대화로 이어 가세요. 예: \"이 아이디어로 발견 단계를 시작하자. 한 번에 하나씩 물어봐 줘.\"")

    def cmd_project(self, args, auth):
        st = op.status_summary(self.current())
        cur = st["stage"]
        lines = [f"프로젝트: {st['root']}",
                 "단계: " + (f"{op.STAGE_KO[cur]} — {op.STAGES[cur]['goal']}" if cur else "사용 안 함 (운영과 같음)"),
                 f"발송 방식: {'승인하면 바로 보냄' if st['send_mode'] == 'human' else '승인 뒤 에이전트가 보냄'}",
                 "승인 대기 {pending} · 승인됨 {approved} · 보냄 {sent} · 거절 {rejected}".format(**st["counts"])]
        if st["pass"]:
            lines.append(f"진행 중인 작업(pass): {st['pass']['pass_id']} — 다음 {op.next_step(st['pass']) or '마무리'}")
        return "\n".join(lines)

    def cmd_stage(self, args, auth):
        ov = op.stage_overview(self.current())
        if not ov["stage"]:
            return "이 프로젝트는 단계 모델을 쓰지 않습니다."
        cur = ov["stage"]
        flow = " → ".join(f"[{op.STAGE_KO[n]}]" if n == cur else op.STAGE_KO[n] for n in op.STAGE_ORDER)
        out = [f"단계: {op.STAGE_KO[cur]} — {ov['goal']}", flow]
        if ov["back_reason"]:
            out.append(f"되돌아온 이유: {ov['back_reason']}")
        out.append("넘어가기 조건: " + ("모두 통과 → `/advance`" if ov["ready"] else "아직"))
        out.append(_checks(ov["checks"]))
        return "\n".join(out)

    def cmd_advance(self, args, auth):
        od = self.current()
        res = op.stage_move(od, "advance", auth)
        msg = f"단계: {op.STAGE_KO[res['from']]} → {op.STAGE_KO[res['to']]}. {op.STAGES[res['to']]['goal']}."
        if res["from"] == "build":
            msg += "\n통과한 마일스톤 검사:\n" + "\n".join(f"  {m['n']}. {m['title']} ← {m.get('test')}" for m in op.load_milestones(od))
        return msg

    def cmd_back(self, args, auth):
        parts = args.split(None, 1)
        if len(parts) < 2:
            return HELP["back"]
        to = _stage_name(parts[0])
        res = op.stage_move(self.current(), "back", auth, to=to, reason=parts[1])
        return f"단계: {op.STAGE_KO.get(res['from'], '없음')} → {op.STAGE_KO[res['to']]}. 이유를 에이전트가 다음 문서에 반영합니다."

    def cmd_inbox(self, args, auth):
        od = self.current()
        if re.fullmatch(r"\d{4}", args):
            it = next((x for x in op.queue_items(od, op.QUEUE_STATUSES) if x["id"] == args), None)
            if not it:
                return f"{args} 번 항목이 없습니다."
            return _card(it, full=True)
        items = op.queue_items(od, ("pending", "approved"))
        if not items:
            return "승인 대기가 비어 있습니다."
        return f"승인 대기·승인됨 {len(items)}건\n\n" + "\n\n".join(_card(it) for it in items)

    def cmd_ok(self, args, auth):
        if not re.fullmatch(r"\d{4}", args):
            return HELP["ok"]
        od = self.current()
        secrets_env = self.secrets() if op.send_mode_of(od) == "human" else None
        res = op.pending_decide(od, args, "approve", auth, secrets_env=secrets_env)
        msg = f"{args} 승인했습니다."
        if res["sent"] is not None:
            code, out = res["sent"]
            msg += f"\n발송 {'완료' if code == 0 else '실패'}: {out}"
        elif not (res["meta"].get("action") or "").strip():
            if op.ticket_channel(res["meta"]) or res["meta"].get("type") == "site":
                msg += "\n실행할 명령(action)이 없어 보내지 않았습니다. 에이전트에게 명령을 붙여 새로 올려 달라고 하세요."
            else:
                msg += " 밖으로 보낼 것이 없는 항목이라 승인만 기록했습니다."
        elif op.send_mode_of(od) == "agent":
            msg += f"\n발송 방식이 agent 라서 에이전트가 `op send {args}` 로 실행합니다."
        return msg

    def cmd_reject(self, args, auth):
        parts = args.split(None, 1)
        if not parts or not re.fullmatch(r"\d{4}", parts[0]):
            return HELP["reject"]
        op.pending_decide(self.current(), parts[0], "reject", auth, note=parts[1] if len(parts) > 1 else None)
        return f"{parts[0]} 거절했습니다. 이유는 다음 초안에 반영됩니다."

    def cmd_setup(self, args, auth):
        s = self.settings()
        parts = shlex.split(args) if args else []
        if parts[:1] == ["folder"] and len(parts) == 2:
            s["folder"] = os.path.abspath(os.path.expanduser(parts[1]))
            self.save(s)
            return f"새 프로젝트는 {s['folder']} 아래에 만듭니다."
        if parts[:1] == ["use"] and len(parts) == 2:
            target = parts[1]
            root = s["projects"].get(target) or os.path.abspath(os.path.expanduser(target))
            if not os.path.isdir(os.path.join(root, op.OP_DIR_NAME)):
                return f"{root} 에는 operator 프로젝트(.operator/)가 없습니다."
            key = os.path.basename(root)
            s["projects"][key], s["current"] = root, key
            self.save(s)
            op.register_project(root)
            via = op.human_via(os.path.join(root, op.OP_DIR_NAME))
            note = "" if "terminal" not in via else ("\n참고: 이 프로젝트는 터미널 승인도 받습니다 (human_via: " + ", ".join(via) +
                                                     "). Hermes 로만 받으려면 .operator/guard.json 에 "
                                                     "\"human_via\": [\"local\", \"messenger\"] 를 직접 넣으세요.")
            return f"지금 프로젝트: {key} ({root}){note}"
        if parts[:1] == ["unlock"]:
            env = self.secrets(reload=True)
            ready = [ch for ch, spec in op.CHANNELS.items() if all(env.get(k) for k in spec["env"])]
            return "발송 토큰을 읽어 메모리에 두었습니다. 준비된 채널: " + (", ".join(ready) or "없음")
        lines = [f"새 프로젝트 폴더: {s['folder']}", f"지금 프로젝트: {s.get('current') or '없음'}"]
        lines += [f"  · {k}: {v}" for k, v in sorted(s["projects"].items())]
        lines += ["", "바꾸기: /setup folder <경로> · /setup use <프로젝트 이름|폴더>",
                  "발송 토큰: 터미널에서 `op secret set <이름>` 으로 등록한 뒤 이 맥에서 `/setup unlock` (키체인 허락 창이 뜹니다).",
                  "토큰 값은 대화창에 붙여 넣지 마세요."]
        return "\n".join(lines)

    # ------------------------------------------------------------ 도구 호출 가드 (플러그인 훅)
    def guard(self, tool_name, args, session_cwd):
        """Hermes pre_tool_call 플러그인 훅. 막아야 하면 이유 문자열, 아니면 None.
        셸 훅과 달리 세션 폴더(session_cwd)를 안다."""
        if tool_name not in ("terminal", "write_file", "patch", "read_file", "execute_code"):
            return None
        args = args if isinstance(args, dict) else {}
        workdir = args.get("workdir")
        base = workdir if isinstance(workdir, str) and os.path.isabs(workdir) else (session_cwd or os.getcwd())
        cmd, paths = op.extract_from_hook_input({"tool_name": tool_name, "tool_input": args})
        sdir = os.path.realpath(op.secret_dir())
        for p in paths:
            rp = os.path.realpath(p if os.path.isabs(p) else os.path.join(base, p))
            if rp == sdir or rp.startswith(sdir + os.sep):
                return "[operator 승인 게이트] 비밀값과 operator 설정 폴더는 사람이 띄운 프로세스만 읽고 쓴다."
        roots = op.operator_roots(base, cmd, paths)
        if not (isinstance(workdir, str) and os.path.isabs(workdir)) and not session_cwd:
            # 세션 폴더를 모르면 셸 훅처럼 등록된 프로젝트 전부의 규칙으로 판단한다 (모르면 막는 쪽)
            roots += [os.path.join(r, op.OP_DIR_NAME) for r in op.known_projects() if os.path.join(r, op.OP_DIR_NAME) not in roots]
        for od in roots:
            deny, reason = op.guard_decide(cmd, paths, od, base)
            if deny:
                return "[operator 승인 게이트] " + reason
        return None

    # ------------------------------------------------------------ 토큰
    def secrets(self, reload=False):
        if self._secrets is None or reload:
            self._secrets = op.channel_env()
        return self._secrets


def _stage_name(word):
    w = word.strip().lower()
    for en, ko in op.STAGE_KO.items():
        if w in (en, ko):
            return en
    raise op.OpError(f"모르는 단계: {word} (발견, 검증, 만들기, 운영, 배우기)")


def _checks(checks):
    return "\n".join(f"  {'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in checks)


def _card(it, full=False):
    m = it["meta"]
    head = f"{it['id']} · {m.get('type', '')}" + (f"/{m['channel']}" if m.get("channel") else "") + \
           (f" → {m['to']}" if m.get("to") else "") + f" [{it['status']}]\n{m.get('title', '')}"
    body = it["body"].strip()
    body = body if full else (body[:300] + ("…" if len(body) > 300 else ""))
    act = (m.get("action") or "").strip()
    tail = f"실행될 명령: {act or '없음'}"
    if it["status"] == "pending":
        tail += f"\n승인: /ok {it['id']} · 거절: /reject {it['id']} <이유>"
    return f"{head}\n\n{body}\n\n{tail}"

