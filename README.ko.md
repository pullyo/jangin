# operator

[English](README.md) · **한국어**

**아이디어 구상을 함께 하고, 그 아이디어로 개발과 배포 관리까지 돕는, 내 컴퓨터에서 도는 전용 AI 비서.**
중심은 구상입니다. 코딩 에이전트가 한 번에 하나씩 묻고, 반론을 던지고, 조사해서 만들 가치가 있는지 같이 정합니다.
그다음 승인된 계획을 마일스톤마다 만들고 승인 큐를 거쳐 배포하며, 출시를 알리고 숫자를 보고 다음 할 일을 제안합니다.
다음 단계로 넘어가는 것과 내 컴퓨터 밖으로 나가는 행동은 전부 내 손을 거칩니다. 목표와 로드맵: [VISION.md](VISION.md).

operator 는 [Agent Skill](https://agentskills.io) 과 의존성 없는 작은 파이썬 CLI(`op`)로 이뤄져 있습니다.
같은 폴더를 Claude Code, Codex CLI, Cursor, Gemini CLI 등 Agent Skills 형식을 읽는 도구에서 그대로 씁니다.

---

## 왜 만들었나

"AI 직원" 서비스가 매력적인 이유는 무언가를 *만들어* 주는 데서 끝나지 않기 때문입니다. 무엇을 만들지 같이 정하고,
만든 뒤에도 계속 *굴려* 줍니다. 그런데 그 서비스를 안전하게 만드는 건 모델이 아니라 모델을 둘러싼 장치입니다.
단계, 승인, 체크포인트, 검증 같은 것들입니다. 대부분의 에이전트 플러그인은 모델에게 "먼저 확인받아"라고 *부탁*만 하고,
제품이 이미 있다고 가정합니다. operator 는 에이전트에게 따라갈 단계를 주고, 부탁을 우회할 수 없는 규칙으로 바꿉니다.

| operator 없이 | operator 와 함께 |
|---|---|
| 세션마다 완성된 제품을 가정하고 게시물부터 씀 | 프로젝트의 **단계**(발견 → 검증 → 만들기 → 운영 → 배우기)가 기록되고, 에이전트는 그 단계의 일만 함. 다음 단계로는 나만 넘김 |
| 프롬프트에 "게시 전에 물어봐"라고 적음 (대체로 지켜짐) | 게시·메일·배포·결제·삭제를 **훅이 막고** 승인 큐로 보냄 |
| 에이전트가 내 API 토큰을 가짐 | 기본값은 **승인하는 순간 내 프로세스가 보냄**. 토큰은 macOS 키체인에 있고 에이전트는 읽지 못하게 막힘 |
| "다 했어요" | 마일스톤은 검사 명령이 실제로 통과해야 끝남. 단계 문서와 초안도 검증을 통과해야 인정됨 |
| 에이전트가 대화를 다시 읽고 어디까지 했는지 추측 | 단계마다 기록하고, 새 세션은 정확히 그 단계부터 이어감 |

1인 창업자와 인디 개발자를 위한 도구입니다. 한 번에 다 읽을 수 있을 만큼 작고, 중요한 곳에서는 엄격합니다.

## 동작 방식

```
 발견 ──▶ 검증 ──▶ 만들기 ──▶ 운영 ──▶ 배우기 ──▶ (내가 고름: 운영 | 만들기 | 발견)
 같이      조사하고   검사를     매일 pass    지표를 성공
 의논      진행/수정  통과하는    승인 큐로    지표와 비교
           /중단     마일스톤
        화살표마다 = `op stage advance`, 내 터미널에서 내가 실행

 단계 안에서:
 에이전트 ──▶ 리서치 / 초안 / 코드 ──▶ op verify ──▶ op pending add ──▶ .operator/pending/
   │  `git push`, `curl -X POST`, `wrangler deploy`, 토큰 읽기 등을 시도
   └──▶ op guard (훅) ──✋ 차단 ──▶ "승인 큐에 올려라"

 나 (터미널, 텔레그램으로 휴대폰, 또는 브라우저) ──▶ 0001 승인 ──▶ 내 프로세스가 발송 ──▶ .operator/sent/
```

단계 이동과 승인은 대화형 터미널(또는 내가 띄운 텔레그램 봇·1회용 웹 링크)에서만 동작합니다.
그래서 에이전트의 셸 도구로는 무엇도 승인하거나 넘길 수 없습니다.

## 기능

| | 명령 | 하는 일 |
|---|---|---|
| 단계 | `op stage` | 발견 → 검증 → 만들기 → 운영 → 배우기. 단계마다 문서와 통과 조건이 있음. 넘기기와 되돌리기(이유를 에이전트가 읽음)는 나만 |
| 마일스톤 | `op milestone` | 만들기 단계의 작업 단위. 검사 명령이 exit 0 이어야 완료. `true` 같은 빈 검사는 거부 |
| 지표 | `op metric` | 배우기 단계의 숫자. 발견 단계에서 정한 성공 지표 옆에 보여 주고, 보낸 수·거절 수를 자동 집계 |
| 승인 게이트 | `op guard` (PreToolUse 훅) | 밖으로 나가거나 되돌릴 수 없는 명령, 큐·단계 파일 편집, 비밀값 읽기를 막음. `cd 프로젝트 && …`, `git -C 프로젝트 …` 도 같은 규칙 |
| 사람 쪽 발송 | `op pending approve` | 기본값은 승인하는 순간 내 프로세스가 action 을 실행. 에이전트는 보내지 못함 |
| 비밀값 | `op secret` | 토큰은 macOS 키체인(읽을 때마다 허락을 물음)이나 프로젝트 밖 권한 600 파일. 출력하지 않고 티켓에도 쓰지 않음 |
| 실제 게시 | `op deliver` | X, Threads, 이메일(SMTP), 웹훅(Slack/Discord) |
| X 연결과 갱신 | `op connect x` | 브라우저에서 OAuth 2.0 PKCE 로그인. 만료된 토큰은 자동으로 갱신해 저장 |
| 원격 승인 | `op telegram`, `op serve` | 텔레그램 버튼으로 휴대폰에서 승인·거절(포트 안 엶), 또는 같은 Wi-Fi 에서 1회용 링크 |
| 재개 가능한 pass | `op pass` | 단계별 기본 순서로 도는 작업 단위. "크레딧" 대신 단계 상한. 오류나 새 세션에도 이어감 |
| 검증 게이트 | `op verify` | 종류별 규칙: 포스트(채널별 길이), 이메일(받는 사람·제목), 리서치(출처 URL 3개 이상), 사이트(빌드 성공) |
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
mkdir ~/bakery-booking && cd ~/bakery-booking && op init    # 새 아이디어는 발견 단계에서 시작
# 이미 운영 중인 제품이면:  op init --stage operate
```

**3. 에이전트에게 말하기** (그 폴더에서 새 세션을 열고)

> 동네 빵집용 예약 페이지를 만들어 보고 싶어. operator 로 같이 정리해 줘.

에이전트가 한 번에 하나씩 묻고, 답을 `.operator/stages/discover.md` 에 정리합니다(문제, 고객, 제안, 성공 지표).
`op stage check` 를 통과하면 다음 단계로 넘겨 달라고 요청합니다.

**4. 단계 이동과 승인은 직접**

```bash
op stage                 # 지금 위치와 남은 조건
op stage advance         # 조건을 통과하면 발견 → 검증 → 만들기 → 운영 → 배우기
op pending list
op pending approve 0001  # 이 터미널에서 바로 발송. 또는: op pending reject 0001 --reason "너무 딱딱함"
```

**5. 운영 단계에 오면 채널 연결**

```bash
op secret set OPERATOR_WEBHOOK_URL   # 먼저 개인 Discord/Slack 웹훅으로 전체 흐름 확인
op connect x                         # 그다음 X (채널 설정 참고), Threads, 이메일
op telegram                          # 선택: 휴대폰으로 승인
```

## 명령

| 명령 | 누가 | 용도 |
|---|---|---|
| `op init [--stage 단계] [--send human\|agent]` · `op status` | 누구나 | 작업 공간 만들기, 단계·pass·큐·거절 기록 보기 |
| `op stage` · `doc` · `check` · `history` | 에이전트 | 단계 보기, 문서 만들기, 넘어가기 조건 검사 |
| `op stage advance` · `back --to 단계 --reason …` · `set 단계` | **나**, 대화형 터미널 | 단계 이동 |
| `op milestone add "제목" --test "명령"` · `done N` · `list` | 에이전트 | 만들기 단계 마일스톤. 검사가 통과해야 완료 |
| `op metric add 이름 값 [--source …]` · `list` | 에이전트 / 나 | 배우기 단계의 숫자 기록 |
| `op pass start/next/done/fail/end` | 에이전트 | pass 실행과 단계 기록 |
| `op verify <파일> --type …` | 에이전트 | 큐에 올리기 전 초안 검사 |
| `op pending add <파일> [--action "명령"]` | 에이전트 | 검증 후 큐 등록 (x/threads/email/webhook 은 `op deliver <id>` 가 자동으로 채워짐) |
| `op pending list/show` | 누구나 | 큐 보기 |
| `op pending approve <id> [--action "명령"] [--no-send]` · `reject <id> --reason …` | **나**, 대화형 터미널 | 결정. 발송 방식이 human 이면 승인이 곧 발송 |
| `op send <id>` | 에이전트(agent 방식) / 나 | 승인된 명령만 실행 |
| `op secret set/rm 이름` · `list` | **나** / 누구나 | 토큰 저장(키체인 또는 600 파일), 이름만 보기 |
| `op connect x` | **나** | 브라우저로 X 로그인, 토큰 자동 갱신 |
| `op telegram [--setup]` · `op serve [--lan]` · `op notify` | **나** / 에이전트 | 텔레그램·Wi-Fi 로 휴대폰 승인 · 대기 건수 알림 |
| `op feedback` | 에이전트 | 최근 거절 사유 읽기 |
| `op deliver --check` | 누구나 | 어느 채널이 준비됐는지 (값은 출력하지 않음) |
| `op guard check [--cwd 폴더] "명령"` | 누구나 | 이 명령이 막히는지 미리 보기 |
| `op llm --role summarize …` | 에이전트 | 좁은 작업을 로컬 모델로 |

## 안전 모델

**강제되는 것** (훅과 `op` 자체가 막음):

- 밖으로 나가거나 되돌릴 수 없는 명령 차단: 소셜 API 게시, 메일 발송, 원격 주소로의 `curl` POST/PUT/DELETE,
  `git push`(`git -C … push` 포함), `vercel/netlify/wrangler/fly deploy`, `npm publish`, Stripe 결제 생성, 도메인 구매,
  재귀 삭제, `git push --force`, `DROP TABLE`.
- 큐(`.operator/pending|approved|sent|rejected`)와 단계·마일스톤·지표·가드 파일은 `op` 로만 바뀝니다. 편집 도구나
  `mv`/`cp`/`>`/`sed -i`/파이썬 한 줄로 고치는 것은 막히고, 읽기는 허용됩니다.
- 승인·거절, 단계 이동, 비밀값 등록, 계정 연결, 승인 서버 시작은 사람의 결정 경로(authority)를 거쳐야 실행됩니다.
  터미널에서는 대화형 터미널(TTY)이 있어야 하고, Hermes 에서는 내가 친 `/approve` 같은 명령을 플러그인이 받아 처리합니다.
  어느 경로로 결정했는지는 티켓(`decided_by`)과 단계 기록(`by`)에 남습니다. 에이전트를 사람으로 바꿔 주는 환경 변수는 없습니다.
- 기본 발송 방식(human)에서는 에이전트가 `op send` 를 아예 실행할 수 없고, 승인된 action 은 내 프로세스에서 실행됩니다.
  agent 방식에서도 `op send` 는 승인된 티켓에 기록된 명령만 실행합니다.
- `~/.config/operator/` 읽기, `security find-generic-password`, `printenv` 같은 명령은 Read 도구까지 포함해 막힙니다.
  키체인 항목은 읽을 때마다 허락을 묻도록 저장됩니다.
- 단계는 조건을 통과해야만 넘어가고, 마일스톤은 검사 명령이 exit 0 일 때만 끝납니다.
- 도메인 구매와 결제는 승인 큐에도 올리지 않습니다. 사람이 직접 합니다.

**막지 못하는 것** — 알아두세요:

- **터미널 확인은 증명이 아니라 실수 방지입니다.** 에이전트의 셸 도구에는 터미널이 없어서 보통의 호출은 막히지만,
  가짜 터미널(`script -q /dev/null op …`)이나 스크립트 파일로 감싸면 TTY 검사와 가드를 통과할 수 있습니다(이 맥에서 확인).
  같은 사용자 권한으로 도는 에이전트가 작정하고 우회하는 것까지 막으려면 Hermes 플러그인 경로만 받도록
  `.operator/guard.json` 에 `"human_via": ["plugin"]` 을 두고, 실제 배포 계정에는 격리 등급 2(docker)를 씁니다
  ([docs/hermes-design.md](docs/hermes-design.md) 4절).
- 훅을 지원하지 않는 도구에서는 규칙이 지시로만 전달됩니다. 다만 키체인 허락 창과 사람 쪽 발송은 그때도 토큰을 지킵니다.
- 가드는 명령 문자열을 읽습니다. 변수로 만든 경로(`cd $HOME/x`)는 세션 폴더 기준으로만 판단하고,
  `.operator/` 가 있는 폴더에 닿는 호출에만 작동합니다.
- 마일스톤 검사 명령은 에이전트가 정합니다. 만들기 단계를 넘길 때 목록이 보이니 읽어 보세요.
- 텔레그램 카드에는 초안 본문이 들어가 텔레그램 서버를 거칩니다(`--titles-only` 로 피할 수 있음).
  `op serve --lan` 은 로컬 네트워크의 일반 HTTP 입니다.

## 한계

- 혼자 돌지 않습니다. pass 는 내가(또는 운영체제 예약이) 시킬 때 시작합니다 —
  [예약 실행](skills/operator/references/scheduling.md) 참고. human 방식의 발송은 컴퓨터가 켜져 있어야 합니다.
- 브랜드 디자인, 도메인 구매, 결제 처리는 하지 않습니다.
- X, Threads, SMTP, 텔레그램은 실제 계정이 아니라 각 API 를 흉내 낸 로컬 서버로 테스트했습니다. Threads 토큰은 갱신하지 않습니다.

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
    ├── references/        단계, pass 흐름, 가드·검증 규칙, 채널과 비밀값, 예약 실행, 설계 메모
    ├── assets/            초안 템플릿, 도구별 훅 설정, launchd 템플릿
    └── install.sh         여러 도구용 설치 스크립트
```

## 테스트

```bash
python3 -m unittest discover -s tests
```

테스트는 Claude Code 와 Codex 가 보내는 것과 같은 훅 입력을 실제 `op` 프로세스에 넣고, 프로젝트를 모든 단계로 옮겨 보고,
임시 홈 폴더에서 가짜 X·Threads·토큰·텔레그램 서버로 보내 실제 계정과 키체인을 건드리지 않고 확인합니다.

## 배경

[Foundable](https://foundable.com) 이 공개적으로 설명하는 AI 직원의 운영 방식(만들기 → 운영 → 수익, 모든 것이
사용자의 OK 를 기다림)에서 착안했습니다. operator 는 독립 구현이며 Foundable 과 관계가 없습니다.
설계 메모: [references/foundable-research.md](skills/operator/references/foundable-research.md).

## 라이선스

MIT
