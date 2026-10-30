# jangin × Hermes 설계

상태: M1–M3 구현 (2026-10-30, `hermes-distro` 브랜치, jangin 0.6.0). 기준 Hermes Agent v0.22.5 (2026.9.24).
근거는 Hermes 소스 읽기와, 시험용 HERMES_HOME 에서 돌린 실제 Hermes 의 플러그인 로더·명령 디스패치·훅 시험이다.
무엇이 확인됐고 무엇이 아직인지는 7절에 있다.

## 1. 왜 Hermes 인가

[VISION.md](../VISION.md) 의 목표는 일반 사용자도 쓰는 "구상 → 개발 → 배포 관리" 전용 AI 비서다.
지금 jangin 은 터미널 명령을 알아야 쓸 수 있다. Hermes Agent 는 그 빈자리를 이미 채우고 있다.

| 필요한 것 | Hermes 가 이미 가진 것 |
|---|---|
| 앱 | Hermes Desktop (맥, 윈도우), 안드로이드(Termux) |
| 메신저 대화 | 텔레그램, 디스코드, 슬랙, 왓츠앱, 시그널 게이트웨이 |
| 생각하는 손 | Hermes 자체 에이전트. Claude Code·Codex 설치가 필요 없다 |
| 스킬 | Agent Skills 표준 호환. jangin SKILL.md 를 그대로 읽는다 |
| 실행 전 차단 | 셸 훅 `pre_tool_call` (exit 2 또는 block JSON, `fail_closed`) — CLI, 게이트웨이, Desktop 모두 |
| 사람 확인 | 훅이 `{"action":"approve"}` 를 돌려주면 Hermes 의 사람 승인 화면으로 넘어간다 (텔레그램·디스코드·슬랙 버튼). 단 yolo, `approvals.mode: off`, cron 의 `approve` 모드, 저장된 "항상 허용"이면 자동 통과한다 — jangin 은 이 경로를 쓰지 않고 block 만 쓴다 |
| 사람만 치는 명령 | 플러그인 `ctx.register_command` → 사용자가 치는 `/명령`, 게이트웨이 프로세스에서 플러그인 코드가 처리. 메신저에서 오면 `source.user_id` 가 붙는다 |
| 예약 | 내장 cron, 결과를 메신저로 전달. cron 의 위험 명령은 기본 거부(`cron_mode: deny`) |
| 격리 | Docker 터미널 백엔드, `docker_volumes` 에 `:ro` 마운트 |

그래서 앱·메신저·예약·모델 실행은 Hermes 에 맡기고, jangin 은 **단계, 승인 큐, 검증, 차단, 사람만 하는 단계 이동과 발송**에 집중한다.
Claude Code, Codex, Cursor, Gemini CLI 지원은 그대로 둔다. Hermes 는 일반 사용자용 기본 경로가 된다.

## 2. 사용자가 겪는 흐름

1. Hermes Desktop 을 설치하고 처음 설정(모델 로그인)을 마친다.
2. 설치: `curl -fsSL https://raw.githubusercontent.com/pullyo/jangin/main/install.sh | sh` — Hermes 가 없으면 설치, jangin 받기,
   기본 프로필을 `--clone-all` 로 복사해 `jangin` 프로필 생성(OAuth 는 Hermes 가 복사하지 않고 이어받게 함), 플러그인·스킬·SOUL.md 설치.
   쓰던 Hermes(기본 프로필)는 건드리지 않는다. 업데이트는 `jangin update`.
   `hermes plugins install pullyo/jangin/hermes/jangin` 은 하위 폴더만 받아서 스킬(op.py)이 빠진다 — 7절.
3. 터미널에서 `jangin setup` — 원래 Hermes 마법사(모델·터미널·메신저·도구)를 먼저 그대로 돌리고, 이어서 한국어 jangin 단계: 플러그인, 프로젝트 폴더, 승인 방식, 메신저 승인 허용 사용자, 두 번째 잠금(셸 훅).
   대화창의 `/setup` 은 폴더·지금 프로젝트·토큰 읽기(`/setup unlock`). (하루 상한은 M4)
4. `/idea 동네 빵집 예약 페이지` — 프로젝트 폴더를 만들고 발견 단계가 시작된다. 에이전트가 한 번에 하나씩 묻는다.
5. 발견 문서가 채워지면 에이전트가 "다음 단계로 넘길 준비가 됐습니다"라고 알린다. 사용자가 `/advance`.
6. 만들기 단계: 에이전트가 마일스톤을 만들고, 사용자가 `/build 1` 로 Hermes `/goal` 반복을 시작한다 (6.1절).
   검사가 통과하면 반복이 끝나고, 다음 단계로는 사람이 `/advance`. 첫 배포는 승인 대기로 온다.
7. `/inbox` 에서 확인하고 `/ok 0003` → 플러그인이 게이트웨이 프로세스에서 실행·발송한다. (상태 확인·되돌리기 티켓은 M5)
8. 운영·배우기: 매일 아침 예약 실행이 초안을 큐에 올리고 카드로 알린다. 주간 회고가 메신저로 온다.

사용자가 쓰는 것은 대화와 `/명령` 몇 개뿐이다. 터미널은 설치 때 한 번 연다.

명령 이름은 Hermes 내장 명령과 겹치지 않게 골랐다. 겹치면 Hermes 가 경고만 남기고 등록을 건너뛴다
(`hermes_cli/plugins.py`). 내장 `/approve`·`/deny` 는 위험 명령 허락용, `/status`·`/queue` 도 내장이다.

| 명령 | 하는 일 | 사람의 결정 |
|---|---|---|
| `/idea <한 줄>` | 프로젝트 폴더 + 발견 단계 시작, `human_via: ["local","messenger"]` | |
| `/project` | 상태 (op status) | |
| `/stage` | 단계, 넘어가기 조건 | |
| `/advance` · `/back <단계> <이유>` | 단계 이동 | ✓ |
| `/inbox [번호]` | 승인 대기 | |
| `/ok <번호>` · `/reject <번호> <이유>` | 결정. human 방식이면 승인 즉시 플러그인에서 발송 | ✓ |
| `/setup` | 폴더, 지금 프로젝트, `/setup unlock` (키체인에서 토큰을 메모리로) | |
| `/jangin <하위 명령>` | 위 명령을 한 이름으로 (status·queue·approve 별칭 포함) | |

## 3. 구조

```
 Hermes 게이트웨이 프로세스 (사람의 손)
 ├── jangin 플러그인
 │     /idea /project /stage /advance /back /inbox /ok /reject /setup /jangin
 │     승인 시 발송·배포 실행 (카드 게시·상태 확인·되돌리기 티켓은 M5)
 │     pre_tool_call 훅: op 의 가드 규칙 (ctx.session_cwd() 로 세션 폴더를 안다)
 │     토큰: /setup unlock 또는 첫 /ok 때 키체인에서 한 번 읽어 메모리에만 (허락 창은 그때)
 │     cron 등록: 매일 pass, 주간 회고 (M4)
 └── Hermes 에이전트 (생각하는 손)
       jangin 스킬을 읽고 구상 질문, 조사, 문서, 코딩, 검사
       도구 호출마다 → 플러그인 훅 (+ 선택: 셸 훅 `op guard --format hermes`, fail_closed)
       터미널 백엔드: local (기본) 또는 docker (격리 등급)
```

| 지금 jangin | Hermes 에서 |
|---|---|
| `op stage advance/back/set` (터미널) | `/advance`, `/back <단계> <이유>` |
| `op pending approve/reject` (터미널) | `/ok 0003`, `/reject 0003 <이유>` |
| `op telegram`, `op serve` | 필요 없음. Hermes 게이트웨이와 Desktop 이 대신한다 |
| `op secret set` | 지금은 터미널의 `op secret set`. 값은 대화창에 쓰지 않는다 (Desktop 입력 창은 7절) |
| 훅 (Claude Code / Codex) | 플러그인 `pre_tool_call` 훅 (세션 폴더를 안다) + 선택으로 셸 훅 `op guard --format hermes` (fail_closed) |
| launchd 예약 | Hermes cron |
| `op status`, `op stage`, `op pending list` | `/project`, `/stage`, `/inbox` (에이전트도 읽기 명령은 그대로 쓴다) |

## 4. "사람만" 을 어떻게 증명하나

### 지금 방식의 약점 (2026-10-30 확인)

jangin 0.5.0 은 사람 확인을 두 가지로 한다: 대화형 터미널(TTY) 검사와 `OPERATOR_ALLOW_NONINTERACTIVE_APPROVE=1`.
둘 다 우회할 수 있다.

- macOS 의 `script -q /dev/null <명령>` 은 가짜 터미널을 만들어 TTY 검사를 통과한다 (이 맥에서 확인).
- 가드는 명령 문자열을 읽는다. 에이전트가 승인 명령을 파일에 써 두고 `bash x.sh` 로 실행하면 가드는 `bash x.sh` 만 본다.
- 환경 변수는 에이전트가 스스로 설정할 수 있다.

즉 훅은 실수와 일반적인 시도는 막지만, 작정한 우회를 막는 보장은 아니다. README 의 "스크립트를 복사해 돌려도
에이전트는 실행할 수 없다"는 표현은 0.6.0 에서 고쳤다.

### 0.6.0 의 authority

사람의 결정(승인·거절, 단계 이동, 비밀값)은 `Authority` 를 받아야 실행되고, 경로가 티켓(`decided_by`)과 단계 기록(`by`)에 남는다.
환경 변수 우회(`OPERATOR_ALLOW_NONINTERACTIVE_APPROVE`)는 없앴다. 프로젝트는 `guard.json` 의 `human_via` 로 받을 경로를 고른다.

| 경로 | 어디서 | 흉내 낼 수 있나 |
|---|---|---|
| `terminal` | 대화형 터미널의 `op …` | 예. 가짜 터미널, 스크립트 파일 |
| `local` | Hermes Desktop·TUI·CLI 화면의 플러그인 명령 (`source=None`) | 원리상 예. 이 화면들은 같은 사용자 권한의 로컬 소켓(`slash.exec`)으로 명령을 보내고, 소켓은 OS 사용자만 확인한다 |
| `messenger` | 게이트웨이가 받은 메신저 메시지 (`source.user_id`) | 확인한 범위에서는 아니오. 사용자 ID 는 메신저 서버가 보증하고, 모델 출력·cron·플러그인 주입은 명령으로 해석되지 않는다 |

`/idea` 로 만든 프로젝트는 `["local", "messenger"]` (터미널 끔). 가장 엄격하게는 `["messenger"]`: 결정은 휴대폰에서만.
셋 모두, 같은 사용자 권한의 에이전트가 파이썬으로 op 모듈을 가져와 `Authority` 를 직접 만드는 것까지는 막지 못한다
(한 줄짜리 `python -c` 는 가드가 막지만 스크립트 파일 안은 못 본다). 그건 격리 등급 2 가 막는다.

### Hermes 에서의 사람 확인

사람의 결정은 **에이전트가 만들 수 없는 경로**로만 들어오게 한다.

1. **플러그인 슬래시 명령.** `/ok`, `/advance` 는 사용자가 메신저나 Desktop 에 친 메시지로 생기고, 게이트웨이 프로세스의
   플러그인 코드가 처리한다. 모델 출력·cron 프롬프트·플러그인 주입 메시지는 명령으로 해석되지 않는다 (7절). 다만 로컬 화면
   경로는 로컬 소켓으로 흉내 낼 수 있어 `local` 로 따로 기록한다. 게이트웨이의 사용자 허용 목록(`TELEGRAM_ALLOWED_USERS` 등)과
   선택으로 `OPERATOR_ALLOWED_USERS`(게이트웨이 환경 변수)가 누가 명령을 칠 수 있는지 정한다.
2. **플러그인이 op 를 직접 부른다.** 셸 명령 + 환경 변수가 아니라, 플러그인이 op 모듈을 가져와
   `pending_decide(od, id, "approve", Authority("messenger", "hermes:telegram:42"))` 를 호출한다.
   플러그인은 `hermes <명령>` CLI 하위 명령(`register_cli_command`)을 등록하지 않는다: 에이전트가 터미널로 칠 수 있어서다.
3. **발송과 배포는 플러그인이 실행한다.** 토큰은 `/setup unlock` 이나 첫 `/ok` 때 키체인에서 읽어 게이트웨이 메모리에만 둔다. 에이전트가 큐 파일을
   위조해도, 발송은 사람이 `/ok` 할 때 플러그인에서만 일어나므로 아무것도 나가지 않는다.

### 격리 등급

| 등급 | 설정 | 막는 것 | 못 막는 것 |
|---|---|---|---|
| 1 기본 | 터미널 백엔드 local + 플러그인 (+ 셸 훅) | 실수, 일반적인 외부 명령, op 채널(X·Threads·메일·웹훅) 무단 발송 (토큰이 키체인 + 플러그인에만 있음) | 스크립트로 감싼 우회, 로컬 소켓으로 `local` 명령 흉내, 에이전트가 이미 로그인된 CLI(예: `wrangler login` 상태)로 직접 배포, `plugin-data/` 설정 파일 고치기 |
| 2 격리 (실계정 권장) | 터미널 백엔드 docker. 프로젝트만 마운트, `.operator/` 의 approved·sent·rejected·stage.json·guard.json 은 `:ro`, `~/.config/operator` 와 배포 CLI 로그인 정보는 마운트 안 함 | 등급 1 + 스크립트 우회, 큐·단계 위조, 직접 배포 | Docker Desktop 설치가 필요 (일반 사용자에게 부담) |

일반 사용자 기본값은 등급 1, 실제 배포 계정을 연결하면 등급 2 를 권한다. 배포 명령은 등급 1 에서도 플러그인이 실행하도록
배포 토큰을 `op secret` 으로만 받고, CLI 를 미리 로그인해 두지 말라고 안내한다.

## 5. jangin 쪽에서 바꿀 것

| # | 변경 | 내용 |
|---|---|---|
| 0 ✓ | 정직한 문서 | README·SKILL 의 TTY 우회 불가 표현 수정, 격리 등급 설명 추가 |
| 1 ✓ | 사람 권한 추상화 | `Authority(terminal | local | messenger)`, `guard.json` 의 `human_via`. 환경 변수 우회 제거, 테스트는 진짜 pty 로 사람 역할 |
| 2 ✓ | `op guard --format hermes` | Hermes 페이로드(`terminal`·`write_file`·`patch`(V4A 포함)·`read_file`·`execute_code`) 해석, exit 2 + `{"action":"block","message"}`. `cwd` 가 게이트웨이 폴더라 `workdir` 이 없으면 등록된 프로젝트(`~/.config/operator/projects.json`) 규칙을 적용 |
| 3 ✓ | op 를 모듈로 | `init_project`, `status_summary`, `queue_items`, `pending_decide`, `stage_move`, `stage_overview`, `secret_store`. `die` 는 `OpError` 를 던지고 CLI `main` 이 처리 |
| 4 ✓ | Hermes 플러그인 패키지 | `hermes/jangin/`: 슬래시 명령, 플러그인 `pre_tool_call` 훅, 스킬 번들(`ctx.register_skill`), 시스템 프롬프트 안내, `SOUL.md`, `config.example.yaml`, `install.sh`. 카드·cron 은 아직 |
| 5 | 설치 마법사 | 완료: 터미널 `jangin setup` (hermes/jangin/setup_wizard.py). Hermes 함수로 config.yaml·.env·훅 허락 목록을 바꾼다. 남은 것: 하루 상한 |
| 6 | 배포 티켓 | `type: deploy` — 배포·상태 확인·되돌리기 명령을 한 티켓에 담아 한 번에 승인. 상태 확인 실패 시 되돌리기 티켓 자동 생성 |
| 7 | 예산 장치 | 하루 pass 수, 큐 상한(차면 예약 실행 중단), 실행 시간 상한 |
| 9 | 만들기 반복 = Hermes `/goal` | 마일스톤 → 완료 계약, 검사 명령 → 품질 관문 `op milestone done <n>`. jangin 은 테스트 약화 감지와 비용 상한만 더한다 (6.1절) |
| 8 | 감독 에이전트 | 플러그인이 다른 모델로 기준표 검토를 돌려 결과를 티켓에 기록 (에이전트가 스스로 적지 못함) |

## 6. 단계별 구현 순서

1. ✓ **시험** — 이 맥의 Hermes v0.22.5 소스와 시험용 HERMES_HOME. 결과는 7절.
2. ✓ **M1 정직한 기반** — 0, 1, 3. Claude Code·Codex 경로도 함께 좋아진다.
3. ✓ **M2 Hermes 안에서 막기** — 2. 스킬 + 셸 훅만으로 Hermes 에서 단계·큐·차단이 동작.
4. ✓ **M3 사람의 손 플러그인** — 4. 슬래시 명령으로 승인·단계 이동, 발송을 플러그인에서. (카드 버튼은 아직)
5. **M4 쉬운 시작** — 5, 7, 9. 설치 마법사, 예산 장치, 만들기 반복을 `/goal` 에 연결. 일반 사용자 첫 시험.
6. **M5 배포 관리** — 6. 비전 3순위.
7. **M6 품질** — 8, 격리 등급 2 안내와 설정 도우미.

### 6.1 만들기 단계: 반복은 Hermes `/goal` 이, 기준은 jangin 이

Hermes `/goal` 은 이미 "끝날 때까지 계속" 반복(랄프 루프)을 갖고 있다. jangin 은 반복을 따로 만들지 않고 연결만 한다.
(근거: `website/docs/user-guide/features/goals.md`, `hermes_cli/goals.py`, Hermes 0.22.5 소스. 실행 시험은 아직)

| Hermes `/goal` 이 이미 하는 것 | 내용 |
|---|---|
| 품질 관문 `/goal gate add <명령>` | 판정 모델보다 먼저 돈다. exit 0 이어야 완료 판정으로 간다. 실패하면 종료 코드와 출력 끝 약 3KB 가 다음 반복의 입력. 관문당 기본 3회 재시도·5분 제한, 다 쓰면 자동 일시정지. 관문은 세션 작업 폴더에서 돈다(`_gate_workspace`) |
| 완료 계약 | outcome, verification, constraints, boundaries, stop_when. `/goal draft` 로 초안, `/subgoal` 로 기준 추가 |
| 반복 상한 | `goals.max_turns` (기본 20) 뒤 자동 일시정지. 판정 모델이 done/continue/blocked/wait. 불가능하면 blocked 로 멈춤 |
| 기다리기·이어가기 | 백그라운드 빌드·CI 를 기다리는 wait(최대 30분), SessionDB 에 저장돼 `/resume` 뒤 이어짐 |
| 권한 | 메신저에서 `/goal gate add` 는 게이트웨이 관리자만. 에이전트는 슬래시 명령을 칠 수 없다(로컬 소켓 예외는 4절) |

연결 방식 (M4):

1. 에이전트가 만들기 단계에서 `op milestone add "예약 폼" --test "npm test -- form"` 으로 마일스톤을 등록한다 (지금과 같음).
2. 사용자가 `/build 1` (jangin 플러그인 명령). 플러그인이 마일스톤 1 을 완료 계약으로 바꾼다:
   outcome = 마일스톤 제목, verification = 검사 명령, constraints = `.operator/stages/build.md` 의 범위와 jangin 규칙,
   boundaries = 배포·게시·발송·결제 금지(승인 대기로), stop_when = 관문 통과 또는 비용 상한.
3. 관문은 검사 명령 그대로가 아니라 **`op milestone done 1`** 이다. 이 명령이 검사 명령을 돌리고, 아래 (a) 검사까지 통과해야
   exit 0 이다. 그래서 반복이 끝나면 `milestones.json` 에 통과 기록이 남고, 관문과 jangin 의 완료 기준이 하나가 된다.
4. 반복이 끝나도 단계는 그대로다. 다음 단계로는 사람이 `/advance` 한다 (`stage_move` 는 사람 경로만 받는다).

Hermes 에 없어서 jangin 이 채우는 것:

| | 무엇 | 어떻게 |
|---|---|---|
| (a) | 테스트 삭제·약화 방지 | 관문이 통과하려면 에이전트가 코드를 고치는 대신 테스트를 지우거나 약하게 만들 수 있다. `op milestone add --protect "tests/**"` 로 보호할 테스트를 정하면 등록 순간의 파일 목록·해시·테스트 개수를 `milestones.json` 에 남긴다. `op milestone done` 은 보호 파일이 사라졌거나 테스트 개수가 줄면 실패한다(바뀐 파일은 목록으로 보여 주고, 사람이 `/build` 를 다시 할 때 새 기준을 받는다). 반복 중에는 가드가 보호 파일의 삭제·덮어쓰기를 막는다(`guard.json` 의 `protect_paths`, 마일스톤이 열려 있을 때만) |
| (b) | 금액 기준 비용 상한 | Hermes 에서 금액 상한은 MCP 도구 비용의 `spend_limit`(채팅당)과 Nous 포털의 월 한도(포털에서만, 읽기 전용) 뿐이고, 모델 호출 비용으로 반복을 멈추는 설정은 찾지 못했다. Hermes 는 세션마다 `estimated_cost_usd` 를 state.db 에 기록한다. 플러그인이 이 값을 읽어 `/build` 에 정한 상한(예: `/build 1 --budget 3`)을 넘으면 `pre_tool_call` 훅에서 도구 호출을 막고 반복을 멈추게 한다. 턴 상한(`goals.max_turns`)은 그 밑의 두 번째 상한 |
| (c) | 단계 이동은 사람만 | 이미 있다 (`stage_move` + authority). `/goal` 이 done 이 돼도 `/advance` 는 사람이 친다 |

체크포인트(반복마다 되돌리기): Hermes 에 있다. `checkpoints.enabled: true` (기본 꺼짐)면 `write_file`·`patch` 와 파괴적인 터미널
명령(`rm`, `mv`, `sed -i`, `>`, `git reset` 등) 전에 턴마다·폴더마다 한 번 그림자 git 저장소에 스냅숏을 남기고, 사람이
`/rollback <N>` 으로 되돌린다. 자동으로 되돌리지는 않고, docker 같은 컨테이너 백엔드에서는 되돌리기를 거부한다.
jangin 은 자체 체크포인트를 만들지 않고, 프로필 설정에서 `checkpoints.enabled: true` 를 권한다.

확인할 것 (시험 단계): 플러그인이 `/goal` 을 코드로 시작할 공개 API 가 있는지(없으면 `/build` 가 사용자에게 `/goal …` 과
`/goal gate add …` 두 줄을 보여 주고 사용자가 친다. `hermes_cli.goals.GoalManager` 를 직접 쓰는 건 내부 API 라 피한다),
에이전트가 칸반 도구(`kanban_create`)로 `--goal` 카드를 만들어 관문을 스스로 정할 수 있는지, `estimated_cost_usd` 가
반복 중에 바로 갱신되는지, 관문이 도는 폴더가 Desktop 세션의 프로젝트 폴더와 같은지.

## 7. 검증 결과 (Hermes v0.22.5, 2026-10-30)

"소스"는 Hermes 코드를 읽어 확인한 것, "실행"은 시험용 HERMES_HOME 에 설치한 실제 Hermes 로 돌려 본 것이다
(`hermes/check_live.py`, `hermes plugins doctor`, `hermes hooks test`). 모델과의 실제 대화와 메신저 게이트웨이는 돌리지 않았다.

| 항목 | 결과 | 근거 |
|---|---|---|
| 모델이 플러그인 슬래시 명령을 실행할 수 있나 | **대부분 아니오, 구멍 하나.** cron 프롬프트는 대화로만 들어가고(`cron/scheduler.py`), 봇 채팅·heartbeat·kanban 깨우기는 명령 모양을 거부하고(`gateway/session_automation.py`), 플러그인 `inject_message` 는 명령 권한이 꺼져 있고, `hermes chat -q "/x"` 는 글자 그대로다. **하지만** Desktop·TUI·CLI 가 쓰는 로컬 RPC `slash.exec` 는 플러그인 명령을 실행하고, 그 소켓은 OS 사용자만 확인한다 → 에이전트의 터미널이 원리상 부를 수 있다. 그래서 로컬 화면 결정은 `local` 로 따로 기록하고 엄격 모드(`messenger`)로 끌 수 있게 했다. 웹훅 경로는 끝까지 추적하지 않았다 | 소스 |
| 명령 이름 | `/approve` `/deny` `/status` `/queue` 는 내장. 겹치면 등록이 조용히 건너뛰어진다 → `/ok` `/project` `/inbox` | 소스, 실행 (10개 등록 확인) |
| 명령 핸들러가 받는 것 | 첫 인자 원문 문자열 + 선언한 키워드(`source`, `platform`, `session_id`, `session_key`). 메신저는 `source.user_id`, 로컬 화면은 `source=None` | 소스, 실행 |
| 셸 훅 페이로드 | `{"hook_event_name","tool_name","tool_input","session_id","cwd","profile","extra"}`. `terminal`: `command`,`workdir` / `write_file`: `path`,`content` / `patch`: `path`,`old_string`,`new_string` 또는 `mode`+`patch`(V4A) / `read_file`: `path` / `execute_code`: `code`. **`cwd` 는 게이트웨이 프로세스의 폴더**(세션 폴더 아님) | 소스, 실행 |
| 셸 훅 차단 형식 | exit 2 + stdout `{"action":"block","message":…}` (또는 `{"decision":"block","reason":…}`). `fail_closed: true` 면 실행 실패·시간 초과·이상한 출력도 차단 | 소스, 실행 (`hermes hooks test`: 막기 exit 2, 허용 exit 0, op.py 없음 → 차단) |
| 셸 훅 첫 사용 동의 | TTY 에서 y/N, `<HERMES_HOME>/shell-hooks-allowlist.json` 에 기록. `--accept-hooks`, `HERMES_ACCEPT_HOOKS=1`, `hooks_auto_accept: true` 로 건너뜀 | 소스 |
| 플러그인 훅 | `ctx.register_hook("pre_tool_call", fn)`, `fn(tool_name, args, …)` 가 `{"action":"block","message"}` 를 돌려주면 차단. `ctx.session_cwd()` 로 세션 폴더를 안다 → 기본 가드는 플러그인 훅 | 소스, 실행 |
| 설치 | `hermes plugins install owner/repo[/하위폴더]` (하위 폴더는 sparse checkout), 매니페스트는 `plugin.yaml` (`name` 만 필수), 진입점 `__init__.py:register(ctx)`, 활성화 `plugins.enabled` 또는 `hermes plugins enable`. 스킬은 `ctx.register_skill(name, SKILL.md 경로)` 로 `jangin:jangin` | 소스, 실행 (`install.sh --home` + `plugins enable` + `plugins doctor` OK) |
| 프로필·성격 | `hermes profile create <이름>` → `~/.hermes/profiles/<이름>/SOUL.md`. 프로필 배포판(`distribution.yaml` + SOUL.md + skills/ + plugins/, `hermes profile install <repo>`) 이 있다. 플러그인이 SOUL.md 를 직접 바꾸는 API 는 없다 → 설치 스크립트가 넣고 `register_system_prompt_section` 으로 짧은 안내 | 소스(문서) |
| 에이전트가 쓸 수 있는 Hermes 파일 | `write_file` 은 `~/.hermes` 의 `config.yaml` 만 막는다. `plugin-data/`, `shell-hooks-allowlist.json` 은 쓸 수 있다 → 승인 상태는 plugin-data 가 아니라 프로젝트 `.operator/`(가드 보호)에 둔다. 프로젝트 목록은 `~/.config/operator/` (가드 보호) | 소스 |
| 실제 흐름 | `/setup folder` → `/idea` → `/stage` → `/advance`(by `local:hermes:desktop`) → `op pending add` → `/inbox` → `/ok`(메신저 source, `decided_by: messenger:hermes:telegram:42`). 같은 프로젝트에서 `script -q /dev/null op stage set` 은 exit 7 | 실행 (`hermes/check_live.py`) |

### 아직 실제로 확인하지 않은 것

| 항목 | 이유·방법 |
|---|---|
| 실제 모델과의 대화 (에이전트가 스킬을 따르는지, `/ok` 를 흉내 내려 하는지) | 모델 토큰이 들고 사용자 프로필이 필요하다. 프로필 `jangin` 에서 직접 대화로 |
| 메신저 게이트웨이 (텔레그램에서 친 `/ok` 의 `source.user_id`) | 봇 토큰과 실제 계정이 필요하다. 소스상 경로만 확인 |
| Desktop 앱에서 명령·훅 동작과 셸 훅 동의 창 모양 | Desktop 화면 조작이 필요하다 |
| 로컬 소켓 `slash.exec` 를 에이전트가 실제로 부를 수 있는지 | 원리상 가능(소스). 실제 공격 시험은 하지 않았다 |
| 게이트웨이(Desktop·launchd)에서 키체인 허락 창이 뜨는지 | `/setup unlock` 을 이 맥에서 직접 |
| 메신저 카드에 승인 버튼 붙이기 | `ctx.post_message` 는 글만 확인. 버튼은 Hermes 의 승인 전송(`register_approval_transport`)을 써야 할 수 있다 |
| docker 백엔드에서 `.operator/` 일부만 `:ro` | 격리 등급 2, M6 |
| `/goal` 연결 (6.1절): 플러그인이 goal 을 코드로 시작할 수 있는지, 칸반 `--goal`, 비용 값 갱신 시점, 관문 폴더 | 소스와 문서만 읽었다. M4 시험에서 |
| `hermes plugins install pullyo/jangin/hermes/jangin` | 하위 폴더만 받아 스킬(op.py)이 없다. 지금은 `install.sh` 로 설치 |

## 7.1 Jangin 전용 화면 (2026-10-30 구현)

OMH 처럼 Hermes 의 화면 프로그램 자리(`HERMES_TUI_DIR/dist/entry.js`, `node` 로 실행)에 우리 화면을 둔다. Hermes 코드는 고치지 않는다.
- 접속: Hermes 의 `ui-tui/scripts/gateway_bootstrap.py --start` 가 세션 티켓과 WebSocket 주소를 준다 → `new WebSocket(url, protocols)`.
- 규약(JSON-RPC 2.0, 게이트웨이 `hermes-gateway-v1`): 첫 이벤트 `gateway.ready` → `runtime.describe`(session_create 계약에 `tui` 가 있어야 함)
  → `session.create {request_id, source: 'tui', cwd}` → `session.info` → `prompt.submit {session_id, text, input_id}`.
  이벤트 프레임은 `{method:'event', params:{type, session_id, payload, execution_generation, …}}`: message.start/delta/complete,
  tool.start/complete, status.update, approval.request → `approval.respond {session_id, execution_generation, prompt_id, choice}`,
  clarify.request → `clarify.respond {…, answer}`, 중단 `session.interrupt {session_id, execution_generation}`, 슬래시 `slash.exec {session_id, command}`.
  20초마다 `gateway.ping`. 실제 Hermes 0.22.5 에서 세션 생성·답변·슬래시·종료를 확인했다.
- 남은 것: 세션 이어서 열기(`HERMES_TUI_RESUME`)는 구현만 하고 실제 확인 전, 이미지 첨부·음성·세션 목록 화면 없음, 마크다운은 그대로 출력.

## 8. 하지 않는 것 (이 설계 범위 밖)

- Hermes 자체를 고치거나 포크하지 않는다. 문서화된 확장 지점(스킬, 셸 훅, 플러그인, cron)만 쓴다.
- 다음 후보: 이 저장소를 **프로필 배포판**으로도 만들기(루트에 `distribution.yaml`, 또는 별도 저장소). 그러면
  `hermes profile install pullyo/jangin` 한 줄로 성격·스킬·플러그인이 같이 들어온다. 아직 시험하지 않았다.
- oh-my-hermes 의존은 넣지 않는다. 설치돼 있으면 만들기 단계의 큰 마일스톤을 맡기는 선택 연동만 나중에 검토한다.
- 자체 앱, 자체 텔레그램 봇 확장은 더 하지 않는다. 기존 `op telegram` 은 Hermes 를 쓰지 않는 사람을 위해 유지한다.
