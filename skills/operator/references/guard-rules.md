# 승인 게이트(가드) 규칙

`op guard` 는 에이전트의 도구 호출 직전에 훅으로 실행된다. 입력(stdin JSON)에서 셸 명령과 파일 경로를
뽑아 아래 규칙과 대조하고, 걸리면 호출을 거부한다. 거부 사유는 모델에게 돌아가서 "그럼 pending 에 올려야겠다"
로 이어진다. `.operator/` 가 없는 프로젝트에선 아무것도 막지 않는다 (간섭 없음).

## 기본 차단 명령 (`DEFAULT_GUARD.deny_commands`, 대소문자 무시)

| 분류 | 패턴 (요지) |
|---|---|
| 발송 | `sendmail`, `mail`, `mutt`, `swaks`, `gh pr/issue create/merge/comment`, `agentmail ... send` |
| 게시 | `curl` → twitter/x/facebook/threads/linkedin/instagram API, `curl -X POST/PUT/DELETE/PATCH` 외부 URL (localhost 제외) |
| 배포 | `vercel/netlify/wrangler/fly/railway/render deploy|publish|up`, `vercel --prod`, `supabase db push / functions deploy / secrets set`, `git push`, `npm publish` |
| 결제·도메인 | `stripe ... charges/payment_intents/... create/confirm/capture`, 레지스트라 `register/purchase/buy` |
| 파괴 | `rm -r*/-f*` (`.operator/tmp` 제외), `git push --force`, `git branch -D`, `git reset --hard`, `DROP TABLE/DATABASE/SCHEMA`, `supabase projects delete` |

## 사람 전용 명령 (`human_only_commands`)

`op pending approve`, `op pending reject`, `op approve`, `op reject`. 에이전트 세션에선 훅이 막는다.
사람은 훅이 없는 자기 터미널에서 실행한다. Claude 데스크톱 앱이라면 Terminal 패널.

## 보호 경로 (`deny_paths`) — Write/Edit/apply_patch 대상

`.operator/pending/`, `.operator/approved/`, `.operator/sent/`, `.operator/rejected/`, `.operator/guard.json`.
큐는 `op pending add` 로만 들어가고, 상태 변경은 `op pending approve/reject` 와 `op send` 로만 일어난다.

## 통과 조건

- `op send <id> -- ...` 이고 `<id>` 가 `approved/` 에 있을 때. (`op send` 자체도 다시 확인한다.)
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
