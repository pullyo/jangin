#!/bin/sh
# Jangin 을 Hermes Agent 옆의 "전용 사업 비서" 프로필로 설치한다. 쓰던 Hermes(기본 프로필)와 Hermes 코드는 건드리지 않는다.
#
#   sh hermes/jangin/install.sh                    # 프로필 'jangin' 를 만들고(없으면) 플러그인·스킬·성격을 넣는다
#                                                    #   새 프로필은 기본 프로필을 복사해 만든다 (모델·키·스킬·플러그인·기억).
#                                                    #   OAuth 로그인은 Hermes 가 복사하지 않고 기본 프로필 것을 이어받게 한다.
#   sh hermes/jangin/install.sh --fresh            # 복사하지 않고 빈 프로필로 만든다
#   sh hermes/jangin/install.sh --profile 이름      # 다른 프로필 이름
#   sh hermes/jangin/install.sh --home 폴더         # 이 HERMES_HOME 에 바로 설치 (프로필을 만들지 않음, 시험용)
#   sh hermes/jangin/install.sh --no-soul           # 프로필의 SOUL.md 는 그대로 둔다
#   sh hermes/jangin/install.sh --no-command        # ~/.local/bin/jangin 명령을 만들지 않는다
#
# 하는 일: <HERMES_HOME>/plugins/jangin/ 에 플러그인을 복사하고, 그 안의 skill/ 에 jangin 스킬을 복사한다.
# SOUL.md 는 원래 것을 SOUL.md.bak-날짜 로 남긴 뒤 바꾼다. 마지막에 `hermes plugins enable jangin` 을 실행하고,
# `jangin` 명령(~/.local/bin/jangin)을 만든다: `jangin setup` 은 한국어 jangin 마법사, 나머지는 hermes 로 전달.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
PROFILE=jangin
TARGET=""
SOUL=1
COMMAND=1
FRESH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE=$2; shift 2 ;;
    --home) TARGET=$2; HOME_GIVEN=1; shift 2 ;;
    --no-soul) SOUL=0; shift ;;
    --no-command) COMMAND=0; shift ;;
    --fresh) FRESH=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "모르는 옵션: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$TARGET" ]; then
  command -v hermes >/dev/null 2>&1 || { echo "hermes 명령을 찾지 못했다. Hermes Agent 를 먼저 설치한다."; exit 1; }
  TARGET="$HOME/.hermes/profiles/$PROFILE"
  # 예전 이름(operator)으로 만든 프로필이 있으면 새로 복사하지 않고 이름만 바꾼다 (대화·기억·설정 그대로)
  if [ ! -d "$TARGET" ] && [ "$PROFILE" = jangin ] && [ -d "$HOME/.hermes/profiles/operator" ]; then
    echo "예전 프로필 'operator' 를 'jangin' 으로 이름을 바꾼다 (hermes profile rename operator jangin)"
    hermes profile rename operator jangin
  fi
  if [ ! -d "$TARGET" ]; then
    if [ "$FRESH" = 0 ] && [ -f "$HOME/.hermes/config.yaml" ]; then
      echo "프로필 '$PROFILE' 을 기본 프로필을 복사해 만든다 (hermes profile create $PROFILE --clone-all --clone-from default)"
      hermes profile create "$PROFILE" --clone-all --clone-from default --no-alias \
        --description "1인 사업 비서: 아이디어 구상, 개발, 배포 관리. 승인·단계 이동·발송은 사람만."
    else
      echo "프로필 '$PROFILE' 을 빈 프로필로 만든다 (hermes profile create $PROFILE)"
      hermes profile create "$PROFILE" --no-alias
    fi
  fi
fi
mkdir -p "$TARGET/plugins"
PLUG="$TARGET/plugins/jangin"
# 예전 이름의 플러그인(plugins/operator)은 끄고 백업 폴더로 옮긴다 (두 플러그인이 같은 명령을 등록하지 않게)
if [ -d "$TARGET/plugins/operator" ]; then
  if command -v hermes >/dev/null 2>&1; then HERMES_HOME="$TARGET" hermes plugins disable operator >/dev/null 2>&1 || true; fi
  mkdir -p "$TARGET/backups"
  mv "$TARGET/plugins/operator" "$TARGET/backups/operator-plugin-$(date +%Y%m%d-%H%M%S)"
  echo "  i 예전 이름의 operator 플러그인을 끄고 $TARGET/backups/ 로 옮겼다"
fi

rm -rf "$PLUG.new"
mkdir -p "$PLUG.new/skill"
for f in __init__.py commands.py setup_wizard.py plugin.yaml SOUL.md config.example.yaml; do cp "$HERE/$f" "$PLUG.new/$f"; done
# 스킬: 평가 자료와 캐시는 빼고 복사한다
(cd "$REPO/skills/jangin" && tar cf - --exclude evals --exclude __pycache__ --exclude '*.pyc' .) | (cd "$PLUG.new/skill" && tar xf -)
rm -rf "$PLUG"
mv "$PLUG.new" "$PLUG"
echo "  + 플러그인: $PLUG"
echo "  + 스킬:     $PLUG/skill (op: $PLUG/skill/scripts/op.py)"

if [ "$SOUL" = 1 ]; then
  if [ -f "$TARGET/SOUL.md" ] && ! cmp -s "$TARGET/SOUL.md" "$HERE/SOUL.md"; then
    cp "$TARGET/SOUL.md" "$TARGET/SOUL.md.bak-$(date +%Y%m%d-%H%M%S)"
    echo "  i 기존 SOUL.md 를 SOUL.md.bak-* 로 남겼다"
  fi
  cp "$HERE/SOUL.md" "$TARGET/SOUL.md"
  echo "  + 성격:     $TARGET/SOUL.md"
fi

if command -v hermes >/dev/null 2>&1; then
  HERMES_HOME="$TARGET" hermes plugins enable jangin || echo "  ! 'hermes plugins enable jangin' 실패. 직접 실행한다: HERMES_HOME=\"$TARGET\" hermes plugins enable jangin"
else
  echo "  i hermes 가 없어 활성화는 건너뛴다. config.yaml 의 plugins.enabled 에 jangin 을 넣는다."
fi

# 프로필 표시 이름 (복사 원본의 표시 이름을 물려받지 않게)
if [ -z "${HOME_GIVEN:-}" ]; then
  for cand in $(which -a python3 2>/dev/null) python3; do
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
      HERMES_HOME="$TARGET" "$cand" -I "$PLUG/setup_wizard.py" --profile "$PROFILE" --display-name "Jangin" --home "$TARGET" >/dev/null 2>&1 \
        && echo "  + 표시 이름: Jangin" && break
    fi
  done
fi

# 복사해 온 프로필에 예전 위치(다른 프로필)의 jangin 셸 훅이 있으면 이 프로필의 op.py 로 고친다.
if [ -f "$TARGET/config.yaml" ] && grep -q 'guard --format hermes' "$TARGET/config.yaml" 2>/dev/null; then
  for cand in $(which -a python3 2>/dev/null) python3; do
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
      HERMES_HOME="$TARGET" "$cand" -I "$PLUG/setup_wizard.py" --repair-hook --home "$TARGET" && break
    fi
  done
fi

# jangin 명령: 기본 HERMES_HOME(~/.hermes) 이면 프로필 default, 프로필 설치면 그 프로필. 시험용 --home 은 만들지 않는다.
CMD_PROFILE=""
if [ -z "${HOME_GIVEN:-}" ]; then CMD_PROFILE=$PROFILE; fi
if [ "$TARGET" = "$HOME/.hermes" ]; then CMD_PROFILE=default; fi
if [ "$COMMAND" = 1 ] && [ -n "$CMD_PROFILE" ] && command -v hermes >/dev/null 2>&1; then
  BIN_DIR="$HOME/.local/bin"
  mkdir -p "$BIN_DIR"
  HERMES_BIN=$(command -v hermes)
  # 마법사는 표준 라이브러리만 쓴다. 실제로 돌아가는 python3 의 절대 경로를 박아 둔다
  # (macOS 의 /usr/bin/python3 는 Xcode 라이선스 동의 전에는 실행되지 않는다).
  PYTHON_BIN=""
  for cand in $(which -a python3 2>/dev/null) python3; do
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then PYTHON_BIN=$cand; break; fi
  done
  [ -n "$PYTHON_BIN" ] || { echo "  ! 실행되는 python3(3.8+)를 찾지 못해 jangin 명령을 만들지 않았다."; COMMAND=0; }
fi
if [ "$COMMAND" = 1 ] && [ -n "$CMD_PROFILE" ] && command -v hermes >/dev/null 2>&1; then
  if [ "$CMD_PROFILE" = default ]; then REINSTALL_ARGS="--home $HOME/.hermes"; else REINSTALL_ARGS="--profile $CMD_PROFILE"; fi
  cat > "$BIN_DIR/jangin" <<WRAP
#!/bin/sh
# jangin — Jangin(Hermes 배포판) 명령. jangin 의 install.sh 가 만들었다.
#   jangin setup            Hermes 기본 설정 → jangin 단계 (Hermes 마법사와 같은 화면)
#   jangin setup --hermes   원래 Hermes 설정 마법사만
#   jangin setup --jangin-only   Hermes 기본 설정을 건너뛰고 Jangin 단계만
#   jangin setup model 등   Hermes 설정의 한 단계
#   jangin update           Hermes 와 jangin 을 함께 최신으로 (jangin 은 $REPO 에서 받아 다시 설치)
#   그 밖의 모든 명령         hermes -p $CMD_PROFILE 로 전달 (jangin chat, jangin gateway restart …)
if [ "\${1:-}" = "setup" ] && { [ \$# -eq 1 ] || [ "\${2:-}" = "--hermes" ] || [ "\${2:-}" = "--jangin-only" ] || [ "\${2:-}" = "--operator-only" ]; }; then
  shift
  exec "$PYTHON_BIN" -I "$PLUG/setup_wizard.py" --profile "$CMD_PROFILE" "\$@"
fi
if [ "\${1:-}" = "update" ] && [ \$# -eq 1 ]; then
  echo "Hermes Agent 업데이트"
  "$HERMES_BIN" update || echo "! Hermes 업데이트에 실패했다. 나중에 hermes update 를 다시 실행해 주세요."
  if [ -d "$REPO/.git" ]; then
    echo "jangin 업데이트 ($REPO)"
    G=""
    for g in \$(which -a git 2>/dev/null) /Library/Developer/CommandLineTools/usr/bin/git /opt/homebrew/bin/git; do
      [ -x "\$g" ] && "\$g" --version >/dev/null 2>&1 && { G=\$g; break; }
    done
    if [ -n "\$G" ]; then "\$G" -C "$REPO" pull --ff-only -q || echo "! jangin 을 최신으로 받지 못했다 (로컬 변경이 있으면 직접 정리)"; fi
  fi
  exec sh "$REPO/hermes/jangin/install.sh" $REINSTALL_ARGS
fi
exec "$HERMES_BIN" -p "$CMD_PROFILE" "\$@"
WRAP
  chmod +x "$BIN_DIR/jangin"
  echo "  + 명령:     $BIN_DIR/jangin  (jangin setup = Jangin 설정 마법사)"
  # 예전 이름 명령(operator)이 이 설치가 만든 것이면 jangin 으로 넘기는 짧은 안내로 바꾼다
  if { [ -f "$BIN_DIR/operator" ] && grep -Eq 'install.sh 가 만들었다|hermes -p' "$BIN_DIR/operator" 2>/dev/null; } \
     || { [ ! -e "$BIN_DIR/operator" ] && [ -d "$HOME/.operator" -o -d "$TARGET/backups" ]; }; then
    printf '%s\n' '#!/bin/sh' '# 예전 이름. Jangin 으로 바뀌었다: jangin 명령을 쓴다.' 'echo "operator 명령은 jangin 으로 바뀌었습니다. 다음부터 jangin 을 쓰세요." >&2' "exec \"$BIN_DIR/jangin\" \"\$@\"" > "$BIN_DIR/operator"
    chmod +x "$BIN_DIR/operator"
    echo "  + 예전 명령: $BIN_DIR/operator → jangin 으로 넘김"
  fi
fi

cat <<MSG

설치 완료. 다음:
  1. 메신저로 승인하려면 이 프로필의 게이트웨이에 텔레그램 등을 연결하고 허용 사용자(TELEGRAM_ALLOWED_USERS)를 본인으로 한다.
  2. (선택) 셸 훅도 걸어 두면 플러그인이 꺼져도 막는다: $PLUG/config.example.yaml 의 hooks 부분.
  3. 터미널에서: jangin setup   (Hermes 기본 설정 → 프로젝트 폴더, 승인 방식, 메신저 허용 사용자, 두 번째 잠금)
  4. Hermes 앱 새 대화에서: /idea 동네 빵집 예약 페이지
MSG
