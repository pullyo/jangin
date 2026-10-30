#!/usr/bin/env python3
"""op — operator 스킬의 단일 진입점 CLI.

"AI 직원" 서비스가 인프라로 강제하는 장치(단계, 승인, 재개, 검증, 라우팅)를
셸 + JSON 파일 수준으로 옮긴 것이다. 어떤 에이전트(Claude Code, Codex,
Cursor, Gemini CLI, ...)에서든 같은 명령으로 동작한다. 표준 라이브러리만 쓴다.

  0. 단계 모델             → op stage (발견 → 검증 → 만들기 → 운영 → 배우기), op milestone, op metric
  1. 재개 가능한 pass 루프   → op pass start/next/done/fail/end  (.operator/state.json)
  2. 승인 게이트             → op pending add/list/approve/reject, op send, op guard
  3. 검증 게이트             → op verify (pending add 전에 자동 실행)
  4. 모델 라우팅             → op llm --role ... (로컬 모델이 있으면 거기로)

사용법: op.py <command> [args]   (op.py help 로 전체 목록)
"""
import html
import json
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import warnings
from datetime import datetime, timezone

OP_DIR_NAME = ".operator"

DEFAULT_CONFIG = {
    "project": "",
    "language": "ko",
    "pass": {"max_steps": 6, "steps": ["research", "draft", "queue", "report"]},
    "verify": {
        "placeholders": [r"\[TODO[^\]]*\]", r"\bTODO\b", r"\bTBD\b", r"\{\{", r"lorem ipsum", r"\bXXX\b", r"<여기에", r"\[\[.*?\]\]", r"\[링크\]", r"\[이름\]"],
        "banned_words": [],
        "required_words": [],
        "post": {
            "min_len": 20,
            "max_len": {"x": 280, "threads": 500, "instagram": 2200, "linkedin": 3000, "default": 3000},
        },
        "email": {"require": ["to", "subject"], "min_len": 40, "max_len": 4000},
        "research": {"min_sources": 3, "min_len": 200},
        "site": {"command": None, "timeout": 600},
        "build": {"test": None, "timeout": 900},
    },
    "routing": {
        "local_endpoint": "http://localhost:11434/v1",
        "local_model": "qwen2.5:7b",
        "local_roles": ["classify", "summarize", "tag", "extract"],
        "timeout": 120,
    },
}

# 가드가 막는 명령. 밖으로 나가거나(발송·게시·배포), 돈이 들거나(결제), 되돌릴 수 없는(삭제) 것.
DEFAULT_GUARD = {
    "deny_commands": [
        # 발송
        r"\b(sendmail|mailx?|mutt|swaks)\b",
        r"\bgh\s+(pr|issue)\s+(create|merge|comment)\b",
        r"\bagentmail\b.*\bsend\b",
        # 게시 (소셜 API 직접 호출)
        r"curl\b.*\b(api\.twitter\.com|api\.x\.com|graph\.facebook\.com|graph\.threads\.net|api\.linkedin\.com|api\.instagram\.com)",
        r"curl\b.*-X\s*(POST|PUT|DELETE|PATCH)\b.*\bhttps?://(?!localhost|127\.0\.0\.1)",
        # 배포
        r"\b(vercel|netlify|wrangler|fly|flyctl|railway|render)\s+(deploy|publish|up)\b",
        r"\bvercel\s+--prod\b",
        r"\bsupabase\s+(db\s+push|functions\s+deploy|secrets\s+set)\b",
        r'''\bgit\s+(?:(?:-C|-c|--git-dir|--work-tree)(?:=|\s+)(?:"[^"]*"|'[^']*'|\S+)\s+)*push\b''',
        r"\bnpm\s+publish\b",
        # 결제·도메인
        r"\bstripe\b.*\b(charges|payment_intents|payouts|transfers|subscriptions)\b.*\b(create|confirm|capture)\b",
        r"\b(namecheap|godaddy|porkbun|cloudflare)\b.*\b(register|purchase|buy)\b",
        # 삭제·파괴
        r"\brm\s+(?:-[a-zA-Z]*r[a-zA-Z]*|--recursive)\b(?![^;&|]*\.operator/tmp)",
        r'''\bgit\s+(?:(?:-C|-c|--git-dir|--work-tree)(?:=|\s+)(?:"[^"]*"|'[^']*'|\S+)\s+)*(push\s+.*--force|branch\s+-D|reset\s+--hard)\b''',
        r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b",
        r"\bsupabase\s+projects\s+delete\b",
    ],
    # 사람만 실행하는 명령. 에이전트 세션의 훅이 막는다. 사람은 훅이 없는 자기 터미널에서 실행.
    "human_only_commands": [
        r"\bop(\.py)?\s+pending\s+(approve|reject)\b",
        r"\bop(\.py)?\s+(approve|reject)\b",
        r"\bop(\.py)?\s+(serve|deliver|telegram|connect)\b",
        r"\bop(\.py)?\s+stage\s+(advance|back|set)\b",
        r"\bop(\.py)?\s+secret\s+(set|rm)\b",
        # 파이썬으로 op 모듈의 사람 경로를 직접 부르는 것 (플러그인만 쓴다). 스크립트 파일 안은 못 본다: Authority 주석 참고.
        r"\b(?:Authority|pending_decide|stage_move|secret_store|secret_remove|set_status)\s*\(",
    ],
    # 에이전트가 직접 쓰면 안 되는 경로 (Write/Edit/apply_patch). 큐는 op 명령으로만 건드린다.
    "deny_paths": [
        ".operator/pending/", ".operator/approved/", ".operator/sent/", ".operator/rejected/",
        ".operator/guard.json", ".operator/stage.json", ".operator/milestones.json", ".operator/metrics.jsonl",
    ],
}


# 비밀값 읽기. 발송 토큰은 사람이 띄운 프로세스(op serve/telegram/승인 터미널)만 쓴다.
# allow_commands 로도 풀 수 없다.
SECRET_COMMANDS = [
    r"\bsecurity\s+(find-generic-password|find-internet-password|dump-keychain|export|show-keychain-info)\b",
    r"\.config[\\/]operator[\\/]",
    r"\bprintenv\b|(?:^|[;&|(]\s*)(?:env|set|export\s+-p|declare\s+-x)\s*(?:$|[|>;&)])",
]


def secret_dir():
    return os.path.join(os.path.expanduser("~"), ".config", "operator")


# ---------------------------------------------------------------- 공통
def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class OpError(Exception):
    """op 의 함수 API 가 내는 오류. CLI 는 메시지를 stderr 에 쓰고 code 로 끝난다."""

    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.msg, self.code = msg, code


def die(msg, code=1):
    raise OpError(msg, code)


# ---------------------------------------------------------------- authority (사람의 결정이 어느 경로로 왔나)
# 승인·거절, 단계 이동, 비밀값 등록은 Authority 를 받아야만 실행된다. 경로마다 증명의 세기가 다르다.
#
#   terminal   op 를 대화형 터미널에서 실행했다 (op telegram/serve 처럼 터미널에서 띄운 프로세스 안의 버튼 포함).
#              에이전트의 일반적인 셸 호출은 막지만 증명은 아니다. 가짜 터미널(`script -q /dev/null op …`)이나
#              스크립트 파일로 감싼 호출은 통과할 수 있다. 실수 방지 장치로 본다.
#   local      Hermes 플러그인이 Desktop·TUI·CLI 화면에서 친 명령을 받았다. 이 화면들은 같은 사용자 권한의 로컬
#              소켓(slash.exec)으로 명령을 보내므로, 에이전트의 터미널 명령도 원리상 흉내 낼 수 있다. terminal 과 같은 세기.
#   messenger  Hermes 게이트웨이가 텔레그램·디스코드 같은 메신저에서 허용된 사용자의 메시지로 받은 명령. 사용자 ID 는
#              메신저 서버가 보증하고, 에이전트는 사용자 계정으로 메시지를 보낼 수 없다. 지금 가장 강한 경로다.
#
# 세 경로 모두 같은 사용자 권한으로 도는 에이전트가 파이썬으로 이 모듈을 가져와 Authority 를 만드는 것까지는 막지 못한다.
# 그건 격리 등급 2(docker, .operator 일부 읽기 전용)가 막는다.
#
# 프로젝트는 guard.json 의 human_via 로 받을 경로를 고른다. 기본은 셋 다. Hermes 로 만든 프로젝트는
# ["local", "messenger"] (터미널 끔), 엄격하게는 ["messenger"].
AUTHORITY_KINDS = ("terminal", "local", "messenger")


class Authority:
    def __init__(self, kind, who=""):
        if kind not in AUTHORITY_KINDS:
            raise ValueError(f"모르는 authority: {kind}")
        self.kind, self.who = kind, " ".join(str(who).split())[:80]

    @property
    def label(self):
        return self.kind + (f":{self.who}" if self.who else "")

    @classmethod
    def terminal(cls, who=""):
        """대화형 터미널이면 terminal authority, 아니면 OpError(7)."""
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise OpError("이 명령은 사람이 대화형 터미널에서만 실행한다 (에이전트의 셸 도구에는 터미널이 없다). "
                          "사용자에게 무엇을 왜 실행해야 하는지 보여 주고 자기 터미널에서 직접 실행해 달라고 요청해라.", 7)
        return cls("terminal", who)

    def __repr__(self):
        return f"Authority({self.label})"


def human_via(od):
    """이 프로젝트가 받는 사람 경로. guard.json(에이전트가 쓸 수 없는 파일)에 둔다."""
    via = load_json(os.path.join(od, "guard.json"), {}).get("human_via") if od else None
    via = [v for v in (via or AUTHORITY_KINDS) if v in AUTHORITY_KINDS]
    return via or list(AUTHORITY_KINDS)


def human_hint(od, cli, slash):
    """사람에게 부탁할 명령. 터미널 경로를 끈 프로젝트(Hermes)는 슬래시 명령으로 안내한다."""
    return f"`{cli}` (자기 터미널)" if "terminal" in human_via(od) else f"Hermes 에서 `{slash}`"


def require_human(od, authority, what):
    if not isinstance(authority, Authority):
        raise OpError(f"{what}: 사람의 결정이 필요하다.", 7)
    if authority.kind not in human_via(od):
        raise OpError(f"{what}: 이 프로젝트는 {', '.join(human_via(od))} 경로로만 사람의 결정을 받는다 "
                      f"(guard.json human_via). 지금 경로: {authority.kind}.", 7)
    return authority


def terminal_authority(od=None, what="이 명령"):
    """CLI 의 사람 전용 명령 입구. 대화형 터미널인지, 프로젝트가 터미널 경로를 받는지 확인한다."""
    auth = Authority.terminal()
    return require_human(od, auth, what) if od else auth


def find_root(start=None):
    """cwd에서 위로 올라가며 .operator/ 를 찾는다. 없으면 None."""
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(d, OP_DIR_NAME)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def op_dir(required=True, start=None):
    root = find_root(start)
    if root is None:
        if required:
            die("여기엔 .operator/ 가 없다. 먼저 `op init` 을 실행해라.", 2)
        return None
    od = os.path.join(root, OP_DIR_NAME)
    for sub in ("pending", "approved", "sent", "rejected", "passes", "research", "drafts", "tmp", "stages"):
        os.makedirs(os.path.join(od, sub), exist_ok=True)
    return od


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def config(od=None):
    od = od or op_dir()
    return deep_merge(DEFAULT_CONFIG, load_json(os.path.join(od, "config.json"), {}))


def guard_rules(od):
    g = load_json(os.path.join(od, "guard.json"), {})
    out = {}
    for k in DEFAULT_GUARD:
        out[k] = list(DEFAULT_GUARD[k]) + list(g.get(k, []))
    for k in ("allow_commands",):
        out[k] = list(g.get(k, []))
    return out


def parse_front_matter(text):
    """'---' 로 감싼 단순 key: value 헤더를 읽는다. (본문, 헤더dict) 반환."""
    meta = {}
    if text.startswith("---"):
        parts = text.split("\n---", 1)
        if len(parts) == 2:
            header = parts[0][3:]
            body = parts[1].lstrip("\n")
            for line in header.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            return body, meta
    return text, meta


def slugify(s, n=40):
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    return s[:n] or "item"


# ---------------------------------------------------------------- init / status
def init_project(root, stage=None, send_mode=None, human_via_kinds=None):
    """root/.operator 를 만든다. 이미 있으면 빠진 것만 채우고 단계·발송 방식·human_via 는 바꾸지 않는다.
    (od, [참고 메시지]) 를 돌려준다."""
    od = os.path.join(root, OP_DIR_NAME)
    first = not os.path.isdir(od)
    if (stage or "discover") not in STAGES:
        die(f"모르는 단계: {stage} ({', '.join(STAGE_ORDER)})")
    if (send_mode or "human") not in ("human", "agent"):
        die("--send 는 human 또는 agent")
    notes = []
    for sub in ("pending", "approved", "sent", "rejected", "passes", "research", "drafts", "tmp", "stages"):
        os.makedirs(os.path.join(od, sub), exist_ok=True)
    cfg_path = os.path.join(od, "config.json")
    if not os.path.exists(cfg_path):
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        cfg["project"] = os.path.basename(root)
        save_json(cfg_path, cfg)
    gpath = os.path.join(od, "guard.json")
    if not os.path.exists(gpath):
        g = {"send_mode": send_mode or "human", "deny_commands": [], "human_only_commands": [], "deny_paths": [], "allow_commands": []}
        if human_via_kinds:
            g["human_via"] = [k for k in human_via_kinds if k in AUTHORITY_KINDS]
        save_json(gpath, g)
    if not os.path.exists(stage_path(od)):
        if first or stage:
            save_json(stage_path(od), {"stage": stage or "discover", "started": now(),
                                       "history": [{"t": now(), "to": stage or "discover", "by": "init"}]})
    elif stage:
        notes.append(f"참고: 단계는 이미 정해져 있다 ({current_stage(od)}). 바꾸는 건 사람이 `op stage set` 으로 한다.")
    gi = os.path.join(od, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w") as f:
            f.write("tmp/\n*.tmp\n")
    return od, notes


def cmd_init(args):
    """op init [--stage discover|validate|build|operate|learn] [--send human|agent]
    단계와 발송 방식은 처음 만들 때만 정한다. 그 뒤로는 사람이 `op stage set`, guard.json 으로 바꾼다."""
    opts = kv(args)
    od, notes = init_project(os.getcwd(), stage=opts.get("stage"), send_mode=opts.get("send"))
    for n in notes:
        print(n)
    print(f"초기화 완료: {od}")
    cur = current_stage(od)
    if cur:
        print(f"단계: {STAGE_KO[cur]} ({cur}) — {STAGES[cur]['goal']}. 다음: `op stage` 로 할 일을 확인한다.")
    print(f"발송 방식: {send_mode_of(od)} ({'사람이 승인하는 순간 사람 쪽에서 보냄' if send_mode_of(od) == 'human' else '승인 뒤 에이전트가 op send 로 보냄'})")


def status_summary(od):
    """프로젝트 상태를 dict 로. CLI 의 op status 와 플러그인의 /status 가 같이 쓴다."""
    fb = os.path.join(od, "feedback.md")
    st = load_json(state_path(od), None)
    return {
        "root": os.path.dirname(od),
        "business": os.path.exists(os.path.join(od, "business.md")),
        "stage": current_stage(od),
        "send_mode": send_mode_of(od),
        "human_via": human_via(od),
        "pass": st if st and st.get("status") == "running" else None,
        "counts": {s: len([f for f in os.listdir(os.path.join(od, s)) if f.endswith(".md")])
                   for s in ("pending", "approved", "sent", "rejected")},
        "rejections": open(fb, encoding="utf-8").read().count("\n- 2") if os.path.exists(fb) else None,
    }


def cmd_status(args):
    s = status_summary(op_dir())
    print(f"프로젝트: {s['root']}")
    print(f"business.md: {'있음' if s['business'] else '없음 → plan 단계 필요'}")
    cur = s["stage"]
    if cur:
        print(f"단계: {STAGE_KO[cur]} ({cur}) — {STAGES[cur]['goal']}  (자세히: op stage)")
    else:
        print("단계: 사용 안 함 (운영과 같음)")
    print(f"발송 방식: {s['send_mode']}")
    print(f"사람의 결정 경로: {', '.join(s['human_via'])}")
    st = s["pass"]
    if st:
        nxt = next_step(st)
        print(f"진행 중인 pass: {st['pass_id']} (goal: {st.get('goal','')}) 다음 단계: {nxt or '없음 → op pass end'}")
        print(f"  단계 사용: {st['step_count']}/{st['max_steps']}")
        for step in st["steps"]:
            print(f"  - {step['name']}: {step['status']}" + (f" → {step['output']}" if step.get("output") else ""))
    else:
        print("진행 중인 pass 없음")
    for status, n in s["counts"].items():
        print(f"{status}: {n}")
    if s["rejections"] is not None:
        print(f"거절 기록: {s['rejections']}건 → 초안 쓰기 전에 `op feedback` 확인")


# ---------------------------------------------------------------- pass (상태 머신)
def state_path(od):
    return os.path.join(od, "state.json")


def next_step(st):
    for s in st["steps"]:
        if s["status"] != "done":
            return s["name"]
    return None


def cmd_pass(args):
    if not args:
        die("op pass start|next|done|fail|end|show")
    sub, rest = args[0], args[1:]
    od = op_dir()
    cfg = config(od)
    sp = state_path(od)
    st = load_json(sp, None)

    if sub == "start":
        opts = kv(rest)
        if st and st.get("status") == "running" and not opts.get("force"):
            nxt = next_step(st)
            print(f"이미 진행 중인 pass 가 있다: {st['pass_id']} — 다음 단계 '{nxt}' 부터 이어서 해라.")
            print("새로 시작하려면 먼저 `op pass end` (또는 --force).")
            sys.exit(3)
        cur = current_stage(od)
        default_steps = (STAGES[cur]["steps"] if cur else None) or cfg["pass"]["steps"]
        steps = (opts.get("steps") or ",".join(default_steps)).split(",")
        today = datetime.now().strftime("%Y-%m-%d")
        n = 1 + len([f for f in os.listdir(os.path.join(od, "passes")) if f.startswith(today)])
        st = {
            "pass_id": f"{today}-{n:02d}",
            "goal": opts.get("goal", ""),
            "stage": current_stage(od) or "",
            "started": now(),
            "status": "running",
            "max_steps": int(opts.get("max-steps") or cfg["pass"]["max_steps"]),
            "step_count": 0,
            "steps": [{"name": s.strip(), "status": "pending", "output": None, "note": None, "finished": None} for s in steps if s.strip()],
            "log": [],
        }
        save_json(sp, st)
        print(f"pass 시작: {st['pass_id']}  (최대 {st['max_steps']} 단계)")
        print(f"다음 단계: {next_step(st)}")
        return

    if st is None or st.get("status") != "running":
        die("진행 중인 pass 가 없다. `op pass start --goal \"...\"` 로 시작해라.", 3)

    if sub == "next":
        nxt = next_step(st)
        if nxt is None:
            print("NONE — 모든 단계 완료. `op pass end` 로 마무리해라.")
        else:
            print(nxt)
        return

    if sub in ("done", "fail"):
        if not rest:
            die(f"op pass {sub} <step> [--output PATH] [--note ...] [--reason ...]")
        name, opts = rest[0], kv(rest[1:])
        step = next((s for s in st["steps"] if s["name"] == name), None)
        if step is None:
            die(f"'{name}' 은 이 pass 의 단계가 아니다. 단계: {[s['name'] for s in st['steps']]}")
        if sub == "done":
            if st["step_count"] >= st["max_steps"]:
                print(f"단계 상한({st['max_steps']}) 도달. 이 pass 에서는 더 진행하지 말고 `op pass end` 로 끝내라.")
                sys.exit(4)
            out = opts.get("output")
            if out and not os.path.exists(os.path.join(os.path.dirname(od), out)) and not os.path.exists(out):
                die(f"--output 경로가 존재하지 않는다: {out} (산출물 없이 done 처리할 수 없다)")
            step.update(status="done", output=out, note=opts.get("note"), finished=now())
            st["step_count"] += 1
            st["log"].append({"t": now(), "step": name, "event": "done", "output": out})
            save_json(sp, st)
            nxt = next_step(st)
            print(f"{name} 완료 ({st['step_count']}/{st['max_steps']}). 다음 단계: {nxt or 'NONE → op pass end'}")
        else:
            step.update(status="failed", note=opts.get("reason") or opts.get("note"))
            st["log"].append({"t": now(), "step": name, "event": "failed", "reason": step["note"]})
            save_json(sp, st)
            print(f"{name} 실패 기록. 원인을 고친 뒤 같은 단계를 다시 하면 된다 (재개 지점 = {name}).")
        return

    if sub == "end":
        st["status"] = "ended"
        st["ended"] = now()
        pid = st["pass_id"]
        save_json(os.path.join(od, "passes", f"{pid}.json"), st)
        md = [f"# pass {pid}", "", f"- goal: {st.get('goal','')}", f"- started: {st['started']}", f"- ended: {st['ended']}",
              f"- steps used: {st['step_count']}/{st['max_steps']}", "", "## 단계"]
        for s in st["steps"]:
            md.append(f"- {s['name']}: {s['status']}" + (f" → `{s['output']}`" if s.get("output") else "") + (f" — {s['note']}" if s.get("note") else ""))
        pend = sorted(f for f in os.listdir(os.path.join(od, "pending")) if f.endswith(".md"))
        md += ["", "## 승인 대기 (Needs your OK)"] + ([f"- {p}" for p in pend] or ["- 없음"])
        with open(os.path.join(od, "passes", f"{pid}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
        os.remove(sp)
        print(f"pass 종료: {pid} → .operator/passes/{pid}.md")
        print(f"승인 대기 {len(pend)}건. 사람이 {human_hint(od, 'op pending list', '/inbox')} 로 확인한다.")
        return

    if sub == "show":
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return
    die(f"모르는 하위 명령: pass {sub}")


def kv(argv):
    """--key value / --flag 형태를 dict 로."""
    out, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k = a[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                out[k] = argv[i + 1]
                i += 2
            else:
                out[k] = True
                i += 1
        else:
            out.setdefault("_", []).append(a)
            i += 1
    return out


# ---------------------------------------------------------------- verify (검증 게이트)
def verify_file(path, vtype, channel, cfg, root):
    """(ok, [checks]) — checks 는 (name, passed, detail)."""
    checks = []
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    body, meta = parse_front_matter(raw)
    v = cfg["verify"]
    text = body.strip()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        found = [p for p in v["placeholders"] if re.search(safe_regex(p), raw, flags=re.I)]
    checks.append(("placeholder 없음", not found, ", ".join(found) if found else "ok"))
    banned = [w for w in v["banned_words"] if w and w.lower() in raw.lower()]
    checks.append(("금지어 없음", not banned, ", ".join(banned) if banned else "ok"))
    if v["required_words"]:
        missing = [w for w in v["required_words"] if w.lower() not in raw.lower()]
        checks.append(("필수어 포함", not missing, "빠짐: " + ", ".join(missing) if missing else "ok"))

    if vtype == "post":
        p = v["post"]
        ch = (channel or meta.get("channel") or "default").lower()
        mx = p["max_len"].get(ch, p["max_len"]["default"])
        n = len(text)
        checks.append((f"길이 {p['min_len']}~{mx} ({ch})", p["min_len"] <= n <= mx, f"{n}자"))
    elif vtype == "email":
        e = v["email"]
        for k in e["require"]:
            checks.append((f"헤더 {k}", bool(meta.get(k)), meta.get(k) or "없음"))
        n = len(text)
        checks.append((f"본문 길이 {e['min_len']}~{e['max_len']}", e["min_len"] <= n <= e["max_len"], f"{n}자"))
    elif vtype == "research":
        r = v["research"]
        urls = set(re.findall(r"https?://[^\s)\]>\"']+", raw))
        checks.append((f"출처 {r['min_sources']}개 이상", len(urls) >= r["min_sources"], f"{len(urls)}개"))
        checks.append((f"본문 {r['min_len']}자 이상", len(text) >= r["min_len"], f"{len(text)}자"))
    elif vtype == "site":
        s = v["site"]
        if not s.get("command"):
            checks.append(("빌드 명령 설정", False, "config.json verify.site.command 가 비어 있다 (예: npm run build)"))
        else:
            try:
                r = subprocess.run(s["command"], shell=True, cwd=root, capture_output=True, text=True, timeout=s.get("timeout", 600))
                tail = (r.stdout + r.stderr).strip().splitlines()[-5:]
                checks.append((f"빌드 `{s['command']}` exit 0", r.returncode == 0, " | ".join(tail)[:400] or f"exit {r.returncode}"))
            except subprocess.TimeoutExpired:
                checks.append(("빌드 시간 내 완료", False, "timeout"))
    elif vtype == "other":
        checks.append(("비어 있지 않음", len(text) >= 10, f"{len(text)}자"))
    else:
        checks.append(("타입", False, f"모르는 타입 {vtype} (post|email|research|site|other)"))
    return all(c[1] for c in checks), checks


def safe_regex(p):
    """정규식이 아니면(예: '[TODO]' 같은 리터럴) 그대로 문자열 매칭으로 취급한다."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            re.compile(p)
        return p
    except re.error:
        return re.escape(p)


def print_checks(checks):
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def cmd_verify(args):
    opts = kv(args)
    files = opts.get("_") or []
    if not files:
        die("op verify <file> --type post|email|research|site|other [--channel x]")
    od = op_dir()
    cfg = config(od)
    root = os.path.dirname(od)
    all_ok = True
    for fp in files:
        if not os.path.exists(fp):
            die(f"파일 없음: {fp}")
        vtype = opts.get("type") or guess_type(fp)
        ok, checks = verify_file(fp, vtype, opts.get("channel"), cfg, root)
        print(f"{fp} ({vtype}): {'PASS' if ok else 'FAIL'}")
        print_checks(checks)
        all_ok &= ok
    sys.exit(0 if all_ok else 1)


def guess_type(fp):
    with open(fp, encoding="utf-8") as f:
        _, meta = parse_front_matter(f.read())
    if meta.get("type"):
        return meta["type"]
    name = os.path.basename(fp).lower()
    for t in ("post", "email", "research", "site"):
        if t in name:
            return t
    return "other"


# ---------------------------------------------------------------- pending (승인 큐)
def next_id(od):
    ids = []
    for sub in ("pending", "approved", "sent", "rejected"):
        for f in os.listdir(os.path.join(od, sub)):
            m = re.match(r"(\d{4})-", f)
            if m:
                ids.append(int(m.group(1)))
    return f"{(max(ids) + 1) if ids else 1:04d}"


def find_item(od, item_id, statuses=("pending", "approved", "sent", "rejected")):
    for sub in statuses:
        for f in os.listdir(os.path.join(od, sub)):
            if f.startswith(item_id + "-") and f.endswith(".md"):
                return sub, os.path.join(od, sub, f)
    return None, None


def cmd_pending(args):
    if not args:
        die("op pending add|list|show|approve|reject")
    sub, rest = args[0], args[1:]
    od = op_dir()
    cfg = config(od)
    root = os.path.dirname(od)

    if sub == "add":
        opts = kv(rest)
        src = (opts.get("_") or [None])[0]
        if not src or not os.path.exists(src):
            die("op pending add <draft-file> --type post|email|research|site|other [--channel x] [--title ...] [--action \"실행할 명령\"]")
        vtype = opts.get("type") or guess_type(src)
        cur = current_stage(od)
        allowed = STAGES[cur]["types"] if cur else None
        if allowed and vtype not in allowed:
            die(f"지금은 {STAGE_KO[cur]} 단계다. 이 단계에서 승인 큐에 올릴 수 있는 종류: {', '.join(allowed)}. "
                f"'{vtype}' 는 {', '.join(STAGE_KO[n] for n in STAGE_ORDER if STAGES[n]['types'] is None or vtype in STAGES[n]['types'])} 단계에서 올린다. "
                "`op stage` 로 지금 할 일을 확인해라.", 8)
        ok, checks = verify_file(src, vtype, opts.get("channel"), cfg, root)
        print(f"검증 ({vtype}): {'PASS' if ok else 'FAIL'}")
        print_checks(checks)
        if not ok:
            print("검증 실패 → pending 에 올리지 않는다. 초안을 고친 뒤 다시 시도해라.")
            sys.exit(1)
        with open(src, encoding="utf-8") as f:
            raw = f.read()
        body, meta = parse_front_matter(raw)
        item_id = next_id(od)
        first_line = body.strip().splitlines()[0][:60] if body.strip() else ""
        title = opts.get("title") or meta.get("title") or first_line or "untitled"
        fname = f"{item_id}-{vtype}-{slugify(title)}.md"
        header = {
            "id": item_id, "type": vtype, "title": title,
            "channel": opts.get("channel") or meta.get("channel") or "",
            "to": meta.get("to", ""), "subject": meta.get("subject", ""),
            "action": opts.get("action") or meta.get("action") or (f"op deliver {item_id}" if ticket_channel({"type": vtype, "channel": opts.get("channel") or meta.get("channel")}) else ""),
            "source": os.path.relpath(src, root), "status": "pending", "created": now(),
            "verify": f"passed {len(checks)} checks",
        }
        pass_st = load_json(state_path(od), None)
        if pass_st:
            header["pass"] = pass_st["pass_id"]
        lines = ["---"] + [f"{k}: {v}" for k, v in header.items() if v != ""] + ["---", "", body.rstrip() + "\n"]
        dst = os.path.join(od, "pending", fname)
        with open(dst, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"승인 대기에 올림: .operator/pending/{fname}")
        print(f"이제 이 항목은 사람이 {human_hint(od, 'op pending approve ' + item_id, '/ok ' + item_id)} 로 승인할 때까지 밖으로 나가지 않는다.")
        return

    if sub == "list":
        opts = kv(rest)
        statuses = [opts.get("status")] if opts.get("status") else ["pending", "approved"]
        if any(s not in QUEUE_STATUSES for s in statuses):
            die(f"--status 는 {'|'.join(QUEUE_STATUSES)}")
        items = queue_items(od, statuses)
        for s in statuses:
            mine = [it for it in items if it["status"] == s]
            print(f"== {s} ({len(mine)})")
            for it in mine:
                meta = it["meta"]
                extra = meta.get("channel") or meta.get("to") or ""
                print(f"  {it['id']}  {meta.get('type', '?'):8s} {extra:20s} {meta.get('title', it['file'])}")
        if not items:
            print("  (비어 있음)")
        return

    if sub == "show":
        if not rest:
            die("op pending show <id>")
        s, p = find_item(od, rest[0])
        if not p:
            die(f"항목 없음: {rest[0]}")
        print(f"[{s}] {p}\n")
        with open(p, encoding="utf-8") as f:
            print(f.read())
        return

    if sub in ("approve", "reject"):
        if not rest:
            die(f"op pending {sub} <id> [--note ...] [--action \"<실행할 명령>\"]")
        opts = kv(rest[1:])
        item_id = rest[0]
        auth = terminal_authority(od, "승인/거절")
        res = pending_decide(od, item_id, sub, auth, note=opts.get("note") or opts.get("reason"),
                             action=opts.get("action"), send=not opts.get("no-send"))
        meta = res["meta"]
        print(f"{item_id} → {meta['status']}")
        if res["sent"] is not None:
            code, msg = res["sent"]
            print(msg)
            sys.exit(code)
        if meta["status"] == "approved":
            if (meta.get("action") or "").strip():
                who = "내 터미널에서 `op send " + item_id + "`" if send_mode_of(od) == "human" else "에이전트가 `op send " + item_id + "`"
                print(f"다음: {who} 로 승인된 action 을 실행한다.\n  action: {meta['action']}")
            else:
                print(f"참고: action 이 없어 `op send` 는 거부된다. `op pending approve` 는 끝났으니 새 티켓으로 다시 올리거나 "
                      f"다음에는 `--action \"<명령>\"` 을 붙여 승인해라.")
        else:
            print("거절 사유는 .operator/feedback.md 에 남아 다음 초안 작성 때 반영된다.")
        return
    die(f"모르는 하위 명령: pending {sub}")


QUEUE_STATUSES = ("pending", "approved", "sent", "rejected")


def queue_items(od, statuses=("pending",)):
    """[{id, status, file, path, meta, body}] — 큐 읽기. 누구나 부를 수 있다."""
    out = []
    for s in statuses:
        for f in sorted(os.listdir(os.path.join(od, s))):
            if f.endswith(".md"):
                p = os.path.join(od, s, f)
                with open(p, encoding="utf-8") as fh:
                    body, meta = parse_front_matter(fh.read())
                out.append({"id": meta.get("id", f[:4]), "status": s, "file": f, "path": p, "meta": meta, "body": body})
    return out


def pending_decide(od, item_id, decision, authority, note=None, action=None, send=True, secrets_env=None):
    """사람의 결정 하나를 큐에 반영한다. decision 은 approve|reject.
    발송 방식이 human 이고 승인된 action 이 있으면 send=True 일 때 바로 실행한다 (run_action).
    secrets_env 가 없으면 이 티켓에 필요한 토큰만 그때 읽는다. {"meta": ..., "sent": (code, msg) | None}"""
    if decision not in ("approve", "reject"):
        raise OpError("결정은 approve 또는 reject", 1)
    if not re.fullmatch(r"\d{4}", str(item_id)):
        raise OpError(f"티켓 번호는 네 자리 숫자다: {item_id}", 1)
    require_human(od, authority, "승인/거절")
    try:
        meta = set_status(od, item_id, "approved" if decision == "approve" else "rejected", note=note, action=action,
                          by=authority.label)
    except ValueError as e:
        raise OpError(str(e), 1)
    sent = None
    if meta["status"] == "approved" and send and send_mode_of(od) == "human" and (meta.get("action") or "").strip():
        env = secrets_env if secrets_env is not None else channel_env(names=ticket_secret_names(meta))
        sent = run_action(od, item_id, secrets_env=env)
    return {"meta": meta, "sent": sent}


def set_status(od, item_id, new_status, note=None, action=None, by=None):
    """pending 티켓을 approved/rejected 로 옮긴다. 호출자가 사람임을 이미 확인했다고 가정한다.
    밖에서는 pending_decide 를 쓴다 (사람 경로 확인 포함)."""
    if new_status not in ("approved", "rejected"):
        raise ValueError("상태는 approved 또는 rejected")
    _, p = find_item(od, item_id, ("pending",))
    if not p:
        raise ValueError(f"pending 에 {item_id} 가 없다.")
    with open(p, encoding="utf-8") as f:
        body, meta = parse_front_matter(f.read())
    if new_status == "approved" and action:
        if re.search(r"\bop(?:\.py)?\s+(?:pending|send|serve)\b", action):
            raise ValueError("action 에 op 의 큐 명령을 넣을 수 없다.")
        meta["action"] = action
    meta["status"] = new_status
    meta[new_status] = now()
    if by:
        meta["decided_by"] = by
    if note:
        meta["note"] = " ".join(str(note).split())
    dst = os.path.join(od, new_status, os.path.basename(p))
    with open(dst, "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---\n\n" + body)
    os.remove(p)
    if new_status == "rejected":
        record_feedback(od, meta, body, note)
    return meta


# ---------------------------------------------------------------- feedback (거절 사유를 다음 초안에 반영)
def record_feedback(od, meta, body, reason):
    path = os.path.join(od, "feedback.md")
    new = not os.path.exists(path)
    excerpt = " ".join(body.split())[:120]
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write("# 거절 기록\n\n다음 초안을 쓰기 전에 읽는다. 같은 이유로 다시 거절되지 않게 한다. 사람이 직접 고쳐도 된다.\n\n")
        f.write(f"- {now()[:10]} · {meta.get('type', '?')}" + (f"/{meta['channel']}" if meta.get("channel") else "")
                + f" · {meta.get('id', '')} {meta.get('title', '')}\n  - 사유: {' '.join(str(reason or '사유 없음').split())}\n  - 초안: {excerpt}\n")


def cmd_feedback(args):
    opts = kv(args)
    od = op_dir()
    path = os.path.join(od, "feedback.md")
    if not os.path.exists(path):
        print("거절 기록 없음")
        return
    entries = re.split(r"\n(?=- \d{4}-)", open(path, encoding="utf-8").read())
    head, items = entries[0], entries[1:]
    n = int(opts.get("last") or 10)
    print(f"최근 거절 {min(n, len(items))}/{len(items)}건 (.operator/feedback.md)")
    for e in items[-n:]:
        print(e.strip())


# ---------------------------------------------------------------- stage (아이디어 → 검증 → 만들기 → 운영 → 배우기)
# 사업이 지금 어느 시기에 있는지 .operator/stage.json 에 기록한다. 단계마다 목표, 승인 큐에 올릴 수 있는 종류,
# 기본 pass 단계, 산출물 문서의 필수 섹션이 다르다. 다음 단계로 넘기는 건 사람만 한다 (op stage advance).
# stage.json 이 없는 프로젝트(0.4 이전)는 단계 모델을 쓰지 않는 것으로 보고 운영과 똑같이 동작한다.
STAGE_ORDER = ["discover", "validate", "build", "operate", "learn"]
STAGE_KO = {"discover": "발견", "validate": "검증", "build": "만들기", "operate": "운영", "learn": "배우기"}
STAGES = {
    "discover": {"goal": "무엇을, 누구에게, 왜 팔지 정한다", "types": ["research", "other"],
                 "steps": ["interview", "draft", "check", "report"],
                 "sections": [("문제", "problem"), ("고객", "customer"), ("제안", "offer"), ("성공 지표", "success metric")]},
    "validate": {"goal": "만들 가치가 있는지 판단한다", "types": ["research", "other"],
                 "steps": ["research", "decide", "check", "report"],
                 "sections": [("근거", "evidence"), ("결정", "decision")]},
    "build": {"goal": "첫 버전을 실제로 동작하게 만든다", "types": ["site", "research", "other"],
              "steps": ["milestone", "test", "report"], "sections": [("범위", "scope")]},
    "operate": {"goal": "사람들에게 알리고 매일 굴린다", "types": None, "steps": None, "sections": []},
    "learn": {"goal": "반응을 보고 다음 행동을 정한다", "types": ["research", "other"],
              "steps": ["collect", "review", "check", "report"], "sections": [("결과", "results"), ("다음", "next")]},
}
STAGE_TEMPLATES = {
    "discover": """# 발견

<!-- 에이전트는 사용자와 대화하며 아래 네 섹션을 채운다. 질문은 한 번에 하나씩. 사용자가 답하지 않은 내용은 지어내지 않는다.
     이 주석은 지워도 되고 남겨도 된다 (검사에서 무시한다). -->

## 문제
<!-- 누가, 언제, 무엇 때문에 불편한가. 지금은 그 문제를 어떻게 해결하고 있나. -->

## 고객
<!-- 처음 팔 사람 한 부류. 어디서 만날 수 있나. -->

## 제안
<!-- 무엇을 얼마에 주나. 지금 방법보다 나은 점 하나. -->

## 성공 지표
<!-- 기간과 숫자 하나. 예: 첫 달 유료 고객 3명. 배우기 단계에서 이 숫자와 실제를 비교한다. -->
""",
    "validate": """# 검증

## 근거
<!-- 비슷한 서비스와 가격, 사람들이 실제로 불평하는 글, 고객이 모이는 곳. 출처 URL 3개 이상. -->

## 결정
<!-- 이유를 적고, 아래 형식의 한 줄을 남긴다. 진행 → 만들기, 수정 → 발견으로 돌아감, 중단 → 멈춤. -->
결정:
""",
    "build": """# 만들기

## 범위
<!-- 첫 버전에 넣을 것과 뺄 것. 마일스톤은 `op milestone add "제목" --test "검사 명령"` 으로 등록하고,
     `op milestone done <번호>` 가 검사 명령을 실제로 돌려 통과해야 완료된다. -->
""",
    "operate": """# 운영

<!-- 운영 단계는 필수 문서가 없다. 채널, 톤, 주기 같은 메모를 남겨도 된다. -->
""",
    "learn": """# 배우기

## 결과
<!-- 발견 단계의 성공 지표와 실제 숫자(`op metric list`)를 비교한다. 거절 사유(`op feedback`)도 본다. -->

## 다음
<!-- 무엇을 바꿀지 적고, 아래 형식의 한 줄을 남긴다. 운영 → 계속 굴림, 만들기 → 제품을 고침, 발견 → 처음부터 다시. -->
다음 단계:
""",
}
_DECISION = re.compile(r"^\s*(?:결정|decision)\s*[:：]\s*(진행|수정|중단|go|revise|stop)\b", re.I | re.M)
_NEXT = re.compile(r"^\s*(?:다음\s*단계|next\s*stage)\s*[:：]\s*(운영|만들기|발견|operate|build|discover)\b", re.I | re.M)
_TARGET = {"진행": "build", "go": "build", "수정": "discover", "revise": "discover", "중단": None, "stop": None,
           "운영": "operate", "operate": "operate", "만들기": "build", "build": "build", "발견": "discover", "discover": "discover"}
_TRIVIAL_TEST = re.compile(r"^\s*(true|:|exit\s+0|echo\b[^;&|]*)\s*$")


def stage_path(od):
    return os.path.join(od, "stage.json")


def load_stage(od):
    return load_json(stage_path(od), None)


def current_stage(od):
    st = load_stage(od)
    return st.get("stage") if st else None


def stage_doc(od, name):
    return os.path.join(od, "stages", f"{name}.md")


def send_mode_of(od):
    """발송 방식은 guard.json(에이전트가 쓸 수 없는 파일)에 둔다. 없으면 human."""
    mode = load_json(os.path.join(od, "guard.json"), {}).get("send_mode") or "human"
    return mode if mode in ("human", "agent") else "human"


def md_sections(text):
    """HTML 주석을 지운 뒤 '## 제목' 단위로 나눈다. ({제목소문자: 내용}, 주석 지운 전체)."""
    clean = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out, cur = {}, None
    for line in clean.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1).strip().lower()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}, clean


def _section(secs, aliases):
    for k, v in secs.items():
        if any(a.lower() in k for a in aliases):
            return v
    return None


def _since(st, iso):
    try:
        return datetime.fromisoformat(iso) >= datetime.fromisoformat(st["started"])
    except (KeyError, TypeError, ValueError):
        return True


def load_milestones(od):
    return load_json(os.path.join(od, "milestones.json"), [])


def load_metrics(od):
    path = os.path.join(od, "metrics.jsonl")
    out = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def sent_items(od):
    out = []
    for f in sorted(os.listdir(os.path.join(od, "sent"))):
        if f.endswith(".md"):
            _, meta = parse_front_matter(open(os.path.join(od, "sent", f), encoding="utf-8").read())
            out.append(meta)
    return out


def stage_checks(od, name, cfg):
    """(checks, 다음 단계). checks 는 (이름, 통과, 설명)."""
    spec, st = STAGES[name], load_stage(od) or {}
    checks, target = [], STAGE_ORDER[STAGE_ORDER.index(name) + 1] if name != "learn" else None
    doc = stage_doc(od, name)
    text = open(doc, encoding="utf-8").read() if os.path.exists(doc) else ""
    secs, clean = md_sections(text)
    if spec["sections"]:
        checks.append((f"문서 .operator/stages/{name}.md", bool(text), "있음" if text else "없음 → `op stage doc` 으로 만든다"))
        for ko, en in spec["sections"]:
            body = _section(secs, [ko, en])
            n = len(re.sub(r"\s+", "", body or ""))
            checks.append((f"'{ko}' 채움 (10자 이상)", body is not None and n >= 10, f"{n}자" if body is not None else "섹션 없음"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            found = [p for p in cfg["verify"]["placeholders"] if re.search(safe_regex(p), clean, flags=re.I)]
        checks.append(("빈칸 표시 없음", not found, ", ".join(found) if found else "ok"))
    if name == "validate":
        urls = set(re.findall(r"https?://[^\s)\]>\"']+", clean))
        need = cfg["verify"]["research"]["min_sources"]
        checks.append((f"출처 {need}개 이상", len(urls) >= need, f"{len(urls)}개"))
        m = _DECISION.search(clean)
        checks.append(("결정 한 줄 (결정: 진행|수정|중단)", bool(m), m.group(1) if m else "없음"))
        target = _TARGET[m.group(1).lower()] if m else None
        if m and target is None:
            checks.append(("결정이 중단이 아님", False, "중단이면 다음 단계로 가지 않는다. 다시 해 보려면 결정을 바꾸거나 사람이 `op stage back --to discover`"))
    elif name == "build":
        ms = load_milestones(od)
        done = [m for m in ms if m.get("done")]
        checks.append(("마일스톤 1개 이상", bool(ms), f"{len(ms)}개"))
        checks.append(("마일스톤 모두 통과", bool(ms) and len(done) == len(ms), f"{len(done)}/{len(ms)}"))
        if cfg["verify"]["site"].get("command"):
            vok, vchecks = verify_file(doc, "site", None, cfg, os.path.dirname(od)) if text else (False, [])
            checks.append(("빌드 성공 (verify.site.command)", vok, vchecks[-1][2] if vchecks else "문서 없음"))
    elif name == "operate":
        sent = [m for m in sent_items(od) if _since(st, m.get("executed") or m.get("created") or "")]
        checks.append(("이 단계에서 보낸 항목 1개 이상", bool(sent), f"{len(sent)}개"))
    elif name == "learn":
        metrics = [m for m in load_metrics(od) if _since(st, m.get("t", ""))]
        checks.append(("이 단계에서 기록한 지표 1개 이상 (op metric add)", bool(metrics), f"{len(metrics)}개"))
        m = _NEXT.search(clean)
        checks.append(("다음 단계 한 줄 (다음 단계: 운영|만들기|발견)", bool(m), m.group(1) if m else "없음"))
        target = _TARGET[m.group(1).lower()] if m else None
    return checks, target


def _discover_metric(od):
    secs, _ = md_sections(open(stage_doc(od, "discover"), encoding="utf-8").read()) if os.path.exists(stage_doc(od, "discover")) else ({}, "")
    return _section(secs, ["성공 지표", "success metric"])


class StageBlocked(OpError):
    def __init__(self, msg, checks):
        super().__init__(msg, 1)
        self.checks = checks


def stage_move(od, event, authority, to=None, reason=None):
    """사람의 단계 이동. event 는 advance|back|set. advance 는 지금 단계 검사를 모두 통과해야 하고
    (아니면 StageBlocked), 다음 단계는 검사가 정한다. back 은 이유가 필요하다.
    {"from", "to", "checks", "event"} 를 돌려준다."""
    if event not in ("advance", "back", "set"):
        raise OpError("단계 이동은 advance|back|set", 1)
    require_human(od, authority, "단계 이동")
    st = load_stage(od)
    cur = st.get("stage") if st else None
    checks = []
    if event in ("set", "back"):
        if to not in STAGES:
            raise OpError(f"op stage {event} {'<단계>' if event == 'set' else '--to <단계> --reason ...'}   단계: {', '.join(STAGE_ORDER)}", 1)
        if event == "back" and not reason:
            raise OpError("되돌리는 이유를 --reason 으로 남긴다. 다음 단계 문서를 쓸 때 에이전트가 읽는다.", 1)
        rec = {"t": now(), "from": cur, "to": to, "by": authority.label, "event": event}
        if reason:
            rec["reason"] = " ".join(str(reason).split())
    else:
        if not cur:
            raise OpError("이 프로젝트는 단계 모델을 쓰지 않는다. 시작하려면 `op stage set discover` (또는 지금 위치).", 1)
        checks, to = stage_checks(od, cur, config(od))
        if not all(c[1] for c in checks):
            raise StageBlocked("통과하지 못한 항목이 있어 넘어가지 않는다.", checks)
        rec = {"t": now(), "from": cur, "to": to, "by": authority.label, "event": "advance"}
        doc = stage_doc(od, cur)
        if os.path.exists(doc):
            import hashlib
            with open(doc, "rb") as f:
                data = f.read()
            rec["doc_sha256"] = hashlib.sha256(data).hexdigest()
            hist = os.path.join(od, "stages", "history")
            os.makedirs(hist, exist_ok=True)
            snap = os.path.join(hist, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{cur}.md")
            with open(snap, "wb") as f:
                f.write(data)
            rec["snapshot"] = os.path.relpath(snap, os.path.dirname(od))
    st = st or {"history": []}
    st["history"] = (st.get("history") or []) + [rec]
    st["stage"], st["started"] = to, now()
    save_json(stage_path(od), st)
    return {"from": cur, "to": to, "checks": checks, "event": event}


def stage_overview(od):
    """지금 단계, 목표, 넘어가기 검사. 플러그인의 /stage 가 쓴다."""
    st = load_stage(od)
    cur = st.get("stage") if st else None
    if not cur:
        return {"stage": None}
    checks, target = stage_checks(od, cur, config(od))
    last_back = next((h for h in reversed(st.get("history") or []) if h.get("event") == "back"), None)
    return {"stage": cur, "goal": STAGES[cur]["goal"], "started": st.get("started", ""), "checks": checks,
            "ready": all(c[1] for c in checks), "next": target,
            "back_reason": last_back.get("reason") if last_back and last_back.get("to") == cur else None}


def cmd_stage(args):
    sub, rest = (args[0], args[1:]) if args else ("show", [])
    opts = kv(rest)
    od = op_dir()
    cfg = config(od)
    st = load_stage(od)
    cur = st.get("stage") if st else None

    if sub in ("advance", "back", "set"):
        auth = terminal_authority(od, "단계 이동")
        to = (opts.get("_") or [None])[0] if sub == "set" else opts.get("to")
        try:
            res = stage_move(od, sub, auth, to=to, reason=opts.get("reason"))
        except StageBlocked as e:
            print(f"{STAGE_KO[cur]} 단계 검사:")
            print_checks(e.checks)
            raise
        if sub == "advance":
            print(f"{STAGE_KO[cur]} 단계 검사:")
            print_checks(res["checks"])
            if cur == "build":
                print("등록된 마일스톤과 검사 명령 (그럴듯한 검사인지 확인해라):")
                for m in load_milestones(od):
                    print(f"  {m['n']}. {m['title']}  ← {m.get('test')}")
        to = res["to"]
        print(f"단계: {STAGE_KO.get(cur, '없음') if cur else '없음'} → {STAGE_KO[to]} ({to}). {STAGES[to]['goal']}.")
        if os.path.exists(state_path(od)):
            print("참고: 진행 중인 pass 는 이전 단계 기준이다. 에이전트에게 `op pass end` 후 새 pass 를 시작하게 해라.")
        return

    if not cur:
        if sub == "show":
            print("단계 모델을 쓰지 않는 프로젝트다 (운영과 똑같이 동작한다).")
            print("아이디어부터 같이 가려면 사람이 `op stage set discover`, 이미 운영 중이면 `op stage set operate`.")
            return
        die("단계 모델을 쓰지 않는 프로젝트다. 사람이 `op stage set <단계>` 로 시작한다.")

    if sub == "show":
        spec = STAGES[cur]
        print(f"단계: {STAGE_KO[cur]} ({cur})  시작 {st.get('started', '')[:10]}")
        print(f"목표: {spec['goal']}")
        print("흐름: " + " → ".join(f"[{STAGE_KO[n]}]" if n == cur else STAGE_KO[n] for n in STAGE_ORDER) + " (배우기 다음은 사람이 고른 단계)")
        print(f"승인 큐에 올릴 수 있는 것: {', '.join(spec['types']) if spec['types'] else '전부'}")
        print(f"기본 pass 단계: {', '.join(spec['steps'] or cfg['pass']['steps'])}")
        print(f"산출물 문서: .operator/stages/{cur}.md ({'있음' if os.path.exists(stage_doc(od, cur)) else '없음 → op stage doc'})")
        last_back = next((h for h in reversed(st.get("history") or []) if h.get("event") == "back"), None)
        if last_back and last_back.get("to") == cur:
            print(f"되돌아온 이유 (사람): {last_back.get('reason', '')}")
        if cur == "learn":
            metric = _discover_metric(od)
            if metric:
                print(f"발견 단계의 성공 지표: {' '.join(metric.split())[:200]}")
        if cur == "build":
            ms = load_milestones(od)
            print(f"마일스톤: {len([m for m in ms if m.get('done')])}/{len(ms)} 통과  (op milestone list)")
        checks, target = stage_checks(od, cur, cfg)
        print(f"넘어가기 조건 ({'모두 통과 → 사람에게 ' + human_hint(od, 'op stage advance', '/advance') + ' 요청' if all(c[1] for c in checks) else '아직'}):")
        print_checks(checks)
        return

    if sub == "doc":
        name = (opts.get("_") or [cur])[0]
        if name not in STAGES:
            die(f"모르는 단계: {name}")
        path = stage_doc(od, name)
        if os.path.exists(path):
            print(f"이미 있다: .operator/stages/{name}.md")
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(STAGE_TEMPLATES[name])
            print(f"만듦: .operator/stages/{name}.md — 섹션을 채운 뒤 `op stage check`.")
        return

    if sub == "check":
        checks, target = stage_checks(od, cur, cfg)
        ok = all(c[1] for c in checks)
        print(f"{STAGE_KO[cur]} 단계: {'PASS' if ok else 'FAIL'}" + (f" → 다음: {STAGE_KO[target]}" if ok and target else ""))
        print_checks(checks)
        if ok:
            print(f"사람에게 결과를 보여 주고 {human_hint(od, 'op stage advance', '/advance')} 를 실행해 달라고 요청해라.")
        sys.exit(0 if ok else 1)

    if sub == "history":
        for h in st.get("history") or []:
            print(f"  {h.get('t', '')[:16]}  {STAGE_KO.get(h.get('from'), '-') if h.get('from') else '-'} → {STAGE_KO.get(h.get('to'), h.get('to'))}"
                  f"  ({h.get('event', h.get('by', ''))})" + (f"  이유: {h['reason']}" if h.get("reason") else ""))
        return
    die("op stage [show|doc|check|history]   사람만: advance | back --to <단계> --reason ... | set <단계>")


# ---------------------------------------------------------------- milestone (만들기 단계: 검사 명령이 통과해야 완료)
def cmd_milestone(args):
    sub, rest = (args[0], args[1:]) if args else ("list", [])
    opts = kv(rest)
    od = op_dir()
    cfg = config(od)
    path = os.path.join(od, "milestones.json")
    ms = load_milestones(od)
    cur = current_stage(od)

    if sub == "add":
        title = " ".join(opts.get("_") or []).strip()
        if not title:
            die('op milestone add "제목" [--test "검사 명령"]')
        if cur not in (None, "build"):
            die(f"마일스톤은 만들기 단계에서 등록한다 (지금: {STAGE_KO[cur]}).", 8)
        test = opts.get("test") if isinstance(opts.get("test"), str) else None
        if test and _TRIVIAL_TEST.match(test):
            die("검사 명령이 아무것도 검사하지 않는다. 실제 테스트·빌드·실행 확인 명령을 넣어라.")
        ms.append({"n": len(ms) + 1, "title": title, "test": test, "done": False, "created": now()})
        save_json(path, ms)
        print(f"마일스톤 {len(ms)}: {title}  검사: {test or '(config verify.build.test 또는 verify.site.command 사용)'}")
        return

    if sub == "list":
        if not ms:
            print("마일스톤 없음 → op milestone add \"제목\" --test \"검사 명령\"")
            return
        for m in ms:
            print(f"  [{'x' if m.get('done') else ' '}] {m['n']}. {m['title']}  ← {m.get('test') or '(기본 검사)'}"
                  + (f"  exit {m['exit']} {m.get('checked', '')[:16]}" if m.get("exit") is not None else ""))
        return

    if sub in ("done", "reopen"):
        try:
            m = ms[int((opts.get("_") or ["0"])[0]) - 1]
        except (ValueError, IndexError):
            die(f"op milestone {sub} <번호>")
        if sub == "reopen":
            m["done"] = False
            save_json(path, ms)
            print(f"{m['n']}. {m['title']} → 다시 진행 중")
            return
        test = m.get("test") or cfg["verify"]["build"].get("test") or cfg["verify"]["site"].get("command")
        if not test:
            die("검사 명령이 없다. `op milestone add ... --test \"명령\"` 으로 등록하거나 config.json 의 verify.build.test 를 설정해라.")
        print(f"[milestone {m['n']}] {test}")
        try:
            r = subprocess.run(test, shell=True, cwd=os.path.dirname(od), capture_output=True, text=True,
                               timeout=cfg["verify"]["build"].get("timeout", 900))
            code, tail = r.returncode, (r.stdout + r.stderr).strip().splitlines()[-8:]
        except subprocess.TimeoutExpired:
            code, tail = 124, ["timeout"]
        print("\n".join(tail))
        m.update(exit=code, checked=now(), done=(code == 0), output=" | ".join(tail)[-400:])
        save_json(path, ms)
        print(f"{m['n']}. {m['title']} → {'통과' if code == 0 else f'실패 (exit {code}) — 고친 뒤 다시 op milestone done ' + str(m['n'])}")
        left = [x for x in ms if not x.get("done")]
        if code == 0 and not left:
            print("모든 마일스톤 통과. `op stage check` 후 사람에게 `op stage advance` 를 요청해라 (첫 배포는 승인 큐로).")
        sys.exit(0 if code == 0 else 1)
    die("op milestone add|list|done|reopen")


# ---------------------------------------------------------------- metric (배우기 단계의 입력)
def cmd_metric(args):
    sub, rest = (args[0], args[1:]) if args else ("list", [])
    opts = kv(rest)
    od = op_dir()
    if sub == "add":
        pos = opts.get("_") or []
        if len(pos) < 2:
            die('op metric add <이름> <값> [--note "..."] [--source "어디서 봤는지"]')
        name, value = pos[0], " ".join(pos[1:])
        rec = {"t": now(), "name": name, "value": value, "stage": current_stage(od) or ""}
        for k in ("note", "source"):
            if isinstance(opts.get(k), str):
                rec[k] = " ".join(opts[k].split())
        with open(os.path.join(od, "metrics.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"기록: {name} = {value}")
        return
    if sub == "list":
        items = load_metrics(od)
        n = int(opts.get("last") or 30)
        print(f"지표 {min(n, len(items))}/{len(items)}건 (.operator/metrics.jsonl)")
        for m in items[-n:]:
            print(f"  {m.get('t', '')[:10]}  {m.get('name')} = {m.get('value')}" + (f"  ({m['source']})" if m.get("source") else "")
                  + (f"  — {m['note']}" if m.get("note") else ""))
        sent = sent_items(od)
        by = {}
        for s in sent:
            k = s.get("channel") or s.get("type") or "?"
            by[k] = by.get(k, 0) + 1
        rejected = len([f for f in os.listdir(os.path.join(od, "rejected")) if f.endswith(".md")])
        print("자동 집계: 보냄 " + (", ".join(f"{k} {v}" for k, v in sorted(by.items())) or "0") + f" · 거절 {rejected}")
        return
    die("op metric add <이름> <값> [--note] [--source] | list [--last N]")


# ---------------------------------------------------------------- deliver (승인된 티켓을 실제 채널로 보냄)
# 토큰은 환경 변수나 프로젝트 밖 ~/.config/operator/env 에서만 읽는다. 티켓·로그에는 절대 쓰지 않는다.
CHANNELS = {
    "x": {"env": ["X_USER_ACCESS_TOKEN"], "doc": "X API v2 사용자 토큰 (OAuth 2.0, tweet.write)"},
    "threads": {"env": ["THREADS_USER_ID", "THREADS_ACCESS_TOKEN"], "doc": "Threads API 사용자 ID 와 토큰 (threads_content_publish)"},
    "email": {"env": ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"], "doc": "SMTP (STARTTLS 587 기본, SMTP_PORT 로 변경)"},
    "webhook": {"env": ["OPERATOR_WEBHOOK_URL"], "doc": "Slack/Discord 등 수신 웹훅 URL"},
}


# 채널 밖에서 쓰는 비밀값 이름. op secret set 으로 등록할 수 있는 이름의 전체 목록이기도 하다.
EXTRA_SECRETS = ["X_REFRESH_TOKEN", "X_CLIENT_ID", "X_CLIENT_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OPERATOR_NTFY_TOPIC"]


def secret_names():
    return [n for spec in CHANNELS.values() for n in spec["env"]] + EXTRA_SECRETS + ["SMTP_PORT"]


def _env_file():
    return os.path.join(secret_dir(), "env")


def _read_env_file():
    out, path = {}, _env_file()
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def secret_index():
    """이름 → 저장소(keychain|file). 값은 들어 있지 않다."""
    return load_json(os.path.join(secret_dir(), "secrets.json"), {})


def _security():
    return os.environ.get("OPERATOR_SECURITY_BIN") or shutil.which("security")


def _keychain_file():
    kc = os.environ.get("OPERATOR_KEYCHAIN")
    return [kc] if kc else []


def keychain_get(name):
    b = _security()
    if not b:
        return None
    r = subprocess.run([b, "find-generic-password", "-s", "operator", "-a", name, "-w", *_keychain_file()], capture_output=True, text=True)
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def keychain_set(name, value):
    """값을 명령줄 인자로 넘기지 않으려고 `security -i` 의 표준 입력으로 보낸다. -T "" 는 어떤 프로그램도
    묻지 않고 읽지 못하게 한다: 읽을 때마다 macOS 가 사용자에게 허락을 묻는다."""
    b = _security()
    if not b:
        raise OSError("security 명령이 없다 (macOS 키체인 전용)")
    q = lambda v: '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    line = f'add-generic-password -U -s operator -a {name} -T "" -w {q(value)}' + "".join(" " + q(k) for k in _keychain_file()) + "\n"
    r = subprocess.run([b, "-i"], input=line, capture_output=True, text=True)
    if r.returncode != 0 or "error" in (r.stderr or "").lower():
        raise OSError("키체인 저장 실패: " + (r.stderr or "").strip()[:200])


def keychain_rm(name):
    b = _security()
    if b:
        subprocess.run([b, "delete-generic-password", "-s", "operator", "-a", name, *_keychain_file()], capture_output=True, text=True)


def _write_env_file(values):
    os.makedirs(secret_dir(), mode=0o700, exist_ok=True)
    path = _env_file()
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# operator 발송 토큰. 사람만 읽는다. 권한 600.\n" + "".join(f"{k}={v}\n" for k, v in sorted(values.items())))
    os.replace(tmp, path)


def set_secret(name, value, backend=None):
    idx = secret_index()
    backend = backend or idx.get(name) or os.environ.get("OPERATOR_SECRET_BACKEND") or ("keychain" if sys.platform == "darwin" and _security() else "file")
    if backend == "keychain":
        keychain_set(name, value)
        vals = _read_env_file()
        if name in vals:  # 같은 이름이 파일에도 있으면 파일 쪽을 지운다
            vals.pop(name)
            _write_env_file(vals)
    else:
        vals = _read_env_file()
        vals[name] = value
        _write_env_file(vals)
    idx[name] = backend
    os.makedirs(secret_dir(), mode=0o700, exist_ok=True)
    save_json(os.path.join(secret_dir(), "secrets.json"), idx)
    return backend


def channel_env(read_keychain=True, names=None):
    """환경 변수 → ~/.config/operator/env → 키체인 순서로 채운다. 키체인 읽기는 macOS 가 허락을 물을 수 있어서
    사람이 띄운 프로세스에서만 부른다. names 를 주면 그 이름만 키체인에서 읽는다."""
    env = dict(os.environ)
    for k, v in _read_env_file().items():
        env.setdefault(k, v)
    if read_keychain:
        for name, backend in secret_index().items():
            if backend == "keychain" and not env.get(name) and (names is None or name in names):
                v = keychain_get(name)
                if v:
                    env[name] = v
    return env


def secret_present(name, env):
    return bool(env.get(name)) or secret_index().get(name) == "keychain"


def ticket_secret_names(meta):
    """이 티켓을 보내는 데 필요한 비밀값 이름만 (키체인 허락 창을 줄이려고)."""
    ch = ticket_channel(meta)
    names = list(CHANNELS[ch]["env"]) if ch else []
    if ch == "x":
        names += ["X_REFRESH_TOKEN", "X_CLIENT_ID", "X_CLIENT_SECRET"]
    if ch == "email":
        names.append("SMTP_PORT")
    return names


def secret_store(name, value, authority, backend=None):
    """사람이 준 비밀값을 저장한다. 값은 어디에도 출력하지 않는다. 저장소 이름(keychain|file)을 돌려준다."""
    if not isinstance(authority, Authority):
        raise OpError("비밀값 등록: 사람의 결정이 필요하다.", 7)
    if name not in secret_names():
        raise OpError(f"모르는 비밀값 이름: {name} ({', '.join(secret_names())})", 1)
    if not value:
        raise OpError("값이 비어 있다.", 1)
    return set_secret(name, value, backend)


def secret_remove(name, authority):
    if not isinstance(authority, Authority):
        raise OpError("비밀값 삭제: 사람의 결정이 필요하다.", 7)
    idx = secret_index()
    if idx.get(name) == "keychain":
        keychain_rm(name)
    vals = _read_env_file()
    vals.pop(name, None)
    _write_env_file(vals)
    idx.pop(name, None)
    save_json(os.path.join(secret_dir(), "secrets.json"), idx)


def cmd_secret(args):
    sub, rest = (args[0], args[1:]) if args else ("list", [])
    opts = kv(rest)
    if sub == "list":
        env, idx = channel_env(read_keychain=False), secret_index()
        print(f"비밀값 저장 위치: {secret_dir()} (값은 출력하지 않는다)")
        for n in secret_names():
            where = idx.get(n) or ("환경 변수" if os.environ.get(n) else ("file" if _read_env_file().get(n) else None))
            print(f"  {n:22s} {where or '-'}")
        return
    if sub in ("set", "rm"):
        auth = terminal_authority(op_dir(required=False), "비밀값 등록·삭제")
        name = (opts.get("_") or [None])[0]
        if name not in secret_names():
            die(f"op secret {sub} <이름>   이름: {', '.join(secret_names())}")
        if sub == "rm":
            secret_remove(name, auth)
            print(f"{name} 삭제")
            return
        if os.environ.get("OPERATOR_SECRET_VALUE") is not None:
            value = os.environ["OPERATOR_SECRET_VALUE"]   # 테스트·설치 스크립트용. 사람 확인(터미널)은 위에서 이미 했다
        else:
            import getpass
            value = getpass.getpass(f"{name} 값 (화면에 보이지 않음): ").strip()
        if not value:
            die("값이 비어 있다.")
        backend = "file" if opts.get("file") else ("keychain" if opts.get("keychain") else None)
        try:
            where = secret_store(name, value, auth, backend)
        except OSError as e:
            die(str(e))
        print(f"{name} 저장 → {where}" + ("  (읽을 때 macOS 가 허락을 묻는다. '항상 허용'은 누르지 않는다)" if where == "keychain" else f"  ({_env_file()}, 권한 600)"))
        return
    die("op secret list | set <이름> [--file|--keychain] | rm <이름>")


def _http(method, url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            return resp.status, text
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def ticket_channel(meta):
    t = meta.get("type")
    if t == "email":
        return "email"
    ch = (meta.get("channel") or "").lower()
    return ch if ch in CHANNELS else None


def deliver_ticket(meta, body, env, dry_run=False):
    """(ok, 요약). 요약에는 토큰을 넣지 않는다."""
    ch = ticket_channel(meta)
    if not ch:
        return False, f"지원하지 않는 채널: type={meta.get('type')} channel={meta.get('channel')}"
    missing = [k for k in CHANNELS[ch]["env"] if not env.get(k)]
    if missing:
        return False, f"{ch}: 환경 변수 없음 {missing} ({CHANNELS[ch]['doc']})"
    text = body.strip()
    if dry_run:
        return True, f"[dry-run] {ch} 로 보낼 내용 {len(text)}자" + (f", 받는 사람 {meta.get('to')}" if ch == "email" else "")
    if ch == "x":
        post = lambda: _http("POST", _x_api(env) + "/2/tweets", json.dumps({"text": text}).encode(),
                             {"Authorization": "Bearer " + env["X_USER_ACCESS_TOKEN"], "Content-Type": "application/json"})
        status, resp = post()
        if status == 401:   # 사용자 토큰은 2시간쯤이면 만료된다 → 갱신 토큰으로 한 번 새로 받고 다시 시도
            new, note = refresh_x(env)
            print(note, flush=True)
            if not new:
                return False, note
            env = {**env, **new}
            status, resp = post()
        if status in (200, 201):
            tid = (json.loads(resp).get("data") or {}).get("id", "")
            return True, f"x 게시 완료 id={tid}"
        return False, f"x 실패 HTTP {status}: {resp[:200]}"
    if ch == "threads":
        base = env.get("OPERATOR_THREADS_API", "https://graph.threads.net") + "/v1.0/" + env["THREADS_USER_ID"]
        tok = env["THREADS_ACCESS_TOKEN"]
        status, resp = _http("POST", base + "/threads", urlencode({"media_type": "TEXT", "text": text, "access_token": tok}).encode(),
                             {"Content-Type": "application/x-www-form-urlencoded"})
        if status != 200:
            return False, f"threads 컨테이너 실패 HTTP {status}: {resp[:200]}"
        cid = json.loads(resp).get("id")
        status, resp = _http("POST", base + "/threads_publish", urlencode({"creation_id": cid, "access_token": tok}).encode(),
                             {"Content-Type": "application/x-www-form-urlencoded"})
        if status == 200:
            return True, f"threads 게시 완료 id={json.loads(resp).get('id', '')}"
        return False, f"threads 게시 실패 HTTP {status}: {resp[:200]}"
    if ch == "email":
        if not meta.get("to") or not meta.get("subject"):
            return False, "email: to/subject 헤더가 없다"
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = env["SMTP_FROM"], meta["to"], meta["subject"]
        msg.set_content(text)
        port = int(env.get("SMTP_PORT") or 587)
        try:
            if port == 465:
                srv = smtplib.SMTP_SSL(env["SMTP_HOST"], port, context=ssl.create_default_context(), timeout=30)
            else:
                srv = smtplib.SMTP(env["SMTP_HOST"], port, timeout=30)
                srv.starttls(context=ssl.create_default_context())
            with srv:
                srv.login(env["SMTP_USER"], env["SMTP_PASSWORD"])
                srv.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            return False, f"email 실패: {e.__class__.__name__}"
        return True, f"email 발송 완료 → {meta['to']}"
    if ch == "webhook":
        status, resp = _http("POST", env["OPERATOR_WEBHOOK_URL"], json.dumps({"text": text, "content": text}).encode(),
                             {"Content-Type": "application/json"})
        return (200 <= status < 300), f"webhook HTTP {status}"
    return False, "알 수 없는 채널"


def cmd_deliver(args):
    """op send 가 승인된 action 으로만 부른다. 직접 실행은 가드가 막고, 여기서도 send 가 넘긴 표시를 확인한다."""
    opts = kv(args)
    od = op_dir()
    if opts.get("check"):
        env = channel_env(read_keychain=False)
        for ch, spec in CHANNELS.items():
            missing = [k for k in spec["env"] if not secret_present(k, env)]
            print(f"  {ch:8s} {'준비됨' if not missing else '없음: ' + ', '.join(missing)}   ({spec['doc']})")
        return
    ids = opts.get("_") or []
    if len(ids) != 1:
        die("op deliver <id>   (op send 가 승인된 action 으로 실행)   |   op deliver --check")
    item_id = ids[0]
    if os.environ.get("OPERATOR_SEND_TICKET") != item_id:
        die("op deliver 는 `op send <id>` 를 통해서만 실행된다.", 6)
    _, p = find_item(od, item_id, ("approved",))
    if not p:
        die(f"{item_id} 는 approved 상태가 아니다.", 5)
    with open(p, encoding="utf-8") as f:
        body, meta = parse_front_matter(f.read())
    ok, summary = deliver_ticket(meta, body, channel_env(names=ticket_secret_names(meta)), dry_run=bool(opts.get("dry-run")))
    print(summary)
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- X OAuth 2.0 (연결과 자동 갱신)
def _x_api(env):
    return env.get("OPERATOR_X_API", "https://api.x.com").rstrip("/")


def _x_token_request(env, params):
    import base64
    cid = env.get("X_CLIENT_ID")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    params = dict(params, client_id=cid)
    if env.get("X_CLIENT_SECRET"):   # 기밀 클라이언트(웹 앱)는 Basic 인증
        headers["Authorization"] = "Basic " + base64.b64encode(f"{cid}:{env['X_CLIENT_SECRET']}".encode()).decode()
    status, resp = _http("POST", _x_api(env) + "/2/oauth2/token", urlencode(params).encode(), headers)
    try:
        data = json.loads(resp)
    except ValueError:
        data = {}
    return status, data


def store_tokens(new):
    """새 토큰을 저장소에 쓰고, 부모(사람이 띄운 프로세스)가 있으면 넘겨준다. 값은 출력하지 않는다."""
    for k, v in new.items():
        try:
            set_secret(k, v)
        except OSError as e:
            sys.stderr.write(f"op: {k} 저장 실패 ({e}). 다음 실행에서 다시 연결이 필요할 수 있다.\n")
    handoff = os.environ.get("OPERATOR_TOKEN_HANDOFF")
    if handoff:
        fd = os.open(handoff, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(new, f)


def refresh_x(env):
    """X 사용자 토큰을 갱신 토큰으로 새로 받는다. (새 env 일부 | None, 메시지)."""
    if not env.get("X_REFRESH_TOKEN") or not env.get("X_CLIENT_ID"):
        return None, "x: 토큰이 만료됐고 X_REFRESH_TOKEN/X_CLIENT_ID 가 없어 갱신할 수 없다. 사람이 `op connect x` 로 다시 연결한다."
    status, data = _x_token_request(env, {"grant_type": "refresh_token", "refresh_token": env["X_REFRESH_TOKEN"]})
    if status != 200 or not data.get("access_token"):
        return None, f"x: 토큰 갱신 실패 HTTP {status} ({data.get('error', '')}). 사람이 `op connect x` 로 다시 연결한다."
    new = {"X_USER_ACCESS_TOKEN": data["access_token"]}
    if data.get("refresh_token"):
        new["X_REFRESH_TOKEN"] = data["refresh_token"]   # X 는 갱신 토큰을 매번 바꾼다
    store_tokens(new)
    return new, "x: 토큰 갱신됨"


def cmd_connect(args):
    """op connect x — 브라우저로 X 에 로그인해 게시 권한 토큰을 받는다 (OAuth 2.0 PKCE). 사람만."""
    import base64
    import hashlib
    opts = kv(args)
    if (opts.get("_") or [None])[0] != "x":
        die("op connect x [--port 8766] [--no-browser]")
    terminal_authority(op_dir(required=False), "계정 연결")
    env = channel_env(names=["X_CLIENT_ID", "X_CLIENT_SECRET"])
    if not env.get("X_CLIENT_ID"):
        die("먼저 X 개발자 포털에서 앱을 만들고 OAuth 2.0 Client ID 를 `op secret set X_CLIENT_ID` 로 등록한다. "
            "앱의 Callback URI 는 http://127.0.0.1:8766/callback")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got = {}

    class CB(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = parse_qs(urlsplit(self.path).query)
            if urlsplit(self.path).path != "/callback" or (q.get("state") or [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            got["code"], got["error"] = (q.get("code") or [""])[0], (q.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p>operator: 연결 처리 중. 이 창은 닫아도 된다.</p>".encode())

    from http.server import HTTPServer
    srv = HTTPServer(("127.0.0.1", int(opts.get("port") or 8766)), CB)
    redirect = f"http://127.0.0.1:{srv.server_address[1]}/callback"
    url = env.get("OPERATOR_X_AUTHORIZE", "https://x.com/i/oauth2/authorize") + "?" + urlencode({
        "response_type": "code", "client_id": env["X_CLIENT_ID"], "redirect_uri": redirect,
        "scope": "tweet.read tweet.write users.read offline.access", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print(f"브라우저에서 X 에 로그인하고 허용한다:\n{url}", flush=True)
    if not opts.get("no-browser"):
        import webbrowser
        webbrowser.open(url)
    srv.timeout = 1
    deadline = datetime.now().timestamp() + float(opts.get("timeout") or 300)
    while "code" not in got and datetime.now().timestamp() < deadline:
        srv.handle_request()
    srv.server_close()
    if not got.get("code"):
        die(f"연결되지 않았다 ({got.get('error') or '시간 초과'}).")
    status, data = _x_token_request(env, {"grant_type": "authorization_code", "code": got["code"],
                                          "redirect_uri": redirect, "code_verifier": verifier})
    if status != 200 or not data.get("access_token"):
        die(f"토큰 교환 실패 HTTP {status} ({data.get('error', '')})")
    new = {"X_USER_ACCESS_TOKEN": data["access_token"]}
    if data.get("refresh_token"):
        new["X_REFRESH_TOKEN"] = data["refresh_token"]
    store_tokens(new)
    print("X 연결 완료. 토큰을 저장했다 (값은 출력하지 않는다)." + ("" if data.get("refresh_token") else " 갱신 토큰이 없다: scope 에 offline.access 가 있는지 확인."))


# ---------------------------------------------------------------- telegram (밖에서 휴대폰으로 승인)
def cmd_telegram(args):
    """텔레그램 봇으로 승인 대기를 보내고, 버튼이나 /approve, /reject 로 결정한다. 봇이 텔레그램 서버에 먼저
    연결해 메시지를 가져오므로 컴퓨터에 포트를 열지 않는다. 정해진 대화방(TELEGRAM_CHAT_ID) 말고는 무시한다."""
    opts = kv(args)
    od = op_dir()
    terminal_authority(od, "op telegram")
    env = channel_env()
    tok = env.get("TELEGRAM_BOT_TOKEN")
    if not tok:
        die("먼저 @BotFather 로 봇을 만들고 `op secret set TELEGRAM_BOT_TOKEN` 으로 등록한다.")
    api = env.get("OPERATOR_TELEGRAM_API", "https://api.telegram.org").rstrip("/") + "/bot" + tok + "/"

    def call(method, http_timeout=40, **params):
        params = {k: v for k, v in params.items() if v is not None}
        try:
            status, resp = _http("POST", api + method, json.dumps(params, ensure_ascii=False).encode(),
                                 {"Content-Type": "application/json"}, timeout=http_timeout)
            data = json.loads(resp)
        except (OSError, ValueError):
            return {"ok": False}
        return data if status == 200 else {"ok": False}

    if opts.get("setup"):
        print("봇에게 아무 메시지나 보낸 뒤 이 명령을 실행하면 대화방 번호가 보인다.")
        for u in call("getUpdates", http_timeout=10).get("result", []):
            chat = (u.get("message") or {}).get("chat") or {}
            if chat:
                print(f"  TELEGRAM_CHAT_ID 후보: {chat.get('id')}  ({chat.get('type')}, {chat.get('username') or chat.get('title') or ''})")
        print("개인 대화방(private) 번호를 `op secret set TELEGRAM_CHAT_ID` 로 등록한다. 그룹은 쓰지 않는다.")
        return
    chat = str(env.get("TELEGRAM_CHAT_ID") or "")
    if not chat:
        die("TELEGRAM_CHAT_ID 가 없다. `op telegram --setup` 으로 번호를 확인해 등록한다.")
    human_send = send_mode_of(od) == "human"
    loaded = env if human_send else None
    titles_only = bool(opts.get("titles-only"))
    project = config(od).get("project") or os.path.basename(os.path.dirname(od))
    say = lambda text, **kw: call("sendMessage", chat_id=chat, text=text[:4000], **kw)

    def decide(item_id, d, reason=None):
        try:
            res = pending_decide(od, item_id, d, Authority("terminal", f"telegram:{chat}"), note=reason, secrets_env=loaded)
        except OpError as e:
            return say(f"{item_id}: {e.msg}")
        meta = res["meta"]
        msg = f"{item_id} → {meta['status']}"
        if res["sent"] is not None:
            code, out = res["sent"]
            msg += f"\n발송 {'완료' if code == 0 else '실패'}: {out}"
        print(f"[telegram] {msg}", flush=True)
        say(msg)

    announced, awaiting, offset = set(), None, None
    print(f"텔레그램 승인 시작 ({project}). Ctrl+C 로 종료.", flush=True)
    try:
        while True:
            for f in sorted(os.listdir(os.path.join(od, "pending"))):
                if not f.endswith(".md") or f[:4] in announced:
                    continue
                body, meta = parse_front_matter(open(os.path.join(od, "pending", f), encoding="utf-8").read())
                iid, act = meta.get("id", f[:4]), (meta.get("action") or "").strip()
                head = f"[{project}] {iid} · {meta.get('type', '')}" + (f"/{meta['channel']}" if meta.get("channel") else "") \
                       + (f" → {meta['to']}" if meta.get("to") else "") + f"\n{meta.get('title', '')}"
                text = head + ("" if titles_only else "\n\n" + body.strip()[:3000]) + f"\n\n실행될 명령: {act or '없음 (승인해도 보낼 수 없다)'}"
                buttons = ([{"text": "승인", "callback_data": f"a:{iid}"}] if act else []) + [{"text": "거절", "callback_data": f"r:{iid}"}]
                say(text, reply_markup={"inline_keyboard": [buttons]})
                announced.add(iid)
            upd = call("getUpdates", http_timeout=10 if opts.get("once") else 40, offset=offset,
                       allowed_updates=["message", "callback_query"], timeout=0 if opts.get("once") else 25)
            for u in upd.get("result", []):
                offset = u["update_id"] + 1
                cq = u.get("callback_query")
                if cq:
                    cchat = str(((cq.get("message") or {}).get("chat") or {}).get("id"))
                    if cchat != chat:
                        call("answerCallbackQuery", callback_query_id=cq.get("id"), text="이 대화방은 승인 권한이 없다.")
                        continue
                    call("answerCallbackQuery", callback_query_id=cq.get("id"))
                    mid = (cq.get("message") or {}).get("message_id")
                    if mid:
                        call("editMessageReplyMarkup", chat_id=chat, message_id=mid, reply_markup={"inline_keyboard": []})
                    kind, _, iid = (cq.get("data") or "").partition(":")
                    if not re.fullmatch(r"\d{4}", iid):
                        continue
                    if kind == "a":
                        decide(iid, "approve")
                    elif kind == "r":
                        awaiting = iid
                        say(f"{iid} 거절 사유를 보내 주세요. 다음 초안에 반영됩니다. 사유 없이 거절: /skip")
                    continue
                m = u.get("message") or {}
                if str((m.get("chat") or {}).get("id")) != chat:
                    continue
                text = (m.get("text") or "").strip()
                if awaiting and (text == "/skip" or not text.startswith("/")):
                    decide(awaiting, "reject", None if text == "/skip" else text)
                    awaiting = None
                elif re.match(r"^/approve\s+\d{4}$", text):
                    decide(text.split()[1], "approve")
                elif re.match(r"^/reject\s+\d{4}\b", text):
                    parts = text.split(None, 2)
                    decide(parts[1], "reject", parts[2] if len(parts) > 2 else None)
                elif text in ("/list", "/start"):
                    pend = sorted(f for f in os.listdir(os.path.join(od, "pending")) if f.endswith(".md"))
                    say(f"[{project}] 승인 대기 {len(pend)}건\n" + "\n".join(pend[:30]))
                    announced.difference_update(p[:4] for p in pend)   # 다시 카드로 보낸다
            if opts.get("once"):
                break
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------- serve / notify (휴대폰에서 승인)
def cmd_notify(args):
    """승인 대기 건수만 ntfy 로 알린다 (본문은 보내지 않음). OPERATOR_NTFY_TOPIC 이 없으면 조용히 넘어간다."""
    od = op_dir()
    env = channel_env(read_keychain=False)   # 에이전트도 부르는 명령이라 키체인은 읽지 않는다 (토픽은 --file 로 저장)
    topic = env.get("OPERATOR_NTFY_TOPIC")
    n = len([f for f in os.listdir(os.path.join(od, "pending")) if f.endswith(".md")])
    if not topic:
        print(f"승인 대기 {n}건 (OPERATOR_NTFY_TOPIC 이 없어 알림은 보내지 않음)")
        return
    server = env.get("OPERATOR_NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    project = config(od).get("project") or os.path.basename(os.path.dirname(od))
    status, _ = _http("POST", f"{server}/{topic}", f"{project}: 승인 대기 {n}건".encode("utf-8"),
                      {"Title": "operator", "Tags": "inbox_tray"}, timeout=10)
    print(f"알림 {'보냄' if 200 <= status < 300 else '실패 HTTP ' + str(status)}: 승인 대기 {n}건")


def _page(title, inner):
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>body{{font:16px/1.5 -apple-system,system-ui,sans-serif;margin:0 auto;max-width:640px;padding:16px;background:#faf7f2;color:#222}}"
            "article{background:#fff;border:1px solid #e5ded3;border-radius:12px;padding:14px;margin:12px 0}pre{white-space:pre-wrap;word-break:break-word;background:#f4efe7;padding:10px;border-radius:8px}"
            "button{font-size:16px;padding:10px 16px;border-radius:8px;border:0;margin-right:8px}.ok{background:#2f7d4f;color:#fff}.no{background:#b34422;color:#fff}"
            "input{font-size:16px;padding:8px;width:100%;box-sizing:border-box;margin:6px 0}small{color:#777}</style>"
            f"<h1>{html.escape(title)}</h1>{inner}")


def cmd_serve(args):
    """승인 대기 목록을 웹 페이지로 보여 주고 사람이 승인·거절한다. 대화형 터미널에서만 시작되고,
    주소에 들어 있는 1회용 토큰이 있어야 접근된다. 에이전트는 이 명령을 실행할 수 없다."""
    opts = kv(args)
    od = op_dir()
    terminal_authority(od, "op serve")
    token = secrets.token_urlsafe(24)
    human_send = send_mode_of(od) == "human"
    loaded = channel_env() if human_send else None   # 키체인 허락은 시작할 때 한 번 (사람이 컴퓨터 앞에 있을 때)
    host = "0.0.0.0" if opts.get("lan") else "127.0.0.1"
    port = int(opts.get("port") or 8765)

    def items():
        out = []
        for f in sorted(os.listdir(os.path.join(od, "pending"))):
            if f.endswith(".md"):
                body, meta = parse_front_matter(open(os.path.join(od, "pending", f), encoding="utf-8").read())
                out.append((meta, body))
        return out

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, text):
            data = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self, given):
            return isinstance(given, str) and secrets.compare_digest(given, token)

        def do_GET(self):
            q = parse_qs(urlsplit(self.path).query)
            if not self._authorized((q.get("t") or [""])[0]):
                return self._send(403, _page("operator", "<p>주소의 토큰이 맞지 않는다.</p>"))
            cards = []
            for meta, body in items():
                i = html.escape(meta.get("id", ""))
                act = (meta.get("action") or "").strip()
                cards.append(
                    f"<article><b>{i} · {html.escape(meta.get('type', ''))}"
                    + (f" / {html.escape(meta['channel'])}" if meta.get("channel") else "")
                    + (f" → {html.escape(meta['to'])}" if meta.get("to") else "")
                    + f"</b><div>{html.escape(meta.get('title', ''))}</div><pre>{html.escape(body.strip())}</pre>"
                    + f"<small>실행될 명령: {html.escape(act) if act else '없음 (승인해도 보낼 수 없음, 터미널에서 --action 지정)'}</small>"
                    + f"<form method=post action='/decide'><input type=hidden name=t value='{html.escape(token)}'><input type=hidden name=id value='{i}'>"
                    + "<input name=reason placeholder='거절 사유 (거절 시)'>"
                    + ("<button class=ok name=d value=approve>승인</button>" if act else "")
                    + "<button class=no name=d value=reject>거절</button></form></article>")
            self._send(200, _page(f"승인 대기 {len(cards)}건", "".join(cards) or "<p>대기 중인 항목이 없다.</p>"))

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 20000:
                return self._send(413, _page("operator", "<p>요청이 너무 크다.</p>"))
            form = parse_qs(self.rfile.read(n).decode("utf-8"))
            get = lambda k: (form.get(k) or [""])[0]
            if not self._authorized(get("t")):
                return self._send(403, _page("operator", "<p>토큰이 맞지 않는다.</p>"))
            d, item_id = get("d"), get("id")
            if d not in ("approve", "reject") or not re.fullmatch(r"\d{4}", item_id):
                return self._send(400, _page("operator", "<p>잘못된 요청</p>"))
            try:
                with send_lock:
                    res = pending_decide(od, item_id, d, Authority("terminal", "serve"), note=get("reason") or None, secrets_env=loaded)
                msg = f"{item_id} → {res['meta']['status']}"
                if res["sent"] is not None:
                    code, out = res["sent"]
                    msg += f" · 발송 {'완료' if code == 0 else '실패'} ({out})"
            except OpError as e:
                msg = e.msg
            print(f"[serve] {msg}", flush=True)
            back = f"/?t={token}"
            self._send(200, _page("operator", f"<p>{html.escape(msg)}</p><p><a href='{html.escape(back)}'>목록으로</a></p>"))

    import threading
    send_lock = threading.Lock()
    srv = ThreadingHTTPServer((host, port), Handler)
    port = srv.server_address[1]
    shown = "127.0.0.1" if host == "127.0.0.1" else _lan_ip()
    print(f"승인 페이지: http://{shown}:{port}/?t={token}", flush=True)
    if host != "127.0.0.1":
        print("같은 Wi-Fi 의 휴대폰에서 위 주소를 연다. HTTPS 가 아니므로 공용 네트워크에서는 쓰지 마라.")
    print("Ctrl+C 로 종료. 토큰은 이 실행에서만 유효하다.", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def _lan_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------- send (승인된 티켓으로만 밖으로)
def run_action(od, item_id, given=None, secrets_env=None):
    """approved 티켓에 기록된 action 을 그대로 실행하고 sent 로 옮긴다. (exit code, 메시지).
    secrets_env 는 사람이 띄운 프로세스가 미리 읽어 둔 토큰. `op deliver` 일 때만 자식에게 넘긴다."""
    root = os.path.dirname(od)
    _, p = find_item(od, item_id, ("approved",))
    if not p:
        s2, _ = find_item(od, item_id)
        return 5, f"{item_id} 는 approved 상태가 아니다 (현재: {s2 or '없음'}). 사람이 승인한 티켓으로만 보낼 수 있다."
    with open(p, encoding="utf-8") as f:
        body, meta = parse_front_matter(f.read())
    action = (meta.get("action") or "").strip()
    if not action:
        return 6, (f"{item_id} 에는 승인된 실행 명령(action)이 없다. 사람이 `op pending approve {item_id} --action \"<명령>\"` "
                   "으로 명령까지 승인해야 보낼 수 있다.")
    if given is not None and " ".join(given.split()) != " ".join(action.split()):
        return 6, f"보내려는 명령이 승인된 action 과 다르다.\n  승인: {action}\n  요청: {given}\n명령을 바꾸려면 새 티켓을 올려 다시 승인받아라."
    if re.search(r"\bop(?:\.py)?\s+(?:pending|send|serve|telegram|stage|secret|connect)\b", action):
        return 6, "action 안에서 op 의 큐·단계·비밀값 명령을 실행할 수 없다."
    print(f"[send {item_id}] {action}", flush=True)
    child_env = {**os.environ, "OPERATOR_SEND_TICKET": item_id}
    own = re.match(r"^\s*op(?:\.py)?\s+(.*)$", action)
    if own:
        handoff = None
        if secrets_env and re.match(r"deliver\b", own.group(1)):
            child_env.update({k: v for k, v in secrets_env.items() if k in secret_names() and v})
            os.makedirs(secret_dir(), mode=0o700, exist_ok=True)
            handoff = child_env["OPERATOR_TOKEN_HANDOFF"] = os.path.join(secret_dir(), f".handoff-{os.getpid()}-{item_id}")
        # `op …` 는 PATH·별칭과 상관없이 이 스크립트 자신으로 실행한다 (셸 별칭은 하위 셸에 없다).
        r = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), *shlex.split(own.group(1))], cwd=root, env=child_env)
        if handoff and os.path.exists(handoff):   # 자식이 토큰을 갱신했으면 이 프로세스가 들고 있는 값도 바꾼다
            try:
                secrets_env.update(load_json(handoff, {}))
            finally:
                os.remove(handoff)
    else:
        r = subprocess.run(action, shell=True, cwd=root, env=child_env)
    meta.update(executed=now(), command=action, exit=str(r.returncode))
    if r.returncode == 0:
        meta["status"] = "sent"
        dst = os.path.join(od, "sent", os.path.basename(p))
        os.remove(p)
    else:
        dst = p
    with open(dst, "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---\n\n" + body)
    return r.returncode, f"exit {r.returncode} → {'sent' if r.returncode == 0 else 'approved 유지 (실패, 다시 시도 가능)'}"


def cmd_send(args):
    if "--" not in args:
        args = args + ["--"]
    if args.index("--") == 0:
        die("op send <id> [-- <승인된 action 과 같은 명령>]")
    i = args.index("--")
    head, cmdv = args[:i], args[i + 1:]
    od = op_dir()
    if send_mode_of(od) == "human" and not (sys.stdin.isatty() and sys.stdout.isatty() and "terminal" in human_via(od)):
        die("이 프로젝트는 사람이 승인하는 순간 사람 쪽에서 보낸다 (guard.json send_mode: human). 에이전트는 보내지 않는다. "
            "사용자에게 `op pending approve <id>` 를 요청해라. 이미 승인됐는데 실패했다면 사람이 자기 터미널에서 `op send <id>`.", 6)
    given = None
    if cmdv:
        given = " ".join(cmdv) if "--shell" in head else shlex.join(cmdv)
    secrets_env = None
    if send_mode_of(od) == "human":
        _, tp = find_item(od, head[0], ("approved",))
        meta = parse_front_matter(open(tp, encoding="utf-8").read())[1] if tp else {}
        secrets_env = channel_env(names=ticket_secret_names(meta))
    code, msg = run_action(od, head[0], given, secrets_env)
    if msg.startswith("exit"):
        print(msg)
    else:
        sys.stderr.write(f"op: {msg}\n")
    sys.exit(code)


# ---------------------------------------------------------------- guard (승인 게이트 훅)
def extract_from_hook_input(data):
    """여러 에이전트의 훅 입력에서 (명령문자열, [파일경로]) 를 뽑는다."""
    ti = data.get("tool_input") or data.get("toolInput") or data.get("input") or {}
    if not isinstance(ti, dict):
        ti = {}
    cmd = ti.get("command") or data.get("command") or ti.get("cmd") or ti.get("code") or ""   # code: Hermes execute_code
    if isinstance(cmd, list):  # Codex shell: ["bash","-lc","..."]
        parts = [str(c) for c in cmd]
        # The script is the argument after -c/-lc; joining everything would lose its quoting.
        cmd = parts[-1] if len(parts) >= 3 and parts[-2] in ("-c", "-lc", "/c", "/C", "-Command") else " ".join(parts)
    paths = []
    for k in ("file_path", "path", "filePath", "notebook_path"):
        v = ti.get(k) or data.get(k)
        if isinstance(v, str):
            paths.append(v)
    for k in ("patch", "input"):  # Codex apply_patch, Hermes patch (V4A 모드)
        v = ti.get(k)
        if isinstance(v, str):
            paths += re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", v, flags=re.M)
    return str(cmd), paths


# Hermes 셸 훅의 cwd 는 세션 폴더가 아니라 게이트웨이 프로세스의 폴더다. 세션 폴더를 모르는 호출은
# 등록된 operator 프로젝트 전부의 규칙으로 판단한다 (모르면 막는 쪽). 목록은 ~/.config/operator/projects.json:
# 사람 쪽(플러그인 /idea, /setup use)만 쓰고, 에이전트는 그 폴더를 읽지도 쓰지도 못한다 (SECRET_COMMANDS, secret_dir).
def projects_path():
    return os.path.join(secret_dir(), "projects.json")


def known_projects():
    return [r for r in load_json(projects_path(), []) if isinstance(r, str) and os.path.isdir(os.path.join(r, OP_DIR_NAME))]


def register_project(root):
    root = os.path.abspath(root)
    roots = [r for r in load_json(projects_path(), []) if isinstance(r, str) and r != root] + [root]
    os.makedirs(secret_dir(), mode=0o700, exist_ok=True)
    save_json(projects_path(), roots)


# A session opened elsewhere can still act inside an operator project: `cd proj && wrangler deploy`,
# `git -C proj push`, or a Write to proj/.operator/pending/x. Find every operator project the call
# can touch, not only the one above the hook's working directory.
_CD = re.compile(r"""(?:^|[;&|(\n]|&&|\|\|)\s*(?:builtin\s+)?(?:cd|pushd|chdir|Set-Location|sl)\s+(?:/d\s+|-LiteralPath\s+|-Path\s+)?("[^"]*"|'[^']*'|[^\s;&|)]+)""", re.I)
_GIT_C = re.compile(r"""\bgit\s+(?:-c\s+\S+\s+)*-C\s+("[^"]*"|'[^']*'|\S+)""")
_DIR_OPTS = re.compile(r"""(?:--cwd|--prefix|--dir|--cd)(?:=|\s+)("[^"]*"|'[^']*'|[^\s;&|]+)""")
# 따옴표 안의 절대 경로 (파이썬 코드나 스크립트 안의 "cd /x && git push" 같은 것)
_QUOTED_ABS = re.compile(r"""["'](/[^"'\n]+)["']""")


def _unquote(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def command_dirs(cmd, base):
    """Directories a shell command changes into or points tools at, resolved against base."""
    dirs = []
    for pattern in (_CD, _GIT_C, _DIR_OPTS):
        for match in pattern.finditer(cmd or ""):
            raw = _unquote(match.group(1))
            if not raw or raw == "-" or "$" in raw or "%" in raw:
                continue
            raw = os.path.expanduser(raw)
            dirs.append(os.path.abspath(raw if os.path.isabs(raw) else os.path.join(base, raw)))
    for match in _QUOTED_ABS.finditer(cmd or ""):
        dirs.append(os.path.abspath(match.group(1)))
    # Each `cd` applies to what follows, so a later relative cd is relative to the earlier one.
    chained, cur = [], base
    for match in _CD.finditer(cmd or ""):
        raw = os.path.expanduser(_unquote(match.group(1)))
        if not raw or raw == "-" or "$" in raw or "%" in raw:
            continue
        cur = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(cur, raw))
        chained.append(cur)
    return list(dict.fromkeys(dirs + chained))


def operator_roots(base, cmd, paths):
    """Every .operator directory the call can affect: from the working directory, the command's cd/-C
    targets, and each file path's own folder (absolute or relative to the working directory)."""
    candidates = [base] + command_dirs(cmd, base)
    for p in paths:
        ap = p if os.path.isabs(p) else os.path.join(base, p)
        candidates.append(os.path.dirname(os.path.abspath(ap)))
    roots = []
    for d in candidates:
        root = find_root(d)
        if root and root not in roots:
            roots.append(root)
    return [os.path.join(r, OP_DIR_NAME) for r in roots]


# 큐 폴더를 읽기만 하는 명령. 이 밖의 명령이 큐 경로를 언급하면 쓰기로 간주해 막는다
# (mv/cp/echo >/sed -i/python 한 줄 등 어떤 형태든). `op ...` 자체는 이 검사에서 제외된다.
_READ_ONLY = re.compile(r"^\s*(?:cat|ls|ll|dir|head|tail|less|more|grep|rg|find|wc|stat|file|diff|jq|tree|bat|type|Get-Content|Get-ChildItem|Select-String)\b")
_QUEUE_DIRS = ("pending", "approved", "sent", "rejected", r"stage\.json", r"milestones\.json", r"metrics\.jsonl", r"guard\.json")


def touches_queue(cmd, od, base):
    """셸 명령이 이 프로젝트의 승인 큐 경로를 언급하면 그 상대 경로를 돌려준다."""
    if re.search(r"\bop(?:\.py)?\s+(?:pending|send|status|pass|verify|init|guard|llm|feedback|notify|stage|milestone|metric|secret)\b", cmd) and not re.search(r"[;&|]", cmd):
        return None  # op 명령 한 줄 — 큐 처리는 op 자신이 규칙대로 한다
    root = os.path.dirname(od)
    names = "|".join(_QUEUE_DIRS)
    for m in re.finditer(r"(?:^|[\s\"'=(])((?:[A-Za-z]:)?[^\s\"';|&<>()]*\.operator[\\/](?:%s)(?:[\\/][^\s\"';|&<>()]*)?)" % names, cmd):
        raw = os.path.expanduser(m.group(1))
        ap = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(base or root, raw))
        try:
            rel = os.path.relpath(ap, root)
        except ValueError:
            continue
        if not rel.startswith(".."):
            return rel
    # 큐 폴더 전체나 .operator 자체를 통째로 옮기거나 지우는 경우
    if re.search(r"\b(mv|rm|cp|rsync|rmdir|Move-Item|Remove-Item|Copy-Item)\b[^;&|]*\.operator(?:[\\/]?)(?:\s|$|[\"'])", cmd):
        return ".operator"
    return None


def guard_decide(cmd, paths, od, base=None):
    """(deny: bool, reason). Relative file paths are resolved against base (the hook's cwd)."""
    rules = guard_rules(od)
    root = os.path.dirname(od)
    queue_msg = ("은 op 만 바꾸는 영역이다 (승인 큐, 단계, 마일스톤, 지표, 가드 설정). 에이전트가 직접 쓸 수 없다. "
                 "초안은 `op pending add`, 마일스톤은 `op milestone`, 지표는 `op metric add` 로 남긴다.")
    secret_msg = ("비밀값(발송 토큰)은 사람이 띄운 프로세스만 읽는다. 에이전트는 토큰을 읽거나 옮기거나 출력하지 않는다. "
                  "채널 준비 상태는 `op deliver --check` 로 확인해라 (값은 나오지 않는다).")
    sdir = os.path.realpath(secret_dir())
    for p in paths:
        ap = os.path.abspath(os.path.join(base or root, p)) if not os.path.isabs(p) else p
        if os.path.realpath(ap) == sdir or os.path.realpath(ap).startswith(sdir + os.sep):
            return True, secret_msg
        rel = os.path.relpath(ap, root)
        for dp in rules["deny_paths"]:
            if rel.startswith(dp.rstrip("/")):
                return True, f"'{rel}' " + queue_msg
    if not cmd.strip():
        return False, ""
    touched = touches_queue(cmd, od, base)
    if touched and not _READ_ONLY.match(cmd):
        return True, f"'{touched}' " + queue_msg + " 셸로 옮기거나 덮어쓰는 것도 같은 규칙이다."
    for pat in SECRET_COMMANDS:
        if re.search(pat, cmd, flags=re.I):
            return True, secret_msg
    for pat in rules["human_only_commands"]:
        if re.search(pat, cmd):
            return True, ("이 명령은 사람만 실행한다 (승인·거절, 단계 이동, 비밀값 등록, 발송·승인 서버). "
                          "사용자에게 무엇을 왜 실행해야 하는지 설명하고, 자기 터미널에서 직접 실행해 달라고 요청해라. "
                          "승인 대기는 `op pending list`, 단계 검사는 `op stage check` 로 보여 줄 수 있다.")
    m = re.search(r"\bop(?:\.py)?\s+send\s+(\d{4})\b", cmd)
    if m:
        s, _ = find_item(od, m.group(1), ("approved",))
        if s:
            return False, ""
        return True, f"티켓 {m.group(1)} 은 approved 상태가 아니다. 사람의 승인 전에는 보낼 수 없다."
    for pat in rules.get("allow_commands", []):
        if re.search(pat, cmd):
            return False, ""
    for pat in rules["deny_commands"]:
        if re.search(pat, cmd, flags=re.I):
            return True, (f"이 명령은 밖으로 나가거나 되돌릴 수 없다 (규칙: {pat}). 직접 실행하지 말고 초안을 "
                          f"`op pending add <file> --type ... --action \"{cmd[:80]}\"` 로 승인 큐에 올려라. "
                          "사람이 approve 하면 `op send <id> -- <명령>` 으로 실행된다.")
    return False, ""


def cmd_guard(args):
    opts = kv(args)
    fmt = opts.get("format", "claude")
    if opts.get("_") and opts["_"][0] == "check":
        cmd = " ".join(opts["_"][1:])
        base = os.path.abspath(opts.get("cwd") or os.getcwd())
        roots = operator_roots(base, cmd, [])
        if not roots:
            print("ALLOW (no .operator here)")
            return
        for od in roots:
            deny, reason = guard_decide(cmd, [], od, base)
            if deny:
                print("DENY: " + reason)
                sys.exit(1)
        print("ALLOW")
        return
    try:
        data = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        data = {}
    # Claude Code and Codex pass the session's working directory as "cwd"; fall back to our own.
    base = data.get("cwd") if isinstance(data.get("cwd"), str) and os.path.isabs(data.get("cwd")) else os.getcwd()
    cmd, paths = extract_from_hook_input(data)
    sdir = os.path.realpath(secret_dir())
    for p in paths:   # 토큰 폴더는 어느 프로젝트에서 부르든 막는다
        rp = os.path.realpath(p if os.path.isabs(p) else os.path.join(base, p))
        if rp == sdir or rp.startswith(sdir + os.sep):
            return _guard_block(fmt, "비밀값(발송 토큰)과 operator 설정 폴더는 사람이 띄운 프로세스만 읽고 쓴다. "
                                     "채널 준비 상태는 `op deliver --check` 로 확인해라 (값은 나오지 않는다).")
    if fmt == "hermes":
        ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        workdir = ti.get("workdir")
        if isinstance(workdir, str) and os.path.isabs(workdir):
            base = workdir   # 터미널 도구가 폴더를 밝힌 호출만 세션 폴더를 안다
            roots = operator_roots(base, cmd, paths)
        else:
            roots = operator_roots(base, cmd, paths)
            roots += [os.path.join(r, OP_DIR_NAME) for r in known_projects() if os.path.join(r, OP_DIR_NAME) not in roots]
    else:
        roots = operator_roots(base, cmd, paths)
    if not roots:
        # 이 호출이 닿는 곳 어디에도 operator 가 활성화되지 않았다 → 간섭하지 않는다.
        if fmt == "cursor":
            print(json.dumps({"permission": "allow"}))
        return
    deny, reason = False, ""
    for od in roots:
        d, r = guard_decide(cmd, paths, od, base)
        try:
            with open(os.path.join(od, "guard.log"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": now(), "deny": d, "cmd": cmd[:200], "paths": paths, "cwd": base, "fmt": fmt}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        if d and not deny:
            deny, reason = True, r
    if not deny:
        if fmt == "cursor":
            print(json.dumps({"permission": "allow"}))
        return
    return _guard_block(fmt, reason)


def _guard_block(fmt, reason):
    msg = "[operator 승인 게이트] " + reason
    if fmt == "cursor":
        print(json.dumps({"permission": "deny", "user_message": msg, "agent_message": msg}, ensure_ascii=False))
        return
    if fmt == "gemini":
        print(json.dumps({"decision": "deny", "reason": msg}, ensure_ascii=False))
        return
    if fmt == "hermes":   # exit 2 + Hermes 지시 JSON. 메시지는 도구 결과로 모델에게 간다
        print(json.dumps({"action": "block", "message": msg}, ensure_ascii=False))
        sys.exit(2)
    # claude / codex: exit 2 + stderr → 도구 호출 차단, 메시지는 모델에게 전달
    sys.stderr.write(msg + "\n")
    sys.exit(2)


# ---------------------------------------------------------------- llm (모델 라우팅)
def cmd_llm(args):
    opts = kv(args)
    role = opts.get("role", "summarize")
    prompt = " ".join(opts.get("_") or [])
    if opts.get("input"):
        with open(opts["input"], encoding="utf-8") as f:
            prompt = (prompt + "\n\n" + f.read()).strip()
    if not prompt:
        die("op llm --role classify|summarize|tag|extract|draft [--input file] \"프롬프트\"")
    od = op_dir(required=False)
    cfg = config(od) if od else DEFAULT_CONFIG
    r = cfg["routing"]
    if role not in r["local_roles"]:
        print(f"ROUTE=self  ({role} 은 판단이 필요한 역할 → 로컬 모델에 맡기지 않는다. 네가 직접 해라.)")
        sys.exit(3)
    body = json.dumps({"model": r["local_model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}).encode()
    req = urllib.request.Request(r["local_endpoint"].rstrip("/") + "/chat/completions", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=r.get("timeout", 120)) as resp:
            out = json.load(resp)
        print(f"ROUTE=local:{r['local_model']}")
        print(out["choices"][0]["message"]["content"].strip())
    except Exception as e:
        print(f"ROUTE=self  (로컬 모델 연결 실패: {e.__class__.__name__}. 네가 직접 해라.)")
        sys.exit(3)


# ---------------------------------------------------------------- main
COMMANDS = {
    "init": cmd_init, "status": cmd_status, "pass": cmd_pass, "verify": cmd_verify,
    "pending": cmd_pending, "send": cmd_send, "guard": cmd_guard, "llm": cmd_llm,
    "deliver": cmd_deliver, "serve": cmd_serve, "notify": cmd_notify, "feedback": cmd_feedback,
    "stage": cmd_stage, "milestone": cmd_milestone, "metric": cmd_metric, "secret": cmd_secret,
    "telegram": cmd_telegram, "connect": cmd_connect,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "-h", "--help"):
        print(__doc__)
        print("""명령:
  init [--stage 단계] [--send human|agent]   .operator/ 작업 공간 생성 (새 프로젝트는 발견 단계, 사람이 발송)
  status                                 현재 상태 요약
  stage [show] | doc | check | history   지금 단계, 할 일, 넘어가기 조건
  stage advance | back --to 단계 --reason ... | set 단계     (사람만, 대화형 터미널)
  milestone add "제목" --test "검사 명령" | list | done <n> | reopen <n>   만들기 단계
  metric add <이름> <값> [--source ..] | list                배우기 단계의 입력
  pass start --goal "..." [--max-steps N] [--steps a,b,c]
  pass next | done <step> [--output P] | fail <step> --reason "..." | end | show
  verify <file> --type post|email|research|site|other [--channel x]
  pending add <file> --type ... [--channel x] [--title ...] [--action "명령"]
  pending list [--status pending|approved|sent|rejected] | show <id>
  pending approve <id> [--action "명령"] [--note ...] | reject <id> --reason ...   (사람만, 대화형 터미널)
  send <id> [-- <명령>]                   승인된 action 그대로 실행 (명령을 주면 action 과 같아야 함)
  guard [--format claude|codex|cursor|gemini|hermes]   (훅: stdin 으로 JSON)
  guard check [--cwd DIR] "<command>"     이 명령이 막히는지 확인
  llm --role classify|summarize|tag|extract [--input f] "프롬프트"
  deliver --check                         채널(x/threads/email/webhook) 토큰 준비 상태 (값은 출력 안 함)
  deliver <id>                            op send 가 승인된 action 으로만 실행 (직접 실행 불가)
  serve [--lan] [--port 8765]             휴대폰·브라우저 승인 페이지 (사람만, 대화형 터미널)
  notify                                  승인 대기 건수를 ntfy 로 알림 (OPERATOR_NTFY_TOPIC)
  feedback [--last N]                     거절 기록 보기 (다음 초안 전에)
  secret list | set <이름> [--file] | rm <이름>   발송 토큰 (set/rm 은 사람만, macOS 는 키체인)
  telegram [--setup] [--titles-only]      텔레그램으로 밖에서 승인 (사람만)
  connect x                               브라우저로 X 연결, 토큰 자동 갱신 (사람만)
""")
        return
    fn = COMMANDS.get(sys.argv[1])
    try:
        if not fn:
            die(f"모르는 명령: {sys.argv[1]} (op help)")
        fn(sys.argv[2:])
    except OpError as e:
        sys.stderr.write(f"op: {e.msg}\n")
        sys.exit(e.code)


if __name__ == "__main__":
    main()
