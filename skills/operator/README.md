# operator

"적게 하지만 절대 안 어기는" 운영 스킬. Foundable 의 AI 직원 Ted 가 인프라(Temporal·Modal·승인 큐)로
강제하던 네 가지 — **승인 게이트 · 재개 가능한 pass · 검증 게이트 · 모델 라우팅** — 를 python3 스크립트와
JSON 파일 수준으로 옮겼다. [Agent Skills 표준](https://agentskills.io/specification) 형식이라
Claude Code, Codex CLI, Cursor, Gemini CLI 등 이 표준을 읽는 도구에서 **같은 폴더 그대로** 쓴다.

```
operator/
├── SKILL.md                 ← 에이전트가 읽는 본문 (모드: plan / run / approve / status)
├── scripts/op, op.py        ← 단일 CLI. 표준 라이브러리만. (state.json · pending/ · verify · guard · llm)
├── references/              ← 설계 근거(Foundable 조사), pass 흐름, 검증·가드 규칙, 라우팅
├── assets/templates/        ← business.md, post/email/research 초안 템플릿
├── assets/hooks/            ← 도구별 훅 설정 + 훅 없는 도구용 AGENTS.md 스니펫
├── agents/openai.yaml       ← Codex 가 표시하는 메타데이터
├── evals/                   ← 테스트 프롬프트 3개 (claude plugin eval 형식)
└── install.sh               ← 여러 도구에 설치
```

## 설치

```bash
sh operator/install.sh                 # ~/.claude, ~/.codex, ~/.cursor, ~/.gemini 중 있는 곳에 링크
sh operator/install.sh --project .     # 프로젝트 레벨 (.agents/skills/operator 등)
sh operator/install.sh --print-hooks   # 훅 스니펫 출력
```

수동 설치는 폴더를 통째로 아래 중 한 곳에 두면 된다 (복사든 링크든).

| 도구 | 사용자 레벨 | 프로젝트 레벨 |
|---|---|---|
| Claude Code | `~/.claude/skills/operator` | `.claude/skills/operator` |
| Codex CLI | `~/.codex/skills/operator` | `.agents/skills/operator` 또는 `.codex/skills/operator` |
| Cursor | `~/.cursor/skills/operator` | `.cursor/skills/operator` |
| Gemini CLI | `~/.gemini/skills/operator` | `.gemini/skills/operator` |
| 그 외 (Copilot, OpenCode 등) | 각 도구의 skills 디렉터리 | `.agents/skills/operator` (공용 규약) |

스킬을 읽지 못하는 도구에서는 `assets/hooks/AGENTS.md.snippet` 을 프로젝트 `AGENTS.md` 에 붙여 넣는다.
그러면 규칙은 지시로 전달되고, CLI(`scripts/op`)는 그대로 동작한다.

## 훅 (승인 게이트를 100% 로)

훅 없이도 스킬은 돈다. 하지만 그땐 "발송하지 마라"가 지시(확률)로 내려앉는다. 훅을 걸면 **물리적으로** 막힌다.
`install.sh --print-hooks` 가 경로를 채운 스니펫을 출력한다. 도구별 파일 위치는 거기 적혀 있다.
Cursor·Gemini 의 훅 이벤트 이름은 버전에 따라 다를 수 있으니 안 걸리면 각 도구의 공식 훅 문서로 필드 이름을 맞춘다.
(`op guard` 는 입력 JSON 에서 `tool_input.command` / `command` / `tool_input.file_path` / apply_patch 본문을 모두 읽는다.)

확인: 프로젝트에서 `op init` 한 뒤 에이전트에게 "git push 해" 라고 시켜 본다. 막히면서 "승인 큐에 올려라"는
메시지가 모델에게 돌아가야 한다.

## 사용 흐름 (사람 쪽)

```bash
op init                                   # 프로젝트 루트에서 한 번
# 에이전트: "operator 로 이 아이디어를 plan 해 줘" → .operator/business.md
# 에이전트: "pass 한 번 돌려" → 리서치 → 초안 → 검증 → .operator/pending/
op pending list                           # 승인 대기 보기
op pending show 0001
op pending approve 0001                   # 또는 reject 0001 --reason "..."
# 에이전트: "0001 보내" → op send 0001 -- <명령>  (승인된 티켓만 통과)
```

`op help` 로 전체 명령.

## Foundable 과 다른 점 (1인용이라 가능한 것)

- 돌아가는 건 사용자가 run 을 시킬 때뿐. 밤새 돌리려면 각 도구의 예약 실행으로 하루 한 번.
- 승인 UI 는 마크다운 파일 + 터미널 명령.
- 크레딧 대신 `--max-steps`.
- Temporal 대신 `state.json`, Modal 대신 검증 명령 exit code, 승인 큐 대신 폴더 네 개.

설계 근거 전체: [references/foundable-research.md](references/foundable-research.md)
