---
name: operator
description: >-
  1인 개발자의 사업·프로젝트를 AI 직원처럼 "굴려주는" 운영 루프. "AI 직원" 서비스가
  인프라로 강제하는 네 가지(승인 게이트, 재개 가능한 pass, 검증 게이트, 모델 라우팅)를
  셸 스크립트와 JSON 파일로 옮긴 것이다. 사용자가 사업/프로젝트 운영 자동화, 소셜 포스트·
  이메일·아웃리치 초안과 발송, 시장·경쟁사 리서치 루틴, 사이트 배포, "AI 직원", "운영 루프",
  "pass", "승인 큐", "Needs your OK", "재개", "operator" 를 언급하거나, 에이전트가 밖으로 나가는 행동(발송·게시·배포·
  결제·삭제)을 해야 하는 상황이면 반드시 이 스킬을 써라. 명시적으로 "스킬"이라 말하지 않아도,
  "매일 돌려줘", "밤새 돌려줘", "초안 만들어서 올려놔", "승인 대기 뭐 있어" 같은 말도 해당한다.
  Claude Code 외에 Codex CLI, Cursor, Gemini CLI 등 Agent Skills 표준을 지원하는 모든 도구에서 동작.
license: MIT
compatibility: >-
  python3 3.8+ (표준 라이브러리만). Agent Skills 표준을 읽는 모든 에이전트. 승인 게이트의
  물리적 차단은 PreToolUse 류 훅을 지원하는 도구(Claude Code, Codex, Cursor, Gemini CLI)에서만 100%.
metadata:
  author: plant313
  version: "0.2.0"
---

# operator — 적게 하지만 절대 안 어기는 운영 루프

"AI 직원" 서비스는 "만들어준다"가 아니라 "굴려준다"로 성립한다. 모델은 빌려 쓰므로 차별점이
아니고, 진짜 차별점은 LLM 을 둘러싼 **실행 환경**이다. 이 스킬은 그 환경을 1인 개발자가
감당할 수 있는 크기로 줄인 것이다 (Foundable 의 공개된 운영 방식에서 착안한 독립 구현이며,
해당 회사와 무관하다. 분석은 [references/foundable-research.md](references/foundable-research.md)). 하는 일은 적지만 아래 네 가지는 절대 어기지 않는다.

| 강제 장치 | 기존 플러그인 ("지시문 더미") | 이 스킬 | 구현 |
|---|---|---|---|
| 승인 게이트 | "확인받아라"고 적음 → 확률 | 발송·게시·배포·결제·삭제 명령을 **물리적으로 차단**, 승인 큐로 우회 → 100% | `op guard` (훅) |
| 재개 | 지난 대화 읽고 추론해서 이어감 | 단계마다 `state.json` 에 기록, 다음 단계부터 실행 | `op pass` |
| 검증 게이트 | 코드만 테스트 | 모든 산출물에 적용. 실패하면 승인 큐에도 못 올라감 | `op verify` (큐 등록 시 자동) |
| 모델 라우팅 | Claude 만 호출 | 분류·요약은 로컬 모델, 판단·초안·코드는 너 | `op llm` |

밖으로 나가는 것은 100% 사람 손을 거치고, 끊겨도 처음부터 하지 않는다. 이게 이 스킬의 전부다.

## 0. 준비 (매 세션 처음 한 번)

`op` 는 이 SKILL.md 와 같은 폴더의 `scripts/op` 다. 아래에서 `op` 라고 쓰면 그 경로를 뜻한다.
(실행 환경이 스킬 폴더를 알려주지 않으면 `.agents/skills/operator/scripts/op`,
`~/.claude/skills/operator/scripts/op`, `~/.codex/skills/operator/scripts/op` 순으로 찾아라.)

```bash
op status            # .operator/ 가 없으면 "먼저 op init" 이라고 나온다
op init              # 프로젝트 루트에서 한 번. .operator/{pending,approved,sent,passes,...} 생성
```

`op status` 결과로 지금 어느 모드인지 판단해라:
- `business.md: 없음` → **plan** 부터
- `진행 중인 pass` 가 있음 → 사용자가 뭐라 하든 먼저 그 pass 를 **이어서** 끝낸다 (재개 원칙)
- `pending: N` 이 0 보다 큼 → 사용자에게 알려라. 승인은 사용자 몫이다.

훅이 설치돼 있는지 확실치 않으면 `op guard check "git push"` 를 실행해 `DENY` 가 나오는지 본다.
훅 없이도 스킬은 동작하지만 그땐 차단이 "지시"로 내려앉는다. 사용자에게 README 의 훅 설치를 권해라.

## 1. 모드

### plan — 아이디어 한 문장 → `.operator/business.md`

사용자의 아이디어를 받아 사업/프로젝트의 정체를 한 파일로 고정한다. 이후 모든 초안은 이 파일을
근거로 쓴다. 템플릿은 [assets/templates/business.md](assets/templates/business.md).

1. 모르는 건 짧게 물어라: 타깃 고객 1문장, 채널(x/threads/linkedin/instagram/email 중), 톤, 쓰면 안 되는 말.
2. `.operator/business.md` 를 템플릿대로 작성. 이름·한 줄 소개·타깃·브랜드 톤·채널·CTA·금지어.
3. `.operator/config.json` 의 `verify.required_words`(브랜드명 등), `verify.banned_words`, 사이트가 있으면
   `verify.site.command`(예: `npm run build`) 를 채운다. 검증 게이트는 여기서 읽는다.

### run — pass 한 번 돌리기

AI 직원은 "pass" 단위로 돌아간다. 한 pass = 리서치 → 초안 → 검증 → 승인 대기. 모든 단계는 체크포인트다.

```bash
op pass start --goal "이번 주 런칭 포스트 3개" --max-steps 6   # 진행 중인 pass 가 있으면 거부됨 → 이어서
op pass next                                                   # 다음 단계 이름 (research|draft|queue|report)
#   ...단계 수행...
op pass done research --output .operator/research/2026-10-29-market.md
op pass done draft    --output .operator/drafts/post-launch-1.md
op pending add .operator/drafts/post-launch-1.md --type post --channel x --action "curl -X POST https://api.x.com/2/tweets ..."
op pass done queue
op pass done report  ;  op pass end                             # passes/<id>.md 에 요약 기록
```

단계별로 할 일:
- **research**: 시장·경쟁사·트렌드를 `.operator/research/<날짜>-<주제>.md` 에. 출처 URL 3개 이상 (검증 규칙).
  웹 검색 도구가 있으면 써라. 없으면 아는 범위에서 쓰되 "출처 부족"을 명시하고 `op pass fail research --reason` 로 기록.
- **draft**: 포스트·이메일 초안을 `.operator/drafts/` 에 한 파일씩. 형식은 아래 §4. business.md 의 톤·CTA·금지어를 따른다.
- **queue**: 초안마다 `op pending add`. 검증을 통과한 것만 올라간다. 실패하면 **초안을 고쳐라**. 규칙을 완화하려고
  config.json 을 건드리지 마라 (그건 사용자 결정). 예외는 비어 있는 값을 채우는 것뿐이다 (예: `verify.site.command`).
  실제로 보낼 명령을 알면 `--action` 으로 같이 적어 둬라. 승인 후 그대로 실행된다.
- **report**: `op pass end` 가 만드는 요약에 더해, 사용자에게 **승인 대기 목록**과 다음 pass 제안을 3줄로.

규칙:
- `--max-steps` 는 원형 서비스의 크레딧 상한에 해당한다. 상한에 닿으면 `op pass end` 하고 멈춘다. 더 하고 싶으면 사용자가 새 pass 를 시킨다.
- `op pass done` 은 `--output` 경로가 실제로 존재해야 통과한다. 산출물 없이 "했다"고 적을 수 없다.
- 중간에 실패하면 `op pass fail <step> --reason "..."`. 다음에 같은 단계부터 재개된다. 처음부터 다시 하지 않는다.
- 세션이 끊겨도 `state.json` 이 남는다. 새 세션은 `op status` → `op pass next` 로 **그 지점에서** 이어 간다.

자세한 흐름과 예시 세션: [references/pass-flow.md](references/pass-flow.md)

### approve — 승인은 사람이

너는 승인하지 못한다. 훅이 `op pending approve/reject` 를 막고, `.operator/pending/` 아래 파일 편집도 막는다.
이건 버그가 아니라 설계다 ("승인은 당신이").

```bash
op pending list              # 대기 목록
op pending show 0003         # 내용
```

사용자가 "승인해 줘"라고 하면 **네가 approve 명령을 치지 말고**, 사용자가 자기 터미널에서 실행할 명령을 보여줘라:

```
op pending approve 0003        # 또는  op pending reject 0003 --reason "톤이 딱딱함"
```

승인된 티켓은 `op send <id> -- <명령>` 으로 실제 발송·게시·배포한다. 이때만 가드가 통과시킨다.
명령이 실패하면 티켓은 approved 에 남고, 성공하면 sent/ 로 이동한다. 재시도 가능.

```bash
op send 0003 -- curl -X POST https://api.x.com/2/tweets -H "..." -d @.operator/approved/0003-post-....md
op send 0004 --shell -- "npm run build && wrangler deploy"
```

### status — 현황 보고

`op status` + `op pending list` 결과를 사람 말로 4줄 이내: 진행 중인 pass, 승인 대기 수, 최근 sent, 다음 제안.

## 2. 승인 게이트 — 막히면 이렇게 한다

가드는 다음을 막는다 (전체 목록과 추가 방법: [references/guard-rules.md](references/guard-rules.md)):
메일 발송, 소셜 API POST, 외부 URL 로의 POST/PUT/DELETE, `vercel/netlify/wrangler/fly deploy`, `git push`,
`npm publish`, `supabase db push`, Stripe 결제 생성, 도메인 구매, `rm -rf`, `git push --force`, `DROP TABLE`.

막혔을 때 올바른 행동은 하나다: 그 결과물을 파일로 만들고 `op pending add <file> --type ... --action "<막힌 명령>"`.
우회하려 하지 마라 (다른 셸로 감싸기, 스크립트에 숨기기, 설정 바꾸기 모두 금지). 가드 로그(`.operator/guard.log`)에 남는다.

도메인 구매와 결제는 승인 큐로도 올리지 않는다. 원형 서비스도 AI 에게 아예 못 하게 했다. 사용자에게 직접 하라고 안내.

## 3. 검증 게이트 — 산출물 타입별 규칙

| 타입 | 통과 조건 (기본값, config.json `verify` 에서 조정) |
|---|---|
| 모든 타입 | placeholder 없음 (`[TODO]`, `TBD`, `{{ }}`, `lorem ipsum`, `[링크]`…), 금지어 없음, 필수어 포함 |
| post | 채널별 길이: x 280 · threads 500 · instagram 2200 · linkedin 3000, 최소 20자 |
| email | front matter 에 `to:`, `subject:` 필수, 본문 40~4000자 |
| research | 출처 URL 3개 이상, 본문 200자 이상 |
| site | `verify.site.command` 가 exit 0. 비어 있으면 실패한다 → package.json 등에 명백한 빌드 명령이 있으면 그걸 채우고 사용자에게 알려라, 없으면 물어라 |

`op verify <file> --type post --channel x` 로 미리 확인할 수 있다. 상세: [references/verify-rules.md](references/verify-rules.md)

## 4. 초안 파일 형식

파일 맨 위 `---` 블록에 메타, 그 아래 본문. 큐에 올라갈 때 이 메타가 그대로 티켓 헤더가 된다.

```markdown
---
type: post
channel: x
title: 베타 런칭 알림
action: curl -X POST https://api.x.com/2/tweets -H "Authorization: Bearer $X_TOKEN" -d @-
---
오늘 Pankeki 베타를 열었습니다. 설명 한 줄만 적으면 따뜻한 팬케이크 아이콘이 나옵니다. https://pankeki.app
```

```markdown
---
type: email
to: hello@example.com
subject: Pankeki 베타 초대
---
안녕하세요, ...
```

research 는 `type: research`, 본문에 `## 요약`, `## 근거`, `## 출처` 세 섹션을 권장한다.

## 5. 모델 라우팅

분류·요약·태깅·추출처럼 정답이 좁은 일은 로컬 모델(맥미니 Ollama 등)로 보내도 된다.
판단·초안·코드는 네가 직접 한다. `op llm` 이 이 구분을 강제한다.

```bash
op llm --role summarize --input .operator/research/raw.md "핵심 5줄로"   # 로컬 모델이 있으면 거기로
op llm --role draft "..."    # → ROUTE=self, exit 3. 네가 직접 써라.
```

`ROUTE=self` 가 나오면 네가 한다. 로컬 모델이 없어도 아무것도 깨지지 않는다. 설정: `config.json` `routing`.
배경: [references/model-routing.md](references/model-routing.md)

## 6. 이 설계의 근거

왜 이렇게 만들었는지, 참고한 서비스가 실제로 어떻게 돌아가는지, 유사 프로젝트와의 차이는
[references/foundable-research.md](references/foundable-research.md) 에 있다. 설계를 바꾸고 싶을 때 먼저 읽어라.
