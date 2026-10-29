#!/usr/bin/env python3
"""op — operator 스킬의 단일 진입점 CLI.

Foundable의 Ted가 인프라(Temporal/Modal/승인 큐)로 강제하던 네 가지를
셸 + JSON 파일 수준으로 옮긴 것이다. 어떤 에이전트(Claude Code, Codex,
Cursor, Gemini CLI, ...)에서든 같은 명령으로 동작한다. 표준 라이브러리만 쓴다.

  1. 재개 가능한 pass 루프   → op pass start/next/done/fail/end  (.operator/state.json)
  2. 승인 게이트             → op pending add/list/approve/reject, op send, op guard
  3. 검증 게이트             → op verify (pending add 전에 자동 실행)
  4. 모델 라우팅             → op llm --role ... (로컬 모델이 있으면 거기로)

사용법: op.py <command> [args]   (op.py help 로 전체 목록)
"""
import json
import os
import re
import shlex
import subprocess
import sys
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
    ],
    # 에이전트가 직접 쓰면 안 되는 경로 (Write/Edit/apply_patch). 큐는 op 명령으로만 건드린다.
    "deny_paths": [
        ".operator/pending/", ".operator/approved/", ".operator/sent/", ".operator/rejected/",
        ".operator/guard.json",
    ],
}


# ---------------------------------------------------------------- 공통
def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def die(msg, code=1):
    sys.stderr.write(f"op: {msg}\n")
    sys.exit(code)


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


def op_dir(required=True):
    root = find_root()
    if root is None:
        if required:
            die("여기엔 .operator/ 가 없다. 먼저 `op init` 을 실행해라.", 2)
        return None
    od = os.path.join(root, OP_DIR_NAME)
    for sub in ("pending", "approved", "sent", "rejected", "passes", "research", "drafts", "tmp"):
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
def cmd_init(args):
    root = os.getcwd()
    od = os.path.join(root, OP_DIR_NAME)
    for sub in ("pending", "approved", "sent", "rejected", "passes", "research", "drafts", "tmp"):
        os.makedirs(os.path.join(od, sub), exist_ok=True)
    cfg_path = os.path.join(od, "config.json")
    if not os.path.exists(cfg_path):
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        cfg["project"] = os.path.basename(root)
        save_json(cfg_path, cfg)
    gpath = os.path.join(od, "guard.json")
    if not os.path.exists(gpath):
        save_json(gpath, {"deny_commands": [], "human_only_commands": [], "deny_paths": [], "allow_commands": []})
    gi = os.path.join(od, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w") as f:
            f.write("tmp/\n*.tmp\n")
    print(f"초기화 완료: {od}")
    print("다음: business.md 가 없으면 plan 단계부터 (SKILL.md 참고).")


def cmd_status(args):
    od = op_dir()
    root = os.path.dirname(od)
    biz = os.path.join(od, "business.md")
    print(f"프로젝트: {root}")
    print(f"business.md: {'있음' if os.path.exists(biz) else '없음 → plan 단계 필요'}")
    st = load_json(os.path.join(od, "state.json"), None)
    if st and st.get("status") == "running":
        nxt = next_step(st)
        print(f"진행 중인 pass: {st['pass_id']} (goal: {st.get('goal','')}) 다음 단계: {nxt or '없음 → op pass end'}")
        print(f"  단계 사용: {st['step_count']}/{st['max_steps']}")
        for s in st["steps"]:
            print(f"  - {s['name']}: {s['status']}" + (f" → {s['output']}" if s.get("output") else ""))
    else:
        print("진행 중인 pass 없음")
    for status in ("pending", "approved", "sent", "rejected"):
        n = len([f for f in os.listdir(os.path.join(od, status)) if f.endswith(".md")])
        print(f"{status}: {n}")


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
        steps = (opts.get("steps") or ",".join(cfg["pass"]["steps"])).split(",")
        today = datetime.now().strftime("%Y-%m-%d")
        n = 1 + len([f for f in os.listdir(os.path.join(od, "passes")) if f.startswith(today)])
        st = {
            "pass_id": f"{today}-{n:02d}",
            "goal": opts.get("goal", ""),
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
        print(f"승인 대기 {len(pend)}건. 사람이 `op pending list` 로 확인한다.")
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
            "action": opts.get("action") or meta.get("action") or "",
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
        print("이제 이 항목은 사람이 `op pending approve " + item_id + "` 할 때까지 밖으로 나가지 않는다.")
        return

    if sub == "list":
        opts = kv(rest)
        statuses = [opts.get("status")] if opts.get("status") else ["pending", "approved"]
        total = 0
        for s in statuses:
            files = sorted(f for f in os.listdir(os.path.join(od, s)) if f.endswith(".md"))
            print(f"== {s} ({len(files)})")
            for f in files:
                with open(os.path.join(od, s, f), encoding="utf-8") as fh:
                    _, meta = parse_front_matter(fh.read())
                extra = meta.get("channel") or meta.get("to") or ""
                print(f"  {meta.get('id', f[:4])}  {meta.get('type', '?'):8s} {extra:20s} {meta.get('title', f)}")
                total += 1
        if total == 0:
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
        if not (sys.stdin.isatty() and sys.stdout.isatty()) and os.environ.get("OPERATOR_ALLOW_NONINTERACTIVE_APPROVE") != "1":
            die("승인/거절은 사람이 대화형 터미널에서만 할 수 있다 (에이전트의 셸 도구에는 터미널이 없다). "
                "자동화 스크립트에서 꼭 필요하면 OPERATOR_ALLOW_NONINTERACTIVE_APPROVE=1 을 사람이 직접 설정해라.", 7)
        s, p = find_item(od, item_id, ("pending",))
        if not p:
            die(f"pending 에 {item_id} 가 없다.")
        with open(p, encoding="utf-8") as f:
            raw = f.read()
        body, meta = parse_front_matter(raw)
        new_status = "approved" if sub == "approve" else "rejected"
        if sub == "approve":
            if opts.get("action"):
                meta["action"] = opts["action"]
            if not (meta.get("action") or "").strip():
                print(f"참고: {item_id} 에 실행 명령(action)이 없다. 이대로 approve 하면 `op send` 는 거부된다. "
                      f"`op pending approve {item_id} --action \"<명령>\"` 으로 명령까지 승인해라.")
        meta["status"] = new_status
        meta[new_status] = now()
        if opts.get("note") or opts.get("reason"):
            meta["note"] = opts.get("note") or opts.get("reason")
        dst = os.path.join(od, new_status, os.path.basename(p))
        with open(dst, "w", encoding="utf-8") as f:
            f.write("---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---\n\n" + body)
        os.remove(p)
        print(f"{item_id} → {new_status}")
        if new_status == "approved":
            act = meta.get("action")
            print("다음: 에이전트가 `op send " + item_id + " -- <명령>` 으로 실제 발송/게시/배포한다." + (f"\n  기록된 action: {act}" if act else ""))
        return
    die(f"모르는 하위 명령: pending {sub}")


# ---------------------------------------------------------------- send (승인된 티켓으로만 밖으로)
def cmd_send(args):
    if "--" not in args:
        args = args + ["--"]
    if args.index("--") == 0:
        die("op send <id> [-- <승인된 action 과 같은 명령>]")
    i = args.index("--")
    head, cmdv = args[:i], args[i + 1:]
    item_id = head[0]
    use_shell = "--shell" in head
    od = op_dir()
    root = os.path.dirname(od)
    s, p = find_item(od, item_id, ("approved",))
    if not p:
        s2, _ = find_item(od, item_id)
        die(f"{item_id} 는 approved 상태가 아니다 (현재: {s2 or '없음'}). 사람이 승인한 티켓으로만 보낼 수 있다.", 5)
    with open(p, encoding="utf-8") as f:
        raw = f.read()
    body, meta = parse_front_matter(raw)
    action = (meta.get("action") or "").strip()
    if not action:
        die(f"{item_id} 에는 승인된 실행 명령(action)이 없다. 사람이 `op pending approve {item_id} --action \"<명령>\"` 으로 명령까지 승인해야 보낼 수 있다.", 6)
    if cmdv:
        given = " ".join(cmdv) if use_shell else shlex.join(cmdv)
        if " ".join(given.split()) != " ".join(action.split()):
            die(f"보내려는 명령이 승인된 action 과 다르다.\n  승인: {action}\n  요청: {given}\n명령을 바꾸려면 새 티켓을 올려 다시 승인받아라.", 6)
    # 승인된 action 그대로 실행한다. 인용이 필요한 명령이라 셸로 넘긴다.
    cmd_str, use_shell = action, True
    if re.search(r"\bop(?:\.py)?\s+(?:pending|send)\b", action):
        die("action 안에서 op 의 큐 명령을 실행할 수 없다.", 6)
    print(f"[send {item_id}] {cmd_str}")
    r = subprocess.run(cmd_str, shell=True, cwd=root)
    meta["executed"] = now()
    meta["command"] = cmd_str
    meta["exit"] = str(r.returncode)
    if r.returncode == 0:
        meta["status"] = "sent"
        dst = os.path.join(od, "sent", os.path.basename(p))
        os.remove(p)
    else:
        dst = p
    with open(dst, "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---\n\n" + body)
    print(f"exit {r.returncode} → {'sent' if r.returncode == 0 else 'approved 유지 (실패, 다시 시도 가능)'}")
    sys.exit(r.returncode)


# ---------------------------------------------------------------- guard (승인 게이트 훅)
def extract_from_hook_input(data):
    """여러 에이전트의 훅 입력에서 (명령문자열, [파일경로]) 를 뽑는다."""
    ti = data.get("tool_input") or data.get("toolInput") or data.get("input") or {}
    if not isinstance(ti, dict):
        ti = {}
    cmd = ti.get("command") or data.get("command") or ti.get("cmd") or ""
    if isinstance(cmd, list):  # Codex shell: ["bash","-lc","..."]
        parts = [str(c) for c in cmd]
        # The script is the argument after -c/-lc; joining everything would lose its quoting.
        cmd = parts[-1] if len(parts) >= 3 and parts[-2] in ("-c", "-lc", "/c", "/C", "-Command") else " ".join(parts)
    paths = []
    for k in ("file_path", "path", "filePath", "notebook_path"):
        v = ti.get(k) or data.get(k)
        if isinstance(v, str):
            paths.append(v)
    for k in ("patch", "input"):  # Codex apply_patch
        v = ti.get(k)
        if isinstance(v, str):
            paths += re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", v, flags=re.M)
    return str(cmd), paths


# A session opened elsewhere can still act inside an operator project: `cd proj && wrangler deploy`,
# `git -C proj push`, or a Write to proj/.operator/pending/x. Find every operator project the call
# can touch, not only the one above the hook's working directory.
_CD = re.compile(r"""(?:^|[;&|(\n]|&&|\|\|)\s*(?:builtin\s+)?(?:cd|pushd|chdir|Set-Location|sl)\s+(?:/d\s+|-LiteralPath\s+|-Path\s+)?("[^"]*"|'[^']*'|[^\s;&|)]+)""", re.I)
_GIT_C = re.compile(r"""\bgit\s+(?:-c\s+\S+\s+)*-C\s+("[^"]*"|'[^']*'|\S+)""")
_DIR_OPTS = re.compile(r"""(?:--cwd|--prefix|--dir|--cd)(?:=|\s+)("[^"]*"|'[^']*'|[^\s;&|]+)""")


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
_QUEUE_DIRS = ("pending", "approved", "sent", "rejected")


def touches_queue(cmd, od, base):
    """셸 명령이 이 프로젝트의 승인 큐 경로를 언급하면 그 상대 경로를 돌려준다."""
    if re.search(r"\bop(?:\.py)?\s+(?:pending|send|status|pass|verify|init|guard|llm)\b", cmd) and not re.search(r"[;&|]", cmd):
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
    queue_msg = "은 승인 큐 영역이다. 에이전트가 직접 쓸 수 없다. 초안은 `op pending add` 로 올리고, 승인/거절은 사람이 터미널에서 한다."
    for p in paths:
        ap = os.path.abspath(os.path.join(base or root, p)) if not os.path.isabs(p) else p
        rel = os.path.relpath(ap, root)
        for dp in rules["deny_paths"]:
            if rel.startswith(dp.rstrip("/")):
                return True, f"'{rel}' " + queue_msg
    if not cmd.strip():
        return False, ""
    touched = touches_queue(cmd, od, base)
    if touched and not _READ_ONLY.match(cmd):
        return True, f"'{touched}' " + queue_msg + " 셸로 옮기거나 덮어쓰는 것도 같은 규칙이다."
    for pat in rules["human_only_commands"]:
        if re.search(pat, cmd):
            return True, "승인/거절은 사람만 한다. 사용자에게 `op pending list` 로 확인하고 `op pending approve <id>` 를 자기 터미널에서 실행해 달라고 요청해라."
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
    msg = "[operator 승인 게이트] " + reason
    if fmt == "cursor":
        print(json.dumps({"permission": "deny", "user_message": msg, "agent_message": msg}, ensure_ascii=False))
        return
    if fmt == "gemini":
        print(json.dumps({"decision": "deny", "reason": msg}, ensure_ascii=False))
        return
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
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "-h", "--help"):
        print(__doc__)
        print("""명령:
  init                                   .operator/ 작업 공간 생성
  status                                 현재 상태 요약
  pass start --goal "..." [--max-steps N] [--steps a,b,c]
  pass next | done <step> [--output P] | fail <step> --reason "..." | end | show
  verify <file> --type post|email|research|site|other [--channel x]
  pending add <file> --type ... [--channel x] [--title ...] [--action "명령"]
  pending list [--status pending|approved|sent|rejected] | show <id>
  pending approve <id> [--action "명령"] [--note ...] | reject <id> --reason ...   (사람만, 대화형 터미널)
  send <id> [-- <명령>]                   승인된 action 그대로 실행 (명령을 주면 action 과 같아야 함)
  guard [--format claude|codex|cursor|gemini]   (훅: stdin 으로 JSON)
  guard check [--cwd DIR] "<command>"     이 명령이 막히는지 확인
  llm --role classify|summarize|tag|extract [--input f] "프롬프트"
""")
        return
    fn = COMMANDS.get(sys.argv[1])
    if not fn:
        die(f"모르는 명령: {sys.argv[1]} (op help)")
    fn(sys.argv[2:])


if __name__ == "__main__":
    main()
