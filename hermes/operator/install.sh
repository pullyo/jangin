#!/bin/sh
# operator 를 Hermes Agent 옆의 "전용 사업 비서" 프로필로 설치한다. 쓰던 Hermes(기본 프로필)와 Hermes 코드는 건드리지 않는다.
#
#   sh hermes/operator/install.sh                    # 프로필 'operator' 를 만들고(없으면) 플러그인·스킬·성격을 넣는다
#                                                    #   새 프로필은 기본 프로필을 복사해 만든다 (모델·키·스킬·플러그인·기억).
#                                                    #   OAuth 로그인은 Hermes 가 복사하지 않고 기본 프로필 것을 이어받게 한다.
#   sh hermes/operator/install.sh --fresh            # 복사하지 않고 빈 프로필로 만든다
#   sh hermes/operator/install.sh --profile 이름      # 다른 프로필 이름
#   sh hermes/operator/install.sh --home 폴더         # 이 HERMES_HOME 에 바로 설치 (프로필을 만들지 않음, 시험용)
#   sh hermes/operator/install.sh --no-soul           # 프로필의 SOUL.md 는 그대로 둔다
#   sh hermes/operator/install.sh --no-command        # ~/.local/bin/operator 명령을 만들지 않는다
#
# 하는 일: <HERMES_HOME>/plugins/operator/ 에 플러그인을 복사하고, 그 안의 skill/ 에 operator 스킬을 복사한다.
# SOUL.md 는 원래 것을 SOUL.md.bak-날짜 로 남긴 뒤 바꾼다. 마지막에 `hermes plugins enable operator` 를 실행하고,
# `operator` 명령(~/.local/bin/operator)을 만든다: `operator setup` 은 한국어 operator 마법사, 나머지는 hermes 로 전달.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
PROFILE=operator
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
PLUG="$TARGET/plugins/operator"

rm -rf "$PLUG.new"
mkdir -p "$PLUG.new/skill"
for f in __init__.py commands.py setup_wizard.py plugin.yaml SOUL.md config.example.yaml; do cp "$HERE/$f" "$PLUG.new/$f"; done
# 스킬: 평가 자료와 캐시는 빼고 복사한다
(cd "$REPO/skills/operator" && tar cf - --exclude evals --exclude __pycache__ --exclude '*.pyc' .) | (cd "$PLUG.new/skill" && tar xf -)
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
  HERMES_HOME="$TARGET" hermes plugins enable operator || echo "  ! 'hermes plugins enable operator' 실패. 직접 실행한다: HERMES_HOME=\"$TARGET\" hermes plugins enable operator"
else
  echo "  i hermes 가 없어 활성화는 건너뛴다. config.yaml 의 plugins.enabled 에 operator 를 넣는다."
fi

# 복사해 온 프로필에 예전 위치(다른 프로필)의 operator 셸 훅이 있으면 이 프로필의 op.py 로 고친다.
if [ -f "$TARGET/config.yaml" ] && grep -q 'guard --format hermes' "$TARGET/config.yaml" 2>/dev/null; then
  for cand in $(which -a python3 2>/dev/null) python3; do
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
      HERMES_HOME="$TARGET" "$cand" -I "$PLUG/setup_wizard.py" --repair-hook --home "$TARGET" && break
    fi
  done
fi

# operator 명령: 기본 HERMES_HOME(~/.hermes) 이면 프로필 default, 프로필 설치면 그 프로필. 시험용 --home 은 만들지 않는다.
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
  [ -n "$PYTHON_BIN" ] || { echo "  ! 실행되는 python3(3.8+)를 찾지 못해 operator 명령을 만들지 않았다."; COMMAND=0; }
fi
if [ "$COMMAND" = 1 ] && [ -n "$CMD_PROFILE" ] && command -v hermes >/dev/null 2>&1; then
  if [ "$CMD_PROFILE" = default ]; then REINSTALL_ARGS="--home $HOME/.hermes"; else REINSTALL_ARGS="--profile $CMD_PROFILE"; fi
  cat > "$BIN_DIR/operator" <<WRAP
#!/bin/sh
# operator — Operator(Hermes 배포판) 명령. operator-skill 의 install.sh 가 만들었다.
#   operator setup            Hermes 기본 설정 → operator 단계 (Hermes 마법사와 같은 화면)
#   operator setup --hermes   원래 Hermes 설정 마법사만
#   operator setup --operator-only   Hermes 기본 설정을 건너뛰고 operator 단계만
#   operator setup model 등   Hermes 설정의 한 단계
#   operator update           Hermes 와 operator 를 함께 최신으로 (operator 는 $REPO 에서 받아 다시 설치)
#   그 밖의 모든 명령         hermes -p $CMD_PROFILE 로 전달 (operator chat, operator gateway restart …)
if [ "\${1:-}" = "setup" ] && { [ \$# -eq 1 ] || [ "\${2:-}" = "--hermes" ] || [ "\${2:-}" = "--operator-only" ]; }; then
  shift
  exec "$PYTHON_BIN" -I "$PLUG/setup_wizard.py" --profile "$CMD_PROFILE" "\$@"
fi
if [ "\${1:-}" = "update" ] && [ \$# -eq 1 ]; then
  echo "Hermes Agent 업데이트"
  "$HERMES_BIN" update || echo "! Hermes 업데이트에 실패했다. 나중에 hermes update 를 다시 실행해 주세요."
  if [ -d "$REPO/.git" ]; then
    echo "operator 업데이트 ($REPO)"
    G=""
    for g in \$(which -a git 2>/dev/null) /Library/Developer/CommandLineTools/usr/bin/git /opt/homebrew/bin/git; do
      [ -x "\$g" ] && "\$g" --version >/dev/null 2>&1 && { G=\$g; break; }
    done
    if [ -n "\$G" ]; then "\$G" -C "$REPO" pull --ff-only -q || echo "! operator 를 최신으로 받지 못했다 (로컬 변경이 있으면 직접 정리)"; fi
  fi
  exec sh "$REPO/hermes/operator/install.sh" $REINSTALL_ARGS
fi
exec "$HERMES_BIN" -p "$CMD_PROFILE" "\$@"
WRAP
  chmod +x "$BIN_DIR/operator"
  echo "  + 명령:     $BIN_DIR/operator  (operator setup = Operator 설정 마법사)"
fi

cat <<MSG

설치 완료. 다음:
  1. 메신저로 승인하려면 이 프로필의 게이트웨이에 텔레그램 등을 연결하고 허용 사용자(TELEGRAM_ALLOWED_USERS)를 본인으로 한다.
  2. (선택) 셸 훅도 걸어 두면 플러그인이 꺼져도 막는다: $PLUG/config.example.yaml 의 hooks 부분.
  3. 터미널에서: operator setup   (Hermes 기본 설정 → 프로젝트 폴더, 승인 방식, 메신저 허용 사용자, 두 번째 잠금)
  4. Hermes 앱 새 대화에서: /idea 동네 빵집 예약 페이지
MSG
