# 게시 채널 설정

티켓의 `type`/`channel` 이 아래 채널이면 `op pending add` 가 action 을 `op deliver <id>` 로 자동으로 채운다.
사람이 그 action 을 승인하면 `op send <id>` 가 실제로 보낸다. 토큰은 환경 변수나 프로젝트 밖
`~/.config/operator/env`(권한 600 권장)에서만 읽고, 티켓·로그에는 쓰지 않는다.

| 채널 | 티켓 | 필요한 값 | 비고 |
|---|---|---|---|
| x | `type: post`, `channel: x` | `X_USER_ACCESS_TOKEN` | X API v2 사용자 컨텍스트 OAuth 2.0 토큰, `tweet.write` 범위. 앱 토큰(Bearer)으로는 게시 불가 |
| threads | `type: post`, `channel: threads` | `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN` | `threads_content_publish` 권한. 컨테이너 생성 → 게시 2단계 |
| email | `type: email` (`to:`, `subject:` 필수) | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (`SMTP_PORT`=587 기본, 465 면 SSL) | Gmail 은 앱 비밀번호 |
| webhook | `type: post`, `channel: webhook` | `OPERATOR_WEBHOOK_URL` | Slack/Discord 수신 웹훅. 본문을 `text`·`content` 로 보냄 |

```bash
op deliver --check      # 각 채널이 준비됐는지 (값은 출력하지 않음)
```

```
# ~/.config/operator/env  (프로젝트 밖, chmod 600)
X_USER_ACCESS_TOKEN=...
THREADS_USER_ID=...
THREADS_ACCESS_TOKEN=...
```

토큰 만료: X 사용자 토큰은 보통 2시간이라 장기 운영에는 refresh 흐름이 필요하다(이 스킬은 갱신하지 않는다).
Threads 장기 토큰은 60일. 만료되면 `op send` 가 HTTP 401 로 실패하고 티켓은 approved 에 남아 다시 보낼 수 있다.

주의: 에이전트도 같은 컴퓨터에서 돌기 때문에 이 파일을 읽을 수 있다. 가드는 외부 POST 를 막지만 완전한
비밀 격리는 아니다. 게시 전용으로 권한을 최소화한 토큰을 쓴다.

지원 채널 밖(LinkedIn, Instagram 등)은 지금처럼 `--action` 에 직접 명령을 적어 승인한다.
