# 예약 실행 — 하루 한 번 pass 돌리기

operator 는 혼자 돌지 않는다. 사용자가 시킬 때 한 pass 를 돈다. 매일 돌리려면 운영체제의 예약 기능으로
에이전트를 비대화형으로 한 번 실행하게 한다. 예약 실행에서도 규칙은 그대로다.

- 승인 큐에 올리는 데까지만 한다. 예약 실행에는 터미널이 없으므로 `op pending approve` 와 `op serve` 는 거부된다.
- 훅은 비대화형 실행에도 걸린다. 발송·게시·배포 명령은 막히고 큐로 간다.
- 끝나면 `op notify` 로 승인 대기 건수만 휴대폰에 알린다 (본문은 보내지 않음).

## 실행할 한 줄

프로젝트 폴더에서 에이전트에게 pass 하나를 시키는 명령이다. 둘 중 쓰는 도구 하나를 고른다.

```bash
# Claude Code
claude -p "operator 스킬로 이 프로젝트의 오늘 pass 를 한 번 돌리고, 끝나면 op notify 를 실행해." --permission-mode acceptEdits
# Codex CLI
codex exec "operator 스킬로 이 프로젝트의 오늘 pass 를 한 번 돌리고, 끝나면 op notify 를 실행해."
```

`--permission-mode acceptEdits` 는 파일 편집을 묻지 않게 한다. 셸 명령 허용 범위는 각 도구의 권한 설정을 따른다.
처음 몇 번은 터미널에서 직접 실행해 결과를 보고, 문제가 없을 때 예약으로 옮긴다.

## macOS — launchd

`assets/templates/launchd.plist` 를 복사해 `PROJECT_DIR`, `AGENT_COMMAND` 를 채우고 `~/Library/LaunchAgents/` 에 둔다.

```bash
cp assets/templates/launchd.plist ~/Library/LaunchAgents/local.operator.daily.plist
# 파일 안의 PROJECT_DIR, AGENT_COMMAND 를 실제 값으로 바꾼 뒤
launchctl load ~/Library/LaunchAgents/local.operator.daily.plist
```

기본은 매일 09:00. 로그는 프로젝트의 `.operator/tmp/schedule.log`. 끄려면 `launchctl unload` 후 파일 삭제.
외장 드라이브의 프로젝트는 드라이브가 연결돼 있을 때만 돈다(없으면 그날은 건너뜀).

## Linux / macOS — cron

```cron
0 9 * * * cd "/path/to/project" && claude -p "operator 스킬로 오늘 pass 를 한 번 돌리고 op notify 를 실행해." >> .operator/tmp/schedule.log 2>&1
```

cron 은 로그인 셸 환경이 없으므로 `claude`/`codex` 의 절대 경로와 필요한 환경 변수(토큰 아님, PATH 등)를 적는다.

## Windows — 작업 스케줄러

```powershell
schtasks /Create /SC DAILY /ST 09:00 /TN "operator-daily" /TR "cmd /c cd /d D:\path\to\project && claude -p \"operator 스킬로 오늘 pass 를 한 번 돌리고 op notify 를 실행해.\" >> .operator\tmp\schedule.log 2>&1"
```

## 휴대폰 알림 (ntfy)

[ntfy](https://ntfy.sh) 앱을 설치하고 추측하기 어려운 주제 이름을 하나 구독한다. 그 이름을 환경 변수나
`~/.config/operator/env` 에 넣는다.

```
OPERATOR_NTFY_TOPIC=operator-<임의의 긴 문자열>
# 자체 서버를 쓰면
OPERATOR_NTFY_SERVER=https://ntfy.example.com
```

공개 ntfy.sh 주제는 이름을 아는 누구나 읽을 수 있다. 그래서 `op notify` 는 프로젝트 이름과 대기 건수만 보낸다.

## 휴대폰으로 승인하기

알림을 받으면 컴퓨터 터미널에서 `op serve --lan` 을 실행해 같은 Wi-Fi 의 휴대폰으로 주소를 연다.
주소에 1회용 토큰이 들어 있고, 서버를 끄면 무효가 된다. HTTPS 가 아니므로 집·사무실처럼 믿을 수 있는 네트워크에서만 쓴다.
밖에서 승인하려면 Tailscale 같은 사설 VPN 으로 컴퓨터에 붙어서 같은 주소를 연다(포트를 인터넷에 열지 않는다).
