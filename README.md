# operator

**적게 하지만 절대 안 어기는 운영 루프.** AI 에이전트에게 사업·프로젝트 운영(리서치 → 초안 → 발송·게시·배포)을
맡기되, 밖으로 나가는 건 100% 사람 손을 거치고, 끊겨도 처음부터 하지 않게 만드는 스킬이다.

"AI 직원" 서비스가 Temporal·Modal·승인 큐 같은 인프라로 강제하는 네 가지를
python3 스크립트 하나와 JSON 파일로 옮겼다. Foundable(foundable.com)의 공개된 운영 방식에서 착안한
독립 구현이며, 해당 회사와는 무관하다. 기존 "AI 직원" 플러그인들이 지시문으로만 "확인받아라"고 적는 자리를
**물리적 차단**으로 바꾼 것이 차이다.

| 강제 장치 | 구현 | 효과 |
|---|---|---|
| 승인 게이트 | `op guard` (PreToolUse 훅) | 발송·게시·배포·결제·삭제 명령 차단 → `pending/` 큐. 승인은 사람 터미널에서만 |
| 재개 | `op pass` + `state.json` | 단계마다 체크포인트. 세션이 끊겨도 멈춘 단계부터 |
| 검증 게이트 | `op verify` | 포스트·이메일·리서치·사이트 전부 검사. 실패하면 큐에도 안 올라감 |
| 모델 라우팅 | `op llm` | 분류·요약은 로컬 모델, 판단·초안은 에이전트 |

[Agent Skills 표준](https://agentskills.io) 형식이라 Claude Code, Codex CLI, Cursor, Gemini CLI 등에서 같은 폴더를 그대로 쓴다.

## 설치

**Claude Code (플러그인, 훅 자동 연결)**

```
/plugin marketplace add pullyo/operator-skill
/plugin install operator@operator-skill
```

**Agent Skills 표준 (Codex, Cursor, Gemini CLI, Copilot 등)**

```bash
npx skills add pullyo/operator-skill
```

**수동 (여러 도구에 한 번에)**

```bash
git clone https://github.com/pullyo/operator-skill
sh operator-skill/skills/operator/install.sh                 # ~/.claude, ~/.codex, ~/.cursor, ~/.gemini 중 있는 곳에 링크
sh operator-skill/skills/operator/install.sh --print-hooks   # 도구별 훅 설정 스니펫
```

훅 없이도 스킬은 동작하지만 그땐 차단이 "지시" 수준이다. 훅을 걸면 물리적으로 막힌다.
도구별 훅 파일 위치와 형식은 [skills/operator/README.md](skills/operator/README.md) 에 있다.

## 사용

```bash
cd <운영할 프로젝트>
op init                      # .operator/ 생성. 이 폴더가 있는 프로젝트에서만 가드가 작동한다
# 에이전트에게: "operator 로 이 아이디어를 plan 해 줘"  → .operator/business.md
# 에이전트에게: "pass 한 번 돌려"                       → 리서치 → 초안 → 검증 → 승인 대기
op pending list              # 사람: 승인 대기 확인
op pending approve 0001      # 사람: 승인, 대화형 터미널에서만 (에이전트는 실행할 수 없다)
# 에이전트에게: "0001 보내"                              → op send 0001  (티켓에 승인된 action 만 실행)
```

`op` 는 `skills/operator/scripts/op` 다. PATH 에 넣거나 전체 경로로 쓴다.

## 구조

```
operator-skill/
├── .claude-plugin/   plugin.json, marketplace.json   ← Claude Code 플러그인
├── .codex-plugin/    plugin.json                     ← Codex 플러그인 메타
├── hooks/hooks.json                                  ← Claude Code 플러그인 훅 (승인 게이트)
└── skills/operator/                                  ← 스킬 본체 (Agent Skills 표준)
    ├── SKILL.md · scripts/op.py · references/ · assets/ · evals/ · install.sh
```

설계 근거(참고 서비스의 공개 자료 분석)는 [skills/operator/references/foundable-research.md](skills/operator/references/foundable-research.md).

## 테스트

```bash
python3 -m unittest discover -s tests
```

`tests/test_guard.py` 는 Claude Code·Codex 가 보내는 것과 같은 훅 JSON 을 실제 `op.py guard` 프로세스에 넣어, 세션 폴더·`cd`·`git -C`·파일 경로로 operator 프로젝트를 찾아 막는지 확인한다.

## 라이선스

MIT
