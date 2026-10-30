# 게시 채널, 토큰, 원격 승인

티켓의 `type`/`channel` 이 아래 채널이면 `op pending add` 가 action 을 `op deliver <id>` 로 자동으로 채운다.
사람이 승인하면 그 action 이 실행된다. 토큰은 티켓·로그에 쓰지 않는다.

| 채널 | 티켓 | 필요한 값 | 비고 |
|---|---|---|---|
| x | `type: post`, `channel: x` | `X_USER_ACCESS_TOKEN` (자동 갱신: `X_REFRESH_TOKEN`, `X_CLIENT_ID`, 선택 `X_CLIENT_SECRET`) | `op connect x` 로 한 번 연결 |
| threads | `type: post`, `channel: threads` | `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN` | `threads_content_publish` 권한. 컨테이너 생성 → 게시 2단계 |
| email | `type: email` (`to:`, `subject:` 필수) | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (`SMTP_PORT`=587 기본, 465 면 SSL) | Gmail 은 앱 비밀번호 |
| webhook | `type: post`, `channel: webhook` | `OPERATOR_WEBHOOK_URL` | Slack/Discord 수신 웹훅. 본문을 `text`·`content` 로 보냄 |

지원 채널 밖(LinkedIn, Instagram 등)은 `--action` 에 직접 명령을 적어 승인한다.

## 발송 방식 — 누가 보내나

`.operator/guard.json` 의 `send_mode` (에이전트가 고칠 수 없는 파일). `op init --send human|agent` 로 처음에 정한다.

| | human (기본) | agent |
|---|---|---|
| 언제 나가나 | 사람이 승인하는 순간 (`op pending approve`, `op serve`, `op telegram`) | 승인 뒤 에이전트가 `op send <id>` |
| 토큰을 읽는 프로세스 | 사람이 띄운 프로세스만 | 에이전트의 `op send` 가 띄운 프로세스 |
| 에이전트의 `op send` | 거부 (exit 6) | 승인된 action 만 실행 |

`op pending approve <id> --no-send` 는 승인만 하고 보내지 않는다. 나중에 사람이 자기 터미널에서 `op send <id>`.

## 토큰 저장 — `op secret`

```bash
op secret set X_CLIENT_ID          # 사람만, 대화형 터미널. 값은 화면에 보이지 않게 입력
op secret set OPERATOR_WEBHOOK_URL --file   # 키체인 대신 파일에
op secret list                     # 이름과 저장 위치만 (값은 출력 안 함)
op deliver --check                 # 채널별 준비 상태
op secret rm THREADS_ACCESS_TOKEN
```

- **macOS 기본은 키체인**이다 (`security`, 서비스 이름 `operator` — 엔진 내부 이름이라 그대로). 어떤 프로그램도 묻지 않고 읽을 수 없게 저장하므로
  읽을 때마다 macOS 가 허락을 묻는다. **"항상 허용"은 누르지 않는다.** `op serve`/`op telegram` 은 시작할 때 한 번에 읽어
  메모리에 들고 있으므로, 시작할 때만 허락하면 된다.
- 다른 운영체제나 `--file` 은 `~/.config/operator/env` (권한 600). 이름 목록은 같은 폴더의 `secrets.json` (값 없음).
- 환경 변수가 있으면 그 값이 먼저다.
- 가드는 에이전트가 `~/.config/operator/` 를 읽거나(셸, Read 도구), `security find-generic-password`, `printenv` 를
  실행하는 것을 막는다. 훅이 없는 도구에서는 키체인 허락 창이 마지막 방어선이다.

## X — 연결과 자동 갱신

1. [X 개발자 포털](https://developer.x.com)에서 앱을 만들고 User authentication 을 켠다. 권한 Read and write,
   Type 은 Native App(공개 클라이언트) 또는 Web App(기밀 클라이언트), Callback URI `http://127.0.0.1:8766/callback`.
2. `op secret set X_CLIENT_ID` (Web App 이면 `X_CLIENT_SECRET` 도).
3. `op connect x` → 브라우저에서 로그인·허용. 받은 토큰은 저장소에 들어간다 (scope: `tweet.read tweet.write users.read offline.access`).

게시 중 401 이 오면 `op deliver` 가 갱신 토큰으로 새 토큰을 받아 저장하고 한 번 다시 보낸다. X 는 갱신 토큰도 매번
바꾸므로 새 값을 저장한다. 갱신이 실패하면 티켓은 approved 에 남고, 사람이 `op connect x` 를 다시 한다.
Threads 장기 토큰은 60일이며 자동 갱신하지 않는다.

## 밖에서 승인 — 텔레그램

봇이 텔레그램 서버에 먼저 연결해 메시지를 가져오므로 컴퓨터에 포트를 열 필요가 없고 통신은 HTTPS 다.

1. 텔레그램에서 @BotFather → `/newbot` → 받은 토큰을 `op secret set TELEGRAM_BOT_TOKEN`.
2. 만든 봇에게 아무 메시지나 보낸 뒤 `op telegram --setup` → 개인 대화방 번호를 `op secret set TELEGRAM_CHAT_ID`.
3. `op telegram` 을 띄워 둔다. 새 승인 대기마다 카드가 오고 **승인**·**거절** 버튼이 붙는다.
   거절을 누르면 사유를 묻고, 답장이 `feedback.md` 에 쌓인다. `/list`, `/approve 0003`, `/reject 0003 사유` 도 된다.

- 등록한 대화방 말고는 전부 무시한다. 그룹 대화방은 쓰지 않는다 (구성원 누구나 버튼을 누를 수 있다).
- 카드에는 초안 본문이 들어가므로 텔레그램 서버를 거친다. 본문을 보내기 싫으면 `op telegram --titles-only`.
- 발송 방식이 human 이면 승인 버튼을 누르는 순간 이 프로세스가 보낸다.

## 같은 Wi-Fi 에서 승인 — `op serve --lan`

1회용 토큰이 있는 주소를 휴대폰으로 연다. HTTPS 가 아니므로 믿을 수 있는 네트워크에서만 쓰고, 인터넷에 열지 않는다.
밖에서는 텔레그램을 쓰거나 Tailscale 같은 사설 VPN 으로 붙는다.
