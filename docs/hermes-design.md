# operator × Hermes 설계

상태: 설계 초안 (2026-10-30). 구현 전. 근거는 Hermes Agent 공식 문서(보안, 훅, 플러그인, 설정)이며
"검증 필요" 표시가 있는 항목은 실제 설치 시험으로 확인한다.

## 1. 왜 Hermes 인가

[VISION.md](../VISION.md) 의 목표는 일반 사용자도 쓰는 "구상 → 개발 → 배포 관리" 전용 AI 비서다.
지금 operator 는 터미널 명령을 알아야 쓸 수 있다. Hermes Agent 는 그 빈자리를 이미 채우고 있다.

| 필요한 것 | Hermes 가 이미 가진 것 |
|---|---|
| 앱 | Hermes Desktop (맥, 윈도우), 안드로이드(Termux) |
| 메신저 대화 | 텔레그램, 디스코드, 슬랙, 왓츠앱, 시그널 게이트웨이 |
| 생각하는 손 | Hermes 자체 에이전트. Claude Code·Codex 설치가 필요 없다 |
| 스킬 | Agent Skills 표준 호환. operator SKILL.md 를 그대로 읽는다 |
| 실행 전 차단 | 셸 훅 `pre_tool_call` (exit 2 또는 block JSON, `fail_closed`) — CLI, 게이트웨이, Desktop 모두 |
| 사람 확인 | 훅이 `{"action":"approve"}` 를 돌려주면 Hermes 의 사람 승인 화면으로 넘어간다 (텔레그램·디스코드·슬랙 버튼) |
| 사람만 치는 명령 | 플러그인 `ctx.register_command` → 사용자가 치는 `/명령`, 게이트웨이 프로세스에서 플러그인 코드가 처리 |
| 예약 | 내장 cron, 결과를 메신저로 전달. cron 의 위험 명령은 기본 거부(`cron_mode: deny`) |
| 격리 | Docker 터미널 백엔드, `docker_volumes` 에 `:ro` 마운트 |

그래서 앱·메신저·예약·모델 실행은 Hermes 에 맡기고, operator 는 **단계, 승인 큐, 검증, 차단, 사람만 하는 단계 이동과 발송**에 집중한다.
Claude Code, Codex, Cursor, Gemini CLI 지원은 그대로 둔다. Hermes 는 일반 사용자용 기본 경로가 된다.

## 2. 사용자가 겪는 흐름

1. Hermes Desktop 을 설치하고 처음 설정(모델 로그인)을 마친다.
2. 대화창에 한 줄: `/plugin install pullyo/operator-skill` 에 해당하는 설치 (검증 필요: 저장소에서 플러그인 설치 방식).
3. `/operator setup` — 플러그인이 대화로 묻는다: 프로젝트 폴더 위치, 메신저 승인 사용 여부, 하루 실행 상한.
4. `/idea 동네 빵집 예약 페이지` — 프로젝트 폴더를 만들고 발견 단계 대화가 시작된다. 에이전트가 한 번에 하나씩 묻는다.
5. 발견 문서가 채워지면 에이전트가 "다음 단계로 넘길 준비가 됐습니다"라고 알린다. 사용자가 `/advance` (또는 카드의 버튼).
6. 만들기 단계: 에이전트가 마일스톤을 만들고 검사를 통과시킨다. 첫 배포는 승인 카드로 온다.
7. 배포 카드에서 승인 → 플러그인이 배포하고 상태 확인을 돌린다. 실패하면 되돌리기 카드가 온다.
8. 운영·배우기: 매일 아침 예약 실행이 초안을 큐에 올리고 카드로 알린다. 주간 회고가 메신저로 온다.

사용자가 쓰는 것은 대화와 `/명령` 몇 개뿐이다. 터미널은 열지 않는다.

## 3. 구조

```
 Hermes 게이트웨이 프로세스 (사람의 손)
 ├── operator 플러그인
 │     /idea /status /stage /advance /back /queue /approve /reject /setup
 │     카드 게시(ctx.post_message), 승인 시 발송·배포 실행, 상태 확인, 되돌리기 티켓
 │     토큰: 게이트웨이 시작 때 키체인에서 한 번 읽어 메모리에만 (허락 창은 그때 한 번)
 │     cron 등록: 매일 pass, 주간 회고
 └── Hermes 에이전트 (생각하는 손)
       operator 스킬을 읽고 구상 질문, 조사, 문서, 코딩, 검사
       도구 호출마다 → pre_tool_call 셸 훅 → `op guard --format hermes` (fail_closed)
       터미널 백엔드: local (기본) 또는 docker (격리 등급)
```

| 지금 operator | Hermes 에서 |
|---|---|
| `op stage advance/back/set` (터미널) | `/advance`, `/back <단계> <이유>`, 카드 버튼 |
| `op pending approve/reject` (터미널) | `/approve 0003`, `/reject 0003 <이유>`, 카드 버튼 |
| `op telegram`, `op serve` | 필요 없음. Hermes 게이트웨이와 Desktop 이 대신한다 |
| `op secret set` | `/operator secret <이름>` — 값은 대화에 쓰지 않고 Desktop 의 입력 창이나 키체인 허락으로 (검증 필요) |
| 훅 (Claude Code / Codex) | Hermes 셸 훅 `pre_tool_call` |
| launchd 예약 | Hermes cron |
| `op status`, `op stage`, `op pending list` | `/status`, `/stage`, `/queue` (에이전트도 읽기 명령은 그대로 쓴다) |

## 4. "사람만" 을 어떻게 증명하나

### 지금 방식의 약점 (2026-10-30 확인)

operator 0.5.0 은 사람 확인을 두 가지로 한다: 대화형 터미널(TTY) 검사와 `OPERATOR_ALLOW_NONINTERACTIVE_APPROVE=1`.
둘 다 우회할 수 있다.

- macOS 의 `script -q /dev/null <명령>` 은 가짜 터미널을 만들어 TTY 검사를 통과한다 (이 맥에서 확인).
- 가드는 명령 문자열을 읽는다. 에이전트가 승인 명령을 파일에 써 두고 `bash x.sh` 로 실행하면 가드는 `bash x.sh` 만 본다.
- 환경 변수는 에이전트가 스스로 설정할 수 있다.

즉 훅은 실수와 일반적인 시도는 막지만, 작정한 우회를 막는 보장은 아니다. README 의 "스크립트를 복사해 돌려도
에이전트는 실행할 수 없다"는 표현은 고쳐야 한다 (구현 0단계).

### Hermes 에서의 사람 확인

사람의 결정은 **에이전트가 만들 수 없는 경로**로만 들어오게 한다.

1. **플러그인 슬래시 명령.** `/approve`, `/advance` 는 사용자가 메신저나 Desktop 에 친 메시지로만 생기고, 게이트웨이 프로세스의
   플러그인 코드가 처리한다. 에이전트의 도구 호출로는 사용자 메시지를 만들 수 없다 (검증 필요). 게이트웨이의 사용자 허용 목록이
   누가 명령을 칠 수 있는지 정한다.
2. **플러그인이 op 를 직접 부른다.** 셸 명령 + 환경 변수가 아니라, 플러그인이 op 모듈을 가져와 `decide(…, authority=plugin)` 같은
   함수를 호출한다. op 의 승인 함수에서 TTY·환경 변수 우회 경로는 없앤다.
3. **발송과 배포는 플러그인이 실행한다.** 토큰은 키체인에서 게이트웨이가 시작할 때 읽어 메모리에만 둔다. 에이전트가 큐 파일을
   위조해도, 발송은 사람이 `/approve` 할 때 플러그인에서만 일어나므로 아무것도 나가지 않는다.

### 격리 등급

| 등급 | 설정 | 막는 것 | 못 막는 것 |
|---|---|---|---|
| 1 기본 | 터미널 백엔드 local + 셸 훅 + 플러그인 | 실수, 일반적인 외부 명령, op 채널(X·Threads·메일·웹훅) 무단 발송 (토큰이 키체인 + 플러그인에만 있음) | 스크립트로 감싼 우회, 에이전트가 이미 로그인된 CLI(예: `wrangler login` 상태)로 직접 배포 |
| 2 격리 (실계정 권장) | 터미널 백엔드 docker. 프로젝트만 마운트, `.operator/` 의 approved·sent·rejected·stage.json·guard.json 은 `:ro`, `~/.config/operator` 와 배포 CLI 로그인 정보는 마운트 안 함 | 등급 1 + 스크립트 우회, 큐·단계 위조, 직접 배포 | Docker Desktop 설치가 필요 (일반 사용자에게 부담) |

일반 사용자 기본값은 등급 1, 실제 배포 계정을 연결하면 등급 2 를 권한다. 배포 명령은 등급 1 에서도 플러그인이 실행하도록
배포 토큰을 `op secret` 으로만 받고, CLI 를 미리 로그인해 두지 말라고 안내한다.

## 5. operator 쪽에서 바꿀 것

| # | 변경 | 내용 |
|---|---|---|
| 0 | 정직한 문서 | README·SKILL 의 TTY 우회 불가 표현 수정, 격리 등급 설명 추가 |
| 1 | 사람 권한 추상화 | `authority = tty | plugin` 으로 정리. 환경 변수 우회 제거(테스트는 별도 주입 방식으로), 플러그인 경로는 모듈 함수로만 |
| 2 | `op guard --format hermes` | Hermes 페이로드(`tool_name`: terminal/write_file/patch/read_file, `tool_input`, `cwd`) 해석, exit 2 + block JSON |
| 3 | op 를 모듈로 | `op.py` 의 핵심을 함수 API 로 (stage_advance, pending_decide, run_action). CLI 는 그 위의 얇은 껍데기 |
| 4 | Hermes 플러그인 패키지 | `hermes/operator/` (plugin.yaml, `__init__.py`): 슬래시 명령, 카드, cron 등록, 스킬 번들(`ctx.register_skill`), 셸 훅 설정 안내 |
| 5 | 설치 마법사 | `/operator setup` 대화형. 훅 설정을 config.yaml 에 쓰고 허용 목록 안내, 프로젝트 폴더, 하루 상한 |
| 6 | 배포 티켓 | `type: deploy` — 배포·상태 확인·되돌리기 명령을 한 티켓에 담아 한 번에 승인. 상태 확인 실패 시 되돌리기 티켓 자동 생성 |
| 7 | 예산 장치 | 하루 pass 수, 큐 상한(차면 예약 실행 중단), 실행 시간 상한 |
| 8 | 감독 에이전트 | 플러그인이 다른 모델로 기준표 검토를 돌려 결과를 티켓에 기록 (에이전트가 스스로 적지 못함) |

## 6. 단계별 구현 순서

1. **시험 (반나절)** — 이 맥에 Hermes 설치, 아래 "검증 필요" 항목 확인. 결과에 따라 이 문서 수정.
2. **M1 정직한 기반** — 0, 1, 3. Claude Code·Codex 경로도 함께 좋아진다.
3. **M2 Hermes 안에서 막기** — 2. 스킬 + 셸 훅만으로 Hermes 에서 단계·큐·차단이 동작.
4. **M3 사람의 손 플러그인** — 4. 슬래시 명령과 카드로 승인·단계 이동, 발송을 플러그인에서.
5. **M4 쉬운 시작** — 5, 7. 설치 마법사와 예산 장치. 일반 사용자 첫 시험.
6. **M5 배포 관리** — 6. 비전 3순위.
7. **M6 품질** — 8, 격리 등급 2 안내와 설정 도우미.

## 7. 검증 필요

| 항목 | 확인 방법 |
|---|---|
| 에이전트가 플러그인 슬래시 명령을 실행할 수 없는가 (사용자 메시지 위조 불가) | 에이전트에게 `/approve` 를 시켜 보고, 플러그인 코드에 호출 경로 로그 |
| Desktop 세션에서 셸 훅 `pre_tool_call` 페이로드의 도구 이름과 `cwd` | `hermes hooks test pre_tool_call --for-tool terminal` 과 실제 Desktop 대화 |
| 저장소(GitHub)에서 플러그인 + 스킬을 한 번에 설치하는 방법 | `hermes plugins install`, `hermes skills tap add` 시험 |
| 게이트웨이(Desktop 앱 또는 launchd)에서 키체인 허락 창이 뜨는가 | 시작 시 `security find-generic-password` 호출 |
| 플러그인이 메신저 카드에 버튼을 붙일 수 있는가, 아니면 `/명령` 만 되는가 | `ctx.post_message` 와 승인 escalate 동작 확인 |
| 셸 훅 동의(첫 사용 허락)를 일반 사용자에게 어떻게 안내할지 | Desktop 에서 첫 사용 프롬프트 모양 확인 |
| docker 백엔드에서 중첩 `:ro` 마운트로 `.operator/` 일부만 읽기 전용이 되는가 | 컨테이너 안에서 쓰기 시도 |

## 8. 하지 않는 것 (이 설계 범위 밖)

- Hermes 자체를 고치거나 포크하지 않는다. 문서화된 확장 지점(스킬, 셸 훅, 플러그인, cron)만 쓴다.
- oh-my-hermes 의존은 넣지 않는다. 설치돼 있으면 만들기 단계의 큰 마일스톤을 맡기는 선택 연동만 나중에 검토한다.
- 자체 앱, 자체 텔레그램 봇 확장은 더 하지 않는다. 기존 `op telegram` 은 Hermes 를 쓰지 않는 사람을 위해 유지한다.
