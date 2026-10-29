#!/bin/sh
# operator 스킬을 여러 에이전트에 설치한다. 스킬 폴더를 각 도구의 스킬 디렉터리에 심볼릭 링크(기본) 또는 복사한다.
#
#   sh install.sh                      # 설치된 도구(~/.claude, ~/.codex, ~/.cursor, ~/.gemini)를 찾아 사용자 레벨에 링크
#   sh install.sh --copy               # 링크 대신 복사
#   sh install.sh --project DIR        # 프로젝트 레벨: DIR/.agents/skills/operator (+ 도구별 프로젝트 폴더)
#   sh install.sh --targets claude,codex
#   sh install.sh --print-hooks        # 훅 설정 스니펫을 실제 경로로 채워 출력 (설정 파일은 직접 수정하지 않는다)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
MODE=link; TARGETS=""; PROJECT=""; PRINT_HOOKS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --copy) MODE=copy ;;
    --targets) TARGETS="$2"; shift ;;
    --project) PROJECT="$2"; shift ;;
    --print-hooks) PRINT_HOOKS=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
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
  place "$P/.agents/skills/operator"      # Codex 등 공용 규약
  place "$P/.claude/skills/operator"      # Claude Code
  place "$P/.cursor/skills/operator"      # Cursor
  place "$P/.gemini/skills/operator"      # Gemini CLI
  [ -f "$P/AGENTS.md" ] && grep -q "operator 운영 규칙" "$P/AGENTS.md" || {
    echo "  i 훅을 못 쓰는 도구를 위해 $HERE/assets/hooks/AGENTS.md.snippet 을 $P/AGENTS.md 에 붙여 넣어라."; }
else
  [ -z "$TARGETS" ] && {
    for t in claude codex cursor gemini; do [ -d "$HOME/.$t" ] && TARGETS="$TARGETS,$t"; done
    TARGETS=${TARGETS#,}
  }
  [ -z "$TARGETS" ] && { echo "설치된 도구를 못 찾았다. --targets claude,codex,cursor,gemini 로 지정해라."; exit 1; }
  echo "사용자 레벨 설치: $TARGETS"
  for t in $(echo "$TARGETS" | tr ',' ' '); do
    case "$t" in
      claude) place "$HOME/.claude/skills/operator" ;;
      codex)  place "$HOME/.codex/skills/operator" ;;
      cursor) place "$HOME/.cursor/skills/operator" ;;
      gemini) place "$HOME/.gemini/skills/operator" ;;
      agents) place "$HOME/.agents/skills/operator" ;;
      *) echo "  ? 모르는 타깃 $t" ;;
    esac
  done
fi

echo
echo "다음: 승인 게이트를 100% 로 만들려면 훅을 건다.  sh \"$HERE/install.sh\" --print-hooks"
[ "$PRINT_HOOKS" = 1 ] || exit 0

echo
echo "================ 훅 설정 (OPERATOR_HOME 을 채운 것) ================"
for f in claude-code.settings.json codex.hooks.json cursor.hooks.json gemini.settings.json; do
  echo
  echo "---- $f"
  sed "s#OPERATOR_HOME#$HERE#g" "$HERE/assets/hooks/$f" | grep -v '"_comment"'
done
echo
echo "붙일 곳:"
echo "  Claude Code : ~/.claude/settings.json  (또는 프로젝트 .claude/settings.json) 의 \"hooks\" 에 합치기"
echo "  Codex CLI   : ~/.codex/hooks.json      (또는 프로젝트 .codex/hooks.json)"
echo "  Cursor      : ~/.cursor/hooks.json     (또는 프로젝트 .cursor/hooks.json)"
echo "  Gemini CLI  : ~/.gemini/settings.json  (또는 프로젝트 .gemini/settings.json) 의 \"hooks\" 에 합치기"
echo "확인: 프로젝트에서 op init 후, 에이전트에게 'git push 해' 라고 시켜 보면 막혀야 한다."
