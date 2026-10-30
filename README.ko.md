# operator

[English](README.md) · **한국어**

**적게 하지만 절대 규칙을 어기지 않는, AI 에이전트용 운영 루프.**
코딩 에이전트에게 작은 사업이나 사이드 프로젝트의 일상 운영(리서치 → 초안 → 게시·메일·배포)을 맡기세요.
내 컴퓨터 밖으로 나가는 행동은 전부 내 손을 거치고, 작업이 끊겨도 멈춘 단계부터 이어갑니다.

operator 는 [Agent Skill](https://agentskills.io) 과 의존성 없는 작은 파이썬 CLI(`op`)로 이뤄져 있습니다.
같은 폴더를 Claude Code, Codex CLI, Cursor, Gemini CLI 등 Agent Skills 형식을 읽는 도구에서 그대로 씁니다.

---

## 왜 만들었나

"AI 직원" 서비스가 매력적인 이유는 무언가를 *만들어* 주는 데서 끝나지 않고 계속 *굴려* 주기 때문입니다.
그런데 그 서비스를 안전하게 만드는 건 모델이 아니라 모델을 둘러싼 장치입니다. 승인, 체크포인트, 검증 같은 것들입니다.
대부분의 에이전트 플러그인은 모델에게 "먼저 확인받아"라고 *부탁*만 하고, 그 부탁은 대체로 지켜집니다.
operator 는 그 부탁을 에이전트가 우회할 수 없는 규칙으로 바꿉니다.

| operator 없이 | operator 와 함께 |
|---|---|
| 프롬프트에 "게시 전에 물어봐"라고 적음 (대체로 지켜짐) | 게시·메일·배포·결제·삭제를 **훅이 막고** 승인 큐로 보냄 |
| 에이전트가 대화를 다시 읽고 어디까지 했는지 추측 | 단계마다 `state.json` 에 기록하고, 새 세션은 정확히 그 단계부터 이어감 |
| 코드만 테스트 | 모든 결과물을 검증(포스트 길이, 빈칸 표시, 금지어, 출처, 빌드)하고 통과해야 큐에 올라감 |
| 모든 요청을 큰 모델로 | 분류·요약은 로컬 모델로 보낼 수 있고, 판단과 글쓰기는 에이전트가 맡음 |

1인 창업자와 인디 개발자를 위한 도구입니다. 한 번에 다 읽을 수 있을 만큼 작고, 중요한 곳에서는 엄격합니다.

## 동작 방식

```
 나 ──"pass 돌려"──▶ 에이전트 ──▶ 리서치 ──▶ 초안 ──▶ op verify ──▶ op pending add ──▶ .operator/pending/
                       │                                  │ 실패 → 초안을 고침
                       │  `git push`, `curl -X POST`, `wrangler deploy` 등을 시도
                       └──▶ op guard (훅) ──✋ 차단 ──▶ "승인 큐에 올려라"

 나 (내 터미널이나 휴대폰) ──▶ op pending approve 0001 ──▶ .operator/approved/
 에이전트 ──▶ op send 0001 ──▶ 승인된 명령만 실행 (예: op deliver 0001 → X 에 게시) ──▶ .operator/sent/
```

승인은 대화형 터미널에서만 동작합니다. 그래서 에이전트의 셸 도구로는 무엇도 승인할 수 없습니다.

## 기능

| | 명령 | 하는 일 |
|---|---|---|
| 승인 게이트 | `op guard` (PreToolUse 훅) | 밖으로 나가거나 되돌릴 수 없는 명령, 승인 큐 편집, 큐 파일을 셸로 옮기는 우회를 막음. `cd 프로젝트 && …`, `git -C 프로젝트 …` 도 같은 규칙 |
| 재개 가능한 pass | `op pass` | 한 pass = 리서치 → 초안 → 큐 등록 → 보고. "크레딧" 대신 단계 상한. 오류나 새 세션에도 이어감 |
| 검증 게이트 | `op verify` | 종류별 규칙: 포스트(채널별 길이), 이메일(받는 사람·제목), 리서치(출처 URL 3개 이상), 사이트(빌드 성공) |
| 실제 게시 | `op deliver` | X, Threads, 이메일(SMTP), 웹훅(Slack/Discord). 승인된 티켓만, 토큰은 프로젝트 밖에서 읽음 |
| 원격 승인 | `op serve`, `op notify` | 같은 Wi-Fi 의 휴대폰에서 1회용 링크로 승인·거절, 대기 건수 푸시 알림 |
| 거절에서 배우기 | `op feedback` | 거절 사유를 모아 다음 초안 전에 읽음 |
| 모델 라우팅 | `op llm` | 좁은 작업은 로컬 OpenAI 호환 모델(예: Ollama)로, 없으면 에이전트가 직접 |

## 빠른 시작 (5분)

**1. 설치** (하나 고르기)

```text
# Claude Code — 플러그인, 훅이 자동 연결됨
/plugin marketplace add pullyo/operator-skill
/plugin install operator@operator-skill
```

```bash
# 어떤 도구든 수동 설치: ~/.claude, ~/.codex, ~/.cursor, ~/.gemini 중 있는 곳에 링크
git clone https://github.com/pullyo/operator-skill
sh operator-skill/skills/operator/install.sh
sh operator-skill/skills/operator/install.sh --print-hooks   # Claude Code / Codex / Cursor / Gemini CLI 용 훅 설정
```

훅 없이도 스킬은 동작하지만, 그때 차단은 보장이 아니라 지시 수준이 됩니다.

**2. 프로젝트 하나에서 켜기**

```bash
alias op="$PWD/operator-skill/skills/operator/scripts/op"   # 또는 scripts/op 를 PATH 에 추가
cd ~/my-product && op init                                 # .operator/ 생성 — 가드는 이 폴더가 있는 곳에서만 작동
```

**3. 에이전트에게 말하기** (그 폴더에서 새 세션을 열고)

> operator 로 내 제품을 plan 해 줘. 채널은 X 랑 Threads, 짧고 친근하게.
>
> pass 한 번 돌려 줘. 채널마다 런칭 포스트 하나씩.

**4. 검토하고 직접 승인하기**

```bash
op pending list
op pending show 0001
op pending approve 0001          # 또는: op pending reject 0001 --reason "너무 딱딱함"
op serve --lan                   # 선택: 휴대폰에서 승인하기
```

**5. 보내기**

> 0001 보내.

에이전트가 `op send 0001` 을 실행하고, 내가 승인한 명령만 실행됩니다. 실제 계정을 연결하기 전에 개인 Discord 나
Slack 채널로 가는 웹훅으로 먼저 전체 흐름을 확인해 보세요.

## 명령

| 명령 | 누가 | 용도 |
|---|---|---|
| `op init` · `op status` | 누구나 | 작업 공간 만들기, 진행 중인 pass·큐·거절 기록 보기 |
| `op pass start/next/done/fail/end` | 에이전트 | pass 실행과 단계 기록 |
| `op verify <파일> --type …` | 에이전트 | 큐에 올리기 전 초안 검사 |
| `op pending add <파일> [--action "명령"]` | 에이전트 | 검증 후 큐 등록 (x/threads/email/webhook 은 `op deliver <id>` 가 자동으로 채워짐) |
| `op pending list/show` | 누구나 | 큐 보기 |
| `op pending approve <id> [--action "명령"]` · `reject <id> --reason …` | **나**, 대화형 터미널 | 결정 |
| `op send <id>` | 에이전트 | 승인된 명령만 실행 |
| `op serve [--lan]` · `op notify` | **나** / 에이전트 | 휴대폰 승인 페이지 · 대기 건수 알림 |
| `op feedback` | 에이전트 | 최근 거절 사유 읽기 |
| `op deliver --check` | 누구나 | 어느 채널에 토큰이 준비됐는지 (값은 출력하지 않음) |
| `op guard check [--cwd 폴더] "명령"` | 누구나 | 이 명령이 막히는지 미리 보기 |
| `op llm --role summarize …` | 에이전트 | 좁은 작업을 로컬 모델로 |

## 안전 모델

**강제되는 것** (훅과 `op` 자체가 막음):

- 밖으로 나가거나 되돌릴 수 없는 명령 차단: 소셜 API 게시, 메일 발송, 원격 주소로의 `curl` POST/PUT/DELETE,
  `git push`(`git -C … push` 포함), `vercel/netlify/wrangler/fly deploy`, `npm publish`, Stripe 결제 생성, 도메인 구매,
  재귀 삭제, `git push --force`, `DROP TABLE`.
- 큐(`.operator/pending|approved|sent|rejected`)는 `op` 로만 바뀝니다. 편집 도구로 쓰거나 `mv`/`cp`/`>`/`sed -i`/파이썬 한 줄로
  고치는 것은 막힙니다. `cat`, `ls`, `grep` 같은 읽기 명령은 허용됩니다.
- `op pending approve/reject` 와 `op serve` 는 대화형 터미널이 없으면 실행되지 않습니다. 스크립트를 복사해 돌려도
  에이전트는 실행할 수 없습니다.
- `op send` 는 승인된 티켓에 기록된 명령만 실행합니다. 다른 명령은 거부하고, 명령이 없는 티켓은 보낼 수 없으며,
  `op pending`/`op send` 를 부르는 명령도 거부합니다.
- 도메인 구매와 결제는 승인 큐에도 올리지 않습니다. 사람이 직접 합니다.

**막지 못하는 것** — 알아두세요:

- 훅을 지원하지 않는 도구에서는 규칙이 지시로만 전달됩니다.
- 토큰은 에이전트와 같은 컴퓨터에 있습니다. 가드가 외부 요청을 막지만 비밀 금고는 아닙니다. 게시 권한만 있는 토큰을 쓰세요.
- `op serve --lan` 은 1회용 토큰이 있는 로컬 네트워크의 일반 HTTP 입니다. 믿을 수 있는 네트워크(또는 Tailscale 같은
  사설 VPN)에서만 쓰고, 인터넷에 열지 마세요.
- 가드는 명령 문자열을 읽습니다. 변수로 만든 경로(`cd $HOME/x`)는 세션 폴더 기준으로만 판단합니다.

## 한계

- 혼자 돌지 않습니다. pass 는 내가(또는 운영체제 예약이) 시킬 때 시작합니다 —
  [예약 실행](skills/operator/references/scheduling.md) 참고.
- 브랜드·웹사이트·메일함을 만들지 않고, 결제를 처리하지 않습니다.
- X 사용자 토큰은 빨리 만료되며 operator 는 갱신하지 않습니다. [채널 설정](skills/operator/references/channels.md) 참고.

## 저장소 구조

```
operator-skill/
├── .claude-plugin/        Claude Code 플러그인 + 마켓플레이스 매니페스트
├── .codex-plugin/         Codex 플러그인 매니페스트
├── hooks/hooks.json       Claude Code 플러그인 훅 (승인 게이트)
├── tests/                 실제 `op` 프로세스를 돌리는 종단 테스트
└── skills/operator/       스킬 본체 (Agent Skills 형식)
    ├── SKILL.md           에이전트가 읽는 문서
    ├── scripts/op.py      CLI — Python 3.8+, 표준 라이브러리만
    ├── references/        pass 흐름, 가드·검증 규칙, 채널, 예약 실행, 설계 메모
    ├── assets/            초안 템플릿, 도구별 훅 설정, launchd 템플릿
    └── install.sh         여러 도구용 설치 스크립트
```

## 테스트

```bash
python3 -m unittest discover -s tests
```

테스트는 Claude Code 와 Codex 가 보내는 것과 같은 훅 입력을 실제 `op` 프로세스에 넣고, 내 컴퓨터에 띄운 가짜
X/Threads API 로 게시해 실제 계정을 건드리지 않고 전송을 확인합니다.

## 배경

[Foundable](https://foundable.com) 이 공개적으로 설명하는 AI 직원의 운영 방식(만들기 → 운영 → 수익, 모든 것이
사용자의 OK 를 기다림)에서 착안했습니다. operator 는 독립 구현이며 Foundable 과 관계가 없습니다.
설계 메모: [references/foundable-research.md](skills/operator/references/foundable-research.md).

## 라이선스

MIT
