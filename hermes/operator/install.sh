#!/bin/sh
# operator 를 Hermes Agent 의 "전용 사업 비서" 프로필로 설치한다. Hermes 코드는 건드리지 않는다.
#
#   sh hermes/operator/install.sh                    # 프로필 'operator' 를 만들고(없으면) 플러그인·스킬·성격을 넣는다
#   sh hermes/operator/install.sh --profile 이름      # 다른 프로필 이름
#   sh hermes/operator/install.sh --home 폴더         # 이 HERMES_HOME 에 바로 설치 (프로필을 만들지 않음, 시험용)
#   sh hermes/operator/install.sh --no-soul           # 프로필의 SOUL.md 는 그대로 둔다
#
# 하는 일: <HERMES_HOME>/plugins/operator/ 에 플러그인을 복사하고, 그 안의 skill/ 에 operator 스킬을 복사한다.
# SOUL.md 는 원래 것을 SOUL.md.bak-날짜 로 남긴 뒤 바꾼다. 마지막에 `hermes plugins enable operator` 를 실행한다.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
PROFILE=operator
TARGET=""
SOUL=1
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE=$2; shift 2 ;;
    --home) TARGET=$2; shift 2 ;;
    --no-soul) SOUL=0; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "모르는 옵션: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$TARGET" ]; then
  command -v hermes >/dev/null 2>&1 || { echo "hermes 명령을 찾지 못했다. Hermes Agent 를 먼저 설치한다."; exit 1; }
  TARGET="$HOME/.hermes/profiles/$PROFILE"
  if [ ! -d "$TARGET" ]; then
    echo "프로필 '$PROFILE' 을 만든다 (hermes profile create $PROFILE)"
    hermes profile create "$PROFILE"
  fi
fi
mkdir -p "$TARGET/plugins"
PLUG="$TARGET/plugins/operator"

rm -rf "$PLUG.new"
mkdir -p "$PLUG.new/skill"
for f in __init__.py commands.py plugin.yaml SOUL.md config.example.yaml; do cp "$HERE/$f" "$PLUG.new/$f"; done
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

cat <<MSG

설치 완료. 다음:
  1. 메신저로 승인하려면 이 프로필의 게이트웨이에 텔레그램 등을 연결하고 허용 사용자(TELEGRAM_ALLOWED_USERS)를 본인으로 한다.
  2. (선택) 셸 훅도 걸어 두면 플러그인이 꺼져도 막는다: $PLUG/config.example.yaml 의 hooks 부분.
  3. 대화창에서: /setup  →  /idea 동네 빵집 예약 페이지
MSG
