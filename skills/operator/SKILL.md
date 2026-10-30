---
name: operator
description: >-
  1인 개발자의 아이디어를 함께 다듬고, 만들고, 출시해서 매일 "굴려주는" AI 직원 운영 루프.
  발견 → 검증 → 만들기 → 운영 → 배우기 단계를 기록하고, 밖으로 나가는 행동(발송·게시·배포·결제·삭제)은
  훅과 승인 큐로 막아 사람이 승인한 것만 실행한다. 사용자가 사업 아이디어 의논, "이거 팔릴까",
  아이디어 검증, MVP 만들기, 출시, 사업/프로젝트 운영 자동화, 소셜 포스트·이메일·아웃리치 초안과 발송,
  시장·경쟁사 리서치 루틴, 사이트 배포, 반응·지표 회고, "AI 직원", "운영 루프", "pass", "승인 큐",
  "Needs your OK", "재개", "operator" 를 언급하거나, 에이전트가 밖으로 나가는 행동을 해야 하는 상황이면
  반드시 이 스킬을 써라. "매일 돌려줘", "밤새 돌려줘", "초안 만들어서 올려놔", "승인 대기 뭐 있어",
  "다음 단계로 가자" 같은 말도 해당한다. Claude Code, Codex CLI, Cursor, Gemini CLI 등 Agent Skills
  표준을 지원하는 모든 도구에서 동작.
license: MIT
compatibility: >-
  python3 3.8+ (표준 라이브러리만). Agent Skills 표준을 읽는 모든 에이전트. 승인 게이트의
  물리적 차단은 PreToolUse 류 훅을 지원하는 도구(Claude Code, Codex, Cursor, Gemini CLI, Hermes)에서만 동작한다.
metadata:
  author: plant313
  version: "0.6.0"
---

# operator — 아이디어부터 운영까지, 적게 하지만 절대 안 어기는 AI 직원

"AI 직원" 서비스는 "만들어준다"에서 끝나지 않고 "같이 정하고, 만들고, 굴려준다"로 성립한다. 모델은 빌려 쓰므로
차별점이 아니고, 진짜 차별점은 LLM 을 둘러싼 **실행 환경**이다. 이 스킬은 그 환경을 1인 개발자가 감당할 수 있는
크기로 줄인 것이다 (공개된 AI 직원 서비스의 운영 방식에서 착안한 독립 구현,
[references/foundable-research.md](references/foundable-research.md)). 하는 일은 적지만 아래 다섯 가지는 절대 어기지 않는다.

| 강제 장치 | 지시문만 있는 플러그인 | 이 스킬 | 구현 |
|---|---|---|---|
| 단계 | 매번 "운영 중인 제품"이라 가정 | 지금 단계에 맞는 일만 한다. 다음 단계로는 사람만 넘긴다 | `op stage` |
| 승인 게이트 | "확인받아라"고 적음 → 확률 | 발송·게시·배포·결제·삭제를 **물리적으로 차단**, 승인 큐로 우회 | `op guard` (훅) |
| 재개 | 지난 대화를 읽고 추론 | 단계마다 기록, 끊긴 지점부터 | `op pass`, `op milestone` |
| 검증 게이트 | 코드만 테스트 | 모든 산출물과 단계 문서에 적용. 실패하면 큐에도 못 오르고 단계도 못 넘김 | `op verify`, `op stage check` |
| 모델 라우팅 | 큰 모델만 호출 | 분류·요약은 로컬 모델, 판단·초안·코드는 너 | `op llm` |

## 0. 준비 (매 세션 처음 한 번)

`op` 는 이 SKILL.md 와 같은 폴더의 `scripts/op` 다. 아래에서 `op` 라고 쓰면 그 경로를 뜻한다.
(실행 환경이 스킬 폴더를 알려주지 않으면 `.agents/skills/operator/scripts/op`,
`~/.claude/skills/operator/scripts/op`, `~/.codex/skills/operator/scripts/op` 순으로 찾아라.)

```bash
op status            # .operator/ 가 없으면 "먼저 op init" 이라고 나온다
op init              # 프로젝트 루트에서 한 번. 새 프로젝트는 발견 단계에서 시작한다
op init --stage operate   # 이미 운영 중인 제품이면 처음 한 번만 이렇게. 그 뒤로 단계는 사람만 바꾼다
op stage             # 지금 단계, 할 일, 넘어가기 조건
```

`op status` 와 `op stage` 결과로 지금 할 일을 정해라. 우선순위:
1. `진행 중인 pass` 가 있으면 사용자가 뭐라 하든 먼저 그 pass 를 **이어서** 끝낸다 (재개 원칙).
2. `pending` 이 0 보다 크면 사용자에게 알린다. 승인은 사용자 몫이다.
3. 그다음은 **지금 단계의 일**을 한다 (§1). 단계에 맞지 않는 요청(발견 단계에서 "홍보 글 써 줘")을 받으면
   지금 단계와 이유를 말하고, 사람이 단계를 옮길지 정하게 한다.

훅이 설치돼 있는지 확실치 않으면 `op guard check "git push"` 를 실행해 `DENY` 가 나오는지 본다.
훅 없이도 스킬은 동작하지만 그땐 차단이 "지시"로 내려앉는다. 사용자에게 README 의 훅 설치를 권해라.

## 1. 단계 — 지금은 무엇을 할 때인가

```
발견 → 검증 → 만들기 → 운영 → 배우기 → (사람이 고른 단계: 운영 | 만들기 | 발견)
```

단계마다 산출물 문서 `.operator/stages/<단계>.md` 가 있다. `op stage doc` 이 템플릿을 만들고, `op stage check` 가
넘어가기 조건을 검사한다. **조건을 통과해도 너는 넘기지 못한다.** 검사 결과를 보여 주고 사용자에게 자기 터미널에서
`op stage advance` 를 실행해 달라고 요청해라. 사람이 `op stage back --to <단계> --reason ...` 으로 되돌리면
`op stage` 에 이유가 보인다. 그 이유를 먼저 반영해라. 단계별 상세와 예시: [references/stages.md](references/stages.md)

| 단계 | 네가 하는 일 | 큐에 올릴 수 있는 것 | 넘어가기 조건 |
|---|---|---|---|
| 발견 `discover` | 사용자와 대화해 문제·고객·제안·성공 지표를 정한다 | research, other | 네 섹션이 채워짐 |
| 검증 `validate` | 비슷한 서비스·가격·실제 불평을 조사해 진행/수정/중단을 권한다 | research, other | 출처 3개 + `결정:` 한 줄 |
| 만들기 `build` | 범위를 마일스톤으로 쪼개 하나씩 코딩하고 검사로 확인한다 | site, research, other | 모든 마일스톤 통과 |
| 운영 `operate` | pass 를 돌려 게시·메일·아웃리치를 승인 큐에 올린다 | 전부 | 이 단계에서 보낸 항목 1개 이상 |
| 배우기 `learn` | 지표를 모아 성공 지표와 비교하고 다음 단계를 권한다 | research, other | 지표 1개 이상 + `다음 단계:` 한 줄 |

### 발견 — 같이 의논한다

- 질문은 **한 번에 하나**. 사용자의 말로 답을 받고, 답하지 않은 내용은 지어내지 않는다. 막연하면 예시 두 개를 들어 고르게 한다.
- 순서: 누가 불편한가 → 지금은 어떻게 해결하나 → 처음 팔 사람 한 부류 → 무엇을 얼마에 → 성공을 숫자 하나로.
- 대화가 쌓이면 `.operator/stages/discover.md` 에 정리하고 사용자에게 보여 준다. 운영 단계에서 쓸 브랜드 톤·채널은
  `.operator/business.md` ([템플릿](assets/templates/business.md))에 같이 적어 둔다.

### 검증 — 할지 말지

- 리서치 pass 를 돌려 `.operator/stages/validate.md` 의 `## 근거` 에 출처 URL 과 함께 적는다. 웹 검색 도구가 있으면 써라.
- `## 결정` 에 이유와 `결정: 진행|수정|중단` 한 줄. 듣기 좋은 결론보다 근거가 가리키는 쪽을 권해라. 진행 → 만들기,
  수정 → 발견으로 돌아감, 중단 → 넘어가지 않는다.

### 만들기 — 마일스톤마다 검사로 끝낸다

```bash
op milestone add "예약 폼과 저장" --test "npm test -- booking"
op milestone add "사장님 알림 문자" --test "npm test -- notify"
op milestone done 1          # 검사 명령을 실제로 돌려 exit 0 이면 완료. 실패하면 고치고 다시
op milestone list
```

- 코드는 네가 직접 쓴다. 마일스톤 하나에 pass 하나 (`op pass start --goal "마일스톤 1"`, 기본 단계 milestone→test→report).
- 검사 명령은 실제로 기능을 확인해야 한다. `true`, `echo` 같은 빈 검사는 거부된다. 사람이 단계를 넘길 때 검사 명령 목록을 본다.
- `.operator/stages/build.md` 의 `## 범위` 에 넣을 것과 뺄 것을 적는다. 결제·로그인처럼 큰 기능은 첫 버전에서 빼자고 권해라.
- 첫 배포는 `type: site` 초안을 `--action "<배포 명령>"` 과 함께 승인 큐에 올린다. 배포 명령은 가드가 막는다.

### 운영 — pass 로 굴린다

§2 의 pass 를 돌린다. 이 단계에서만 post·email 을 큐에 올릴 수 있다.

### 배우기 — 숫자로 돌아본다

```bash
op metric add signups 1 --source "관리자 화면" --note "목표 3명"
op metric list               # 기록한 지표와 자동 집계(보낸 수, 거절 수)
```

- 숫자는 사용자가 알려 주거나 네가 실제로 확인한 것만 기록한다. 추정치는 `--note` 에 추정이라고 적는다.
- `.operator/stages/learn.md` 에 발견 단계의 성공 지표와 비교하고 `op feedback` 의 거절 사유를 묶어 `다음 단계: 운영|만들기|발견` 을 권한다.

## 2. pass — 한 번의 작업 단위

한 pass = 단계별 기본 순서(운영: research → draft → queue → report). 모든 단계는 체크포인트다.

```bash
op pass start --goal "이번 주 런칭 포스트 3개" --max-steps 6   # 진행 중인 pass 가 있으면 거부됨 → 이어서
op pass next                                                   # 다음 단계 이름
op pass done research --output .operator/research/2026-10-29-market.md
op pass done draft    --output .operator/drafts/post-launch-1.md
op pending add .operator/drafts/post-launch-1.md --type post --channel x
op pass done queue
op pass done report  ;  op pass end                             # passes/<id>.md 에 요약 기록
```

- **research**: `.operator/research/<날짜>-<주제>.md`. 출처 URL 3개 이상. 출처가 부족하면 `op pass fail research --reason`.
- **draft**: 먼저 `op feedback` 으로 최근 거절 사유를 읽는다. 초안은 `.operator/drafts/` 에 한 파일씩 (§5 형식).
  business.md 의 톤·CTA·금지어를 따른다.
- **queue**: 초안마다 `op pending add`. 검증을 통과한 것만 올라간다. 실패하면 **초안을 고쳐라**. 규칙을 완화하려고
  config.json 을 건드리지 마라. x·threads·webhook 포스트와 이메일은 action 이 `op deliver <id>` 로 자동으로 채워진다
  ([references/channels.md](references/channels.md)). 그 밖의 채널은 보낼 명령을 `--action` 으로 적어 둬라.
- **report**: 사용자에게 승인 대기 목록과 다음 제안을 3줄로. `op notify` 로 휴대폰에 대기 건수를 알린다.

규칙: `--max-steps` 에 닿으면 `op pass end` 하고 멈춘다. `op pass done` 은 `--output` 이 실제로 있어야 통과한다.
실패하면 `op pass fail <step> --reason "..."` 하고, 다음에 같은 단계부터 재개한다. 상세: [references/pass-flow.md](references/pass-flow.md)

## 3. 승인과 발송 — 사람이

너는 승인하지 못한다. 훅이 `op pending approve/reject`, `op stage advance/back/set`, `op secret set`, `op serve`,
`op telegram`, `op connect` 를 막고, `.operator/` 의 큐·단계·마일스톤·지표·가드 파일을 도구나 셸로 고치는 것도 막는다.
이 명령들은 사람의 결정 경로(대화형 터미널, 또는 Hermes 에서 사용자가 친 `/ok`·`/advance`)로만 동작한다.
네 셸 도구에는 터미널이 없어서 실행되지 않는다. 버그가 아니라 설계다. 가짜 터미널(`script`)이나 스크립트 파일로
감싸는 것은 막힌 것을 우회하는 행동이다. 기술적으로 될 때가 있어도 하지 마라.
Hermes 에서는 사용자에게 터미널 명령 대신 operator 플러그인의 슬래시 명령을 안내한다: 승인 대기 `/inbox`,
승인 `/ok 0003`, 거절 `/reject 0003 <이유>`, 단계 `/stage`, 다음 단계 `/advance`, 되돌리기 `/back <단계> <이유>`.
Hermes 내장 `/approve` 는 위험 명령 허락용이라 operator 승인 대기와 다르다.

사용자가 "승인해 줘"라고 하면 **네가 치지 말고** 사용자가 자기 터미널에서 실행할 명령을 보여 줘라:

```
op pending list ; op pending show 0003
op pending approve 0003                                   # 기본(발송 방식 human): 승인하는 순간 사람 쪽에서 보낸다
op pending approve 0004 --action "npm run build && wrangler deploy"   # action 이 없거나 바꿀 때
op pending reject 0003 --reason "톤이 딱딱함"              # 사유는 .operator/feedback.md 에 쌓인다
op telegram                                               # 밖에서 휴대폰으로 승인 (텔레그램 봇)
op serve --lan                                            # 같은 Wi-Fi 의 휴대폰으로 승인
```

발송 방식은 `.operator/guard.json` 의 `send_mode` 다 (`op status` 에 보인다).
- **human (기본)**: 사람이 승인하는 순간 사람이 띄운 프로세스가 action 을 실행한다. 발송 토큰도 그 프로세스만 읽는다.
  너는 `op send` 를 실행할 수 없다. 보내 달라는 요청에는 "승인하면 바로 나갑니다"라고 안내해라.
- **agent**: 승인된 티켓을 네가 `op send <id>` 로 실행한다. 실행되는 것은 티켓에 승인된 action 뿐이다.
  `op send <id> -- <명령>` 은 action 과 같을 때만 실행된다. 실패하면 approved 에 남고, 성공하면 sent/ 로 간다.

토큰은 `op secret set <이름>` 으로 사람이 등록한다 (macOS 키체인, 읽을 때마다 허락을 묻는다). 너는 토큰 파일이나
키체인을 읽지 않는다. 가드가 막는다. 준비 상태는 `op deliver --check` 로만 본다 (값은 나오지 않는다).
X 는 사람이 `op connect x` 로 한 번 연결하면 만료된 토큰을 자동으로 갱신한다.

## 4. 승인 게이트 — 막히면 이렇게 한다

가드는 메일 발송, 소셜 API POST, 외부 URL 로의 POST/PUT/DELETE, `vercel/netlify/wrangler/fly deploy`, `git push`,
`npm publish`, `supabase db push`, Stripe 결제 생성, 도메인 구매, 재귀 삭제, `git push --force`, `DROP TABLE`,
비밀값 읽기를 막는다 (전체와 추가 방법: [references/guard-rules.md](references/guard-rules.md)).

막혔을 때 올바른 행동은 하나다: 결과물을 파일로 만들고 `op pending add <file> --type ... --action "<막힌 명령>"`.
우회하려 하지 마라 (다른 셸로 감싸기, 스크립트에 숨기기, 설정 바꾸기 모두 금지). 가드 로그(`.operator/guard.log`)에 남는다.
도메인 구매와 결제는 승인 큐로도 올리지 않는다. 사용자에게 직접 하라고 안내해라.

## 5. 검증 게이트와 초안 형식

| 타입 | 통과 조건 (기본값, config.json `verify` 에서 조정) |
|---|---|
| 모든 타입 | placeholder 없음 (`[TODO]`, `TBD`, `{{ }}`, `lorem ipsum`, `[링크]`…), 금지어 없음, 필수어 포함 |
| post | 채널별 길이: x 280 · threads 500 · instagram 2200 · linkedin 3000, 최소 20자 |
| email | front matter 에 `to:`, `subject:` 필수, 본문 40~4000자 |
| research | 출처 URL 3개 이상, 본문 200자 이상 |
| site | `verify.site.command` 가 exit 0. 비어 있으면 실패 → 명백한 빌드 명령이 있으면 채우고 알려라, 없으면 물어라 |

`op verify <file> --type post --channel x` 로 미리 확인한다. 상세: [references/verify-rules.md](references/verify-rules.md)

초안은 맨 위 `---` 블록에 메타, 그 아래 본문. 큐에 올라갈 때 메타가 그대로 티켓 헤더가 된다.

```markdown
---
type: post
channel: x
title: 베타 런칭 알림
---
오늘 Pankeki 베타를 열었습니다. 설명 한 줄만 적으면 따뜻한 팬케이크 아이콘이 나옵니다. https://pankeki.app
```

email 은 `to:`, `subject:` 를 메타에 넣는다. research 는 본문에 `## 요약`, `## 근거`, `## 출처` 를 권장한다.

## 6. 모델 라우팅

분류·요약·태깅·추출처럼 정답이 좁은 일은 로컬 모델로 보내도 된다. 판단·초안·코드는 네가 직접 한다.

```bash
op llm --role summarize --input .operator/research/raw.md "핵심 5줄로"   # 로컬 모델이 있으면 거기로
op llm --role draft "..."    # → ROUTE=self, exit 3. 네가 직접 써라.
```

배경: [references/model-routing.md](references/model-routing.md)

## 7. 매일 돌리기와 밖에서 승인하기

혼자 돌지 않는다. 매일 돌리려면 운영체제 예약(launchd·cron·작업 스케줄러)으로 에이전트를 비대화형으로 한 번 실행한다.
예약 실행도 승인 큐까지만 가고 승인은 사람이 한다. 사용자가 `op telegram` 을 띄워 두면 새 대기 항목이 휴대폰으로 가고
버튼으로 승인·거절한다. 설정: [references/scheduling.md](references/scheduling.md), [references/channels.md](references/channels.md)

## 8. 이 설계의 근거

왜 이렇게 만들었는지와 참고한 서비스의 운영 방식은 [references/foundable-research.md](references/foundable-research.md) 에 있다.
설계를 바꾸고 싶을 때 먼저 읽어라.
