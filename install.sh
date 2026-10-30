#!/bin/sh
# Jangin 한 줄 설치 — 아이디어 구상 → 개발 → 배포 관리를 돕는 1인 사업 비서 (Hermes Agent 기반)
#
#   curl -fsSL https://raw.githubusercontent.com/pullyo/jangin/main/install.sh | sh
#
# 하는 일
#   1. Hermes Agent(Nous Research, MIT)가 없으면 공식 설치 스크립트로 설치한다 (먼저 묻는다)
#   2. jangin 을 ~/.jangin/jangin 에 내려받는다 (있으면 최신으로)
#   3. 쓰던 Hermes(기본 프로필)는 그대로 두고, 그것을 복사해 'jangin' 전용 프로필을 만든다
#   4. `jangin setup` 을 연다
#
# 환경 변수
#   JANGIN_YES=1            묻지 않고 진행 (Hermes 설치 포함)
#   JANGIN_NO_SETUP=1       마지막에 jangin setup 을 열지 않는다
#   JANGIN_HOME=폴더         Jangin 을 받을 곳 (기본 ~/.jangin/jangin)
#   JANGIN_REPO_URL=주소     다른 저장소에서 받기 (포크 등)
#   JANGIN_SOURCE=폴더       내려받지 않고 이 폴더를 그대로 쓴다 (개발용)
#   (예전 이름 OPERATOR_* 도 받는다)
# 나머지 인자는 hermes/jangin/install.sh 로 넘어간다 (예: --profile 이름, --fresh).
set -eu

YES=${JANGIN_YES:-${OPERATOR_YES:-}}
NO_SETUP=${JANGIN_NO_SETUP:-${OPERATOR_NO_SETUP:-}}
SOURCE=${JANGIN_SOURCE:-${OPERATOR_SOURCE:-}}
REPO_URL=${JANGIN_REPO_URL:-${OPERATOR_REPO_URL:-https://github.com/pullyo/jangin}}
DEST=${JANGIN_HOME:-${OPERATOR_HOME:-$HOME/.jangin/jangin}}
PATH="$HOME/.local/bin:$PATH"; export PATH

say() { printf '%s\n' "$*"; }
# 터미널을 실제로 열 수 있을 때만 묻는다. 열 수 없거나 읽지 못하면 "아니오" 로 본다 (묻지 않고 설치하지 않는다).
has_tty() { ( : </dev/tty >/dev/tty ) 2>/dev/null; }
ask() {
  [ -n "$YES" ] && return 0
  has_tty || return 1
  printf '%s [Y/n] ' "$1" > /dev/tty
  read -r a < /dev/tty || return 1
  case "$a" in n|N|no|No|NO|아니오|아니요) return 1 ;; esac
  return 0
}
# macOS 의 /usr/bin/git 은 Xcode 라이선스 동의 전에는 실행되지 않는다. 실제로 도는 git 을 고른다.
find_git() {
  for g in $(which -a git 2>/dev/null) /Library/Developer/CommandLineTools/usr/bin/git /opt/homebrew/bin/git; do
    [ -x "$g" ] && "$g" --version >/dev/null 2>&1 && { printf '%s' "$g"; return 0; }
  done
  return 1
}

say ""
say "Jangin 설치"
say "  아이디어 구상 → 개발 → 배포 관리를 돕는 1인 사업 비서. Hermes Agent(Nous Research, MIT) 위에서 동작합니다."
say ""

# 1. Hermes Agent
if ! command -v hermes >/dev/null 2>&1; then
  say "[1/4] Hermes Agent 가 아직 없습니다."
  say "      공식 설치 스크립트(https://hermes-agent.nousresearch.com/install.sh)로 설치합니다."
  say "      Python, Node 같은 도구가 함께 설치되고 ~/.hermes 폴더가 생깁니다."
  if ! ask "      Hermes Agent 를 설치할까요?"; then
    say "      설치하지 않았습니다. Hermes Agent 를 설치한 뒤 다시 실행해 주세요."
    exit 1
  fi
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
  hash -r 2>/dev/null || true
  command -v hermes >/dev/null 2>&1 || { say "      Hermes 명령을 찾지 못했습니다. 새 터미널을 열고 다시 실행해 주세요."; exit 1; }
else
  say "[1/4] Hermes Agent: 이미 설치됨 ($(hermes --version 2>/dev/null | head -1))"
fi

# 2. jangin 받기
if [ -n "$SOURCE" ]; then
  SRC=$SOURCE
  say "[2/4] jangin: $SRC 를 그대로 씁니다"
else
  SRC=$DEST
  mkdir -p "$(dirname "$DEST")"
  if GIT=$(find_git); then
    if [ -d "$DEST/.git" ]; then
      say "[2/4] jangin: 최신으로 받습니다 ($DEST)"
      "$GIT" -C "$DEST" pull --ff-only -q || say "      ! 최신으로 받지 못해 있는 것을 그대로 씁니다."
    else
      say "[2/4] jangin: 내려받습니다 ($DEST)"
      "$GIT" clone -q --depth 1 "$REPO_URL" "$DEST"
    fi
  else
    say "[2/4] jangin: git 이 없어 압축 파일로 내려받습니다 ($DEST)"
    TMP="$DEST.download"
    mkdir -p "$TMP"
    curl -fsSL "$REPO_URL/archive/refs/heads/main.tar.gz" | tar -xz -C "$TMP" --strip-components 1
    [ -d "$DEST" ] && mv "$DEST" "$DEST.old-$(date +%Y%m%d-%H%M%S)"
    mv "$TMP" "$DEST"
  fi
fi

# 3. Jangin 프로필
say "[3/4] Jangin 전용 프로필을 만듭니다 (쓰던 Hermes 는 그대로 둡니다)"
sh "$SRC/hermes/jangin/install.sh" "$@"

# 4. 설정
if [ -z "$NO_SETUP" ] && has_tty && ask "[4/4] 지금 jangin setup 을 진행할까요?"; then
  "$HOME/.local/bin/jangin" setup < /dev/tty > /dev/tty 2>&1 || true
else
  say "[4/4] 설정은 나중에: jangin setup"
fi
say ""
say "끝. Hermes 앱에서 프로필 'Jangin' 를 고르거나 터미널에서 jangin chat 으로 시작하세요."
say "업데이트: jangin update"
