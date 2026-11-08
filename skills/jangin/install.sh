#!/bin/sh
# jangin 스킬을 여러 에이전트에 설치한다. 스킬 폴더를 각 도구의 스킬 디렉터리에 심볼릭 링크(기본) 또는 복사한다.
#
#   sh install.sh                      # 설치된 도구(~/.claude, ~/.codex, ~/.cursor, ~/.gemini)를 찾아 사용자 레벨에 링크
#   sh install.sh --copy               # 링크 대신 복사
#   sh install.sh --project DIR        # 프로젝트 레벨: DIR/.agents/skills/jangin (+ 도구별 프로젝트 폴더)
#   sh install.sh --targets claude,codex
#   sh install.sh --print-hooks        # 훅 설정 스니펫을 실제 경로로 채워 출력 (설정 파일은 직접 수정하지 않는다)
#   sh install.sh --with-hooks         # 한 번에: 스킬 링크 + Claude Code 훅을 settings.json 에 합침 + op 명령을 ~/.local/bin 에
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
MODE=link; TARGETS=""; PROJECT=""; PRINT_HOOKS=0; WITH_HOOKS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --copy) MODE=copy ;;
    --targets) TARGETS="$2"; shift ;;
    --project) PROJECT="$2"; shift ;;
    --print-hooks) PRINT_HOOKS=1 ;;
    --with-hooks) WITH_HOOKS=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "모르는 옵션: $1" >&2; exit 1 ;;
  esac
  shift
done

place() { # place <dest-dir>
  dest="$1"
  mkdir -p "$(dirname "$dest")"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$HERE" ]; then echo "  = $dest (이미 링크됨)"; return; fi
    echo "  ! $dest 가 이미 있다. 건너뜀 (지우고 다시 실행하면 설치됨)"; return
  fi
  if [ "$MODE" = link ]; then ln -s "$HERE" "$dest"; echo "  + $dest -> $HERE"
  else cp -R "$HERE" "$dest"; echo "  + $dest (복사)"; fi
}

if [ -n "$PROJECT" ]; then
  P=$(cd "$PROJECT" && pwd)
  echo "프로젝트 레벨 설치: $P"
  place "$P/.agents/skills/jangin"      # Codex 등 공용 규약
  place "$P/.claude/skills/jangin"      # Claude Code
  place "$P/.cursor/skills/jangin"      # Cursor
  place "$P/.gemini/skills/jangin"      # Gemini CLI
  [ -f "$P/AGENTS.md" ] && grep -q "jangin 운영 규칙" "$P/AGENTS.md" || {
    echo "  i 훅을 못 쓰는 도구를 위해 $HERE/assets/hooks/AGENTS.md.snippet 을 $P/AGENTS.md 에 붙여 넣어라."; }
else
  [ -z "$TARGETS" ] && {
    for t in claude codex cursor gemini hermes; do [ -d "$HOME/.$t" ] && TARGETS="$TARGETS,$t"; done
    TARGETS=${TARGETS#,}
  }
  [ -z "$TARGETS" ] && { echo "설치된 도구를 못 찾았다. --targets claude,codex,cursor,gemini,hermes 로 지정해라."; exit 1; }
  echo "사용자 레벨 설치: $TARGETS"
  for t in $(echo "$TARGETS" | tr ',' ' '); do
    case "$t" in
      claude) place "$HOME/.claude/skills/jangin" ;;
      codex)  place "$HOME/.codex/skills/jangin" ;;
      cursor) place "$HOME/.cursor/skills/jangin" ;;
      gemini) place "$HOME/.gemini/skills/jangin" ;;
      hermes) place "$HOME/.hermes/skills/jangin" ;;   # Hermes Agent (플러그인은 hermes/jangin/install.sh)
      agents) place "$HOME/.agents/skills/jangin" ;;
      *) echo "  ? 모르는 타깃 $t" ;;
    esac
  done
fi

merge_claude_hook() { # merge_claude_hook <settings.json>  — 있던 설정은 그대로 두고 jangin 훅만 더한다 (.bak 백업)
  python3 -I - "$1" "$HERE" <<'PY'
import json, os, shutil, sys
path, here = sys.argv[1], sys.argv[2]
op = os.path.join(here, "scripts", "op.py")
cmd = f'[ -f "{op}" ] || exit 0; exec python3 -I "{op}" guard --format claude'
data = {}
if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError:
        sys.exit(f"  ! {path} 가 올바른 JSON 이 아니라 건드리지 않았다. --print-hooks 로 직접 붙여라.")
pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
if any("guard --format claude" in h.get("command", "") and "op.py" in h.get("command", "")
       for e in pre for h in e.get("hooks", [])):
    print(f"  = {path} (jangin 훅이 이미 있다)")
    sys.exit(0)
if os.path.exists(path):
    shutil.copy2(path, path + ".bak")
pre.append({"matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit|Read", "hooks": [{"type": "command", "command": cmd}]})
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"  + {path} 에 jangin 훅 추가" + (" (이전 설정은 .bak)" if os.path.exists(path + ".bak") else ""))
PY
}

if [ "$WITH_HOOKS" = 1 ]; then
  echo
  echo "훅 연결 (Claude Code):"
  if [ -n "$PROJECT" ]; then merge_claude_hook "$P/.claude/settings.json"
  elif [ -d "$HOME/.claude" ]; then merge_claude_hook "$HOME/.claude/settings.json"
  else echo "  i ~/.claude 가 없어 건너뜀. 다른 도구는 --print-hooks 로 나오는 설정을 붙인다."; fi
  BIN="$HOME/.local/bin"
  mkdir -p "$BIN"
  if [ -e "$BIN/op" ] || [ -L "$BIN/op" ]; then
    [ "$(readlink "$BIN/op")" = "$HERE/scripts/op" ] && echo "  = $BIN/op (이미 링크됨)" || echo "  ! $BIN/op 가 이미 있다. 건너뜀"
  else ln -s "$HERE/scripts/op" "$BIN/op"; echo "  + $BIN/op -> $HERE/scripts/op"; fi
  case ":$PATH:" in *":$BIN:"*) ;; *) echo "  i $BIN 이 PATH 에 없다. ~/.zshrc 에 추가:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;; esac
  echo
  echo "끝. 프로젝트 폴더에서 에이전트에게 하고 싶은 일을 말하고, 확인할 것이 생기면 터미널에서 op 를 친다."
  [ "$PRINT_HOOKS" = 1 ] || exit 0
fi

echo
echo "다음: 승인 게이트를 100% 로 만들려면 훅을 건다.  sh \"$HERE/install.sh\" --with-hooks  (다른 도구: --print-hooks)"
[ "$PRINT_HOOKS" = 1 ] || exit 0

echo
echo "================ 훅 설정 (OPERATOR_HOME 을 채운 것) ================"
for f in claude-code.settings.json codex.hooks.json cursor.hooks.json gemini.settings.json hermes.config.yaml; do
  echo
  echo "---- $f"
  sed "s#OPERATOR_HOME#$HERE#g" "$HERE/assets/hooks/$f" | grep -v '"_comment"' | grep -v '^#'
done
echo
echo "붙일 곳:"
echo "  Claude Code : ~/.claude/settings.json  (또는 프로젝트 .claude/settings.json) 의 \"hooks\" 에 합치기"
echo "  Codex CLI   : ~/.codex/hooks.json      (또는 프로젝트 .codex/hooks.json)"
echo "  Cursor      : ~/.cursor/hooks.json     (또는 프로젝트 .cursor/hooks.json)"
echo "  Gemini CLI  : ~/.gemini/settings.json  (또는 프로젝트 .gemini/settings.json) 의 \"hooks\" 에 합치기"
echo "  Hermes      : ~/.hermes/config.yaml 의 hooks 에 합치기 (처음 실행 때 훅을 믿을지 묻는다). 설명: assets/hooks/hermes.config.yaml"
echo "확인: 프로젝트에서 op init 후, 에이전트에게 'git push 해' 라고 시켜 보면 막혀야 한다."
