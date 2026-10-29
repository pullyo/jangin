# 승인 게이트(가드) 규칙

`op guard` 는 에이전트의 도구 호출 직전에 훅으로 실행된다. 입력(stdin JSON)에서 셸 명령과 파일 경로를
뽑아 아래 규칙과 대조하고, 걸리면 호출을 거부한다. 거부 사유는 모델에게 돌아가서 "그럼 pending 에 올려야겠다"
로 이어진다. `.operator/` 가 없는 프로젝트에선 아무것도 막지 않는다 (간섭 없음).

## 어느 프로젝트의 규칙을 적용하나

호출이 닿을 수 있는 operator 프로젝트를 모두 찾아, 그중 하나라도 막으면 막는다. 찾는 곳:

1. 훅 입력의 `cwd` (Claude Code·Codex 가 세션 작업 폴더를 넘긴다. 없으면 훅 프로세스의 작업 폴더)
2. 명령 안의 `cd` / `pushd` / `Set-Location` 대상 (연속된 상대 `cd` 도 따라간다), `git -C <폴더>`, `--cwd` / `--prefix` / `--dir`
3. Write·Edit·apply_patch 대상 파일이 있는 폴더

각 위치에서 위로 올라가며 `.operator/` 를 찾는다. 그래서 다른 폴더에서 연 세션이 `cd 프로젝트 && wrangler deploy`
처럼 들어가 실행하는 명령도 막힌다. `$HOME`, `%USERPROFILE%` 같은 변수가 든 경로는 해석하지 않는다(그런 명령은
세션 폴더 기준으로만 본다). 판정은 찾은 프로젝트마다 그 프로젝트의 `guard.log` 에 세션 `cwd` 와 함께 남는다.
`op guard check --cwd <폴더> "<명령>"` 으로 같은 판정을 미리 볼 수 있다.

## 기본 차단 명령 (`DEFAULT_GUARD.deny_commands`, 대소문자 무시)

| 분류 | 패턴 (요지) |
|---|---|
| 발송 | `sendmail`, `mail`, `mutt`, `swaks`, `gh pr/issue create/merge/comment`, `agentmail ... send` |
| 게시 | `curl` → twitter/x/facebook/threads/linkedin/instagram API, `curl -X POST/PUT/DELETE/PATCH` 외부 URL (localhost 제외) |
| 배포 | `vercel/netlify/wrangler/fly/railway/render deploy|publish|up`, `vercel --prod`, `supabase db push / functions deploy / secrets set`, `git push` (`git -C <폴더> push`, `git -c … push` 포함), `npm publish` |
| 결제·도메인 | `stripe ... charges/payment_intents/... create/confirm/capture`, 레지스트라 `register/purchase/buy` |
| 파괴 | 재귀 삭제 `rm -r`/`--recursive` (`.operator/tmp` 아래는 제외; 단일 파일 `rm -f` 는 통과), `git push --force`, `git branch -D`, `git reset --hard`, `DROP TABLE/DATABASE/SCHEMA`, `supabase projects delete` |

## 사람 전용 명령 (`human_only_commands`)

`op pending approve`, `op pending reject`, `op approve`, `op reject`. 에이전트 세션에선 훅이 막는다.
사람은 훅이 없는 자기 터미널에서 실행한다. Claude 데스크톱 앱이라면 Terminal 패널.
훅과 별개로 approve/reject 명령 자체가 **대화형 터미널(TTY)** 을 요구한다. 에이전트의 셸 도구에는 터미널이 없어
스크립트를 복사해 돌려도 거부된다. 자동화에서 꼭 필요하면 사람이 `OPERATOR_ALLOW_NONINTERACTIVE_APPROVE=1` 을 직접 설정한다.

## 보호 경로 (`deny_paths`) — Write/Edit/apply_patch 대상

`.operator/pending/`, `.operator/approved/`, `.operator/sent/`, `.operator/rejected/`, `.operator/guard.json`.
큐는 `op pending add` 로만 들어가고, 상태 변경은 `op pending approve/reject` 와 `op send` 로만 일어난다.

셸 명령도 같은 규칙이다. 명령이 큐 경로를 언급하면 읽기 전용 명령(`cat`, `ls`, `head`, `grep`, `find`, `diff`, `jq` 등)만
통과하고, `mv`/`cp`/`>`/`sed -i`/파이썬 한 줄 같은 쓰기는 전부 막힌다. `.operator` 폴더 자체를 옮기거나 지우는 것도 막힌다.

## 통과 조건

- `op send <id>` 이고 `<id>` 가 `approved/` 에 있을 때. `op send` 는 티켓에 승인된 `action` 만 실행하고, 명령을
  같이 주면 action 과 같을 때만 받아들인다. action 안에 `op pending`/`op send` 가 들어 있으면 실행하지 않는다.
- `.operator/guard.json` 의 `allow_commands` 에 맞을 때 (deny 보다 먼저 본다). 예: 내부 스테이징 배포를 늘 허용하고 싶을 때.

## 프로젝트별 추가 — `.operator/guard.json`

```json
{
  "deny_commands": ["\\bmy-cli\\s+post\\b"],
  "human_only_commands": [],
  "deny_paths": ["content/published/"],
  "allow_commands": ["\\bwrangler\\s+deploy\\s+--env\\s+staging\\b"]
}
```

이 파일 자체가 보호 경로라 에이전트는 못 고친다. 사용자가 편집한다.

## 훅 입력 형식 (도구별)

| 도구 | 명령 위치 | 파일 경로 위치 | 거부 방식 (`--format`) |
|---|---|---|---|
| Claude Code (PreToolUse) | `tool_input.command` | `tool_input.file_path` | `claude`: exit 2 + stderr |
| Codex (PreToolUse) | `tool_input.command` (문자열 또는 `["bash","-lc",...]`) | apply_patch 의 `*** Update File:` 줄 | `codex`: exit 2 + stderr |
| Cursor (beforeShellExecution) | `command` | — | `cursor`: stdout `{"permission":"deny",...}` |
| Gemini CLI (BeforeTool) | `tool_input.command` | `tool_input.file_path` | `gemini`: stdout `{"decision":"deny","reason":...}` |

모든 결정은 `.operator/guard.log` 에 한 줄씩 남는다. 훅 없는 환경에선 `op guard check "<명령>"` 으로 수동 확인.
