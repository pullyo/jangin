# 참고 서비스 분석 (Foundable) — 이 스킬의 설계 근거

Foundable(foundable.com, Autono Labs)의 공개 자료(홈·문서·보도·서브프로세서 목록·런칭 글)를 2026-10-29 에
정리한 것이다. 이 스킬은 그 운영 방식에서 착안한 **독립 구현**이며 해당 회사와 무관하다. 설계를 바꾸기 전에
읽는 파일이다.

## 1. Foundable 이 뭔가

"Ted" 라는 AI 직원이 아이디어 한 문장을 사업으로 세팅하고 **계속 운영**해주는 서비스(foundable.com,
Autono Labs, 2026-04 설립). 핵심은 "만들어준다"가 아니라 "굴려준다".

- **Build**: 이름·로고·브랜드·웹사이트·전용 이메일·백엔드 생성. 코드는 본인 GitHub 으로 동기화.
- **Run(Grow)**: Ted 가 백그라운드에서 pass 단위로 리서치, 고객 아웃리치, 소셜 포스트, 답장, 시트·피치덱,
  사이트 개선을 수행. **전부 승인 대기 상태로 올라옴**.
- **Earn**: 본인 명의 Stripe 연결, 수수료 없음.
- 접점: 웹/모바일 채팅, iMessage/SMS. Gmail·캘린더·Slack·Notion·HubSpot 연결.
- 과금: 크레딧제 (무료 15 + 매일 5). 크레딧이 떨어지면 "Paused — out of credits → Continue".

주의: foundable.ai(2020, GPT-3 기반)는 다른 회사다.

## 2. 기술 스택 — 자체 개발은 거의 없고 외부 SaaS 조립

| 영역 | 서비스 | 역할 |
|---|---|---|
| AI 모델 | OpenAI | 일반 대화, 온보딩, 리서치, 임베딩 |
| AI 모델 | Anthropic Claude | 유료 Run, Build 의 웹사이트 에이전트, Inbox 초안, 영상 구성 |
| AI 보조 | fal.ai / Perplexity / TypeSafe AI / Turbopuffer / Monid / Judgment Labs | 이미지 · 웹검색 · reasoning 라우터 · 장기기억 벡터 · 공개데이터 · 트레이스 |
| 에이전트 실행 | **Temporal Cloud** | Ted 턴, Build, 발송, 예약 실행을 durable workflow 로 |
| 에이전트 실행 | **Modal** | 격리 샌드박스, 영상 렌더링 |
| 에이전트 실행 | **Pierre Code Storage** | 사이트별 Git 저장소, GitHub 동기화 |
| 호스팅 | AWS ECS Fargate, Aurora, S3, CloudFront / Vercel / Cloudflare Workers+R2 / Supabase | API·워커 / 콘솔 / 사용자 사이트 / 사이트별 백엔드 |
| 인증·손발 | WorkOS / Composio / AgentMail / Linq / Zernio / Stripe | 로그인 / 외부 앱 액션 / 메일함 / iMessage / 소셜 게시 / 결제 |

모델 분담: 코드 생성과 자율 실행은 Claude, 일반 대화와 임베딩은 OpenAI.

## 3. 기술적 핵심 세 가지 (모델은 빌려 쓰므로 차별점이 아니다)

1. **재개 가능한 장시간 루프 (Temporal)**: pass 단위로 밤새 돈다. 서버가 죽거나 크레딧이 떨어지거나 승인을
   기다리느라 멈춰도 정확히 그 지점에서 재개. → 이 스킬의 `op pass` + `state.json`.
2. **격리 실행 + 검증 게이트 (Modal + Pierre + Cloudflare)**: 사이트마다 격리 샌드박스에서 빌드, 저장 전에
   테스트 통과. 실패하면 아무것도 안 바뀜. → 이 스킬의 `op verify` (모든 산출물로 확장).
3. **승인 게이트를 설계에 내장**: 이메일·포스트·사이트 변경은 전부 "Needs your OK" 큐. 도메인 구매와 결제는 AI 가
   아예 못 함. Run 의 "Ask first / On its own" 전환과 크레딧 상한(Power). → 이 스킬의 `op guard` + `pending/` + `--max-steps`.

Ted 의 한 pass: 리서치 → 초안 → **검증 게이트** → **승인 대기** → (사람 OK) → 밖으로. 모든 단계는 체크포인트.

## 4. 1인 개발 기준 활용 가능 기술

| 구분 | 기술 | 이유 |
|---|---|---|
| 바로 | Composio | OAuth 직접 안 짜고 외부 앱 연결. MCP 로 Claude Code·Codex 에 붙음 |
| 바로 | Supabase | Postgres + Auth + 스토리지 + RLS 한 번에 |
| 바로 | Cloudflare Workers + R2 | 정적 사이트·가벼운 서버, 무료 범위 넉넉 |
| 바로 | fal.ai | GPU 없는 맥미니에서 이미지 생성 |
| 바로 | Perplexity API | "웹 뒤져서 요약" 프로토타입 |
| 나중에 | Temporal | 러닝커브 높음. 먼저 **상태 파일 + cron** 으로 흉내 (← 이 스킬). 대안 Inngest, Trigger.dev |
| 나중에 | Modal | AI 생성 코드 격리 실행이 필요할 때 |
| 대체 | Turbopuffer → pgvector, Pierre → GitHub, Judgment Labs → Langfuse | |

## 5. 원래 플러그인 구상 (가칭 jangin)

```
jangin/
├ skills/ plan · build · run · approve · earn
├ agents/ researcher · writer · builder
├ hooks/hooks.json   ← 발송·배포·결제 명령 차단 → pending 으로 우회
└ .mcp.json          ← Composio, Supabase, Cloudflare
```

Foundable 과 다른 점(1인용이라 가능한 것): 돌아가는 건 run 을 칠 때뿐, 밤새 돌리려면 예약 실행 하루 한 번.
승인 UI 는 마크다운 파일. 크레딧 대신 "한 pass 에 최대 N 단계". 권장 순서: plan + run + approve 세 개만 먼저.

이 스킬은 그 구상을 **도구 비종속 Agent Skills 표준** 하나로 압축한 것이다. 서브에이전트·MCP 는 범위 밖이고,
방법론(네 가지 강제 장치)만 옮겼다.

## 6. 유사 프로젝트

| 저장소 | 성격 | 비고 |
|---|---|---|
| markfulton/ai-employees | 8개 역할 AI 직원, 60개 루틴 스케줄, 매일 아침 브리핑 | MIT. Run 과 가장 유사. 전부 마크다운 |
| claude-ops | 57 스킬 + 21 에이전트, 통합 인박스, 매출, 자율 PR 머지 | "Claude Code 를 사업 운영체제로" |
| Assistant-Labs/claude-plugin | 식어가는 리드 추적, 결정 필요한 것만 10초 선택지 | "승인은 당신이" 철학 |
| agent-session-resume / claude-queue / fstack | 재개 체크포인트 / 툴 호출 승인 큐 / 휴먼 게이트 | 부품 |
