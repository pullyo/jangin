# pass 흐름 상세

한 pass 는 Ted 의 한 "턴"이다. 밤새 여러 pass 가 돌 수 있지만, 이 스킬에선 사용자가 `run` 을 시킬 때
한 pass 가 돈다 (예약 실행을 걸면 하루 한 번).

## 상태 파일 `.operator/state.json`

```json
{
  "pass_id": "2026-10-29-01",
  "goal": "이번 주 런칭 포스트 3개",
  "status": "running",
  "max_steps": 6,
  "step_count": 2,
  "steps": [
    {"name": "research", "status": "done",    "output": ".operator/research/2026-10-29-market.md"},
    {"name": "draft",    "status": "done",    "output": ".operator/drafts/post-launch-1.md"},
    {"name": "queue",    "status": "pending", "output": null},
    {"name": "report",   "status": "pending", "output": null}
  ],
  "log": [...]
}
```

- `op pass next` 는 첫 번째 `status != done` 단계를 돌려준다. 그게 재개 지점이다.
- `op pass done` 은 `step_count` 를 올린다. `max_steps` 에 닿으면 exit 4 → `op pass end`.
- `op pass fail` 은 단계를 `failed` 로 두고 `log` 에 이유를 남긴다. 다음 `next` 는 같은 단계를 돌려준다.
- `op pass end` 는 상태를 `passes/<id>.json` 과 `passes/<id>.md` 로 옮기고 `state.json` 을 지운다.

## 단계를 바꾸고 싶을 때

`op pass start --steps research,draft,queue,report` 처럼 직접 지정하거나 `config.json` `pass.steps` 를 바꾼다.
예: 사이트 개선 pass 는 `--steps audit,patch,build,queue`. 단계 이름은 자유지만 `queue` 단계가 없으면
아무것도 승인 큐에 올라가지 않는다 — 즉 아무것도 밖으로 못 나간다. 의도한 게 아니면 넣어라.

## 예시 세션 (Claude Code / Codex 어디서든 같다)

```
사용자: 이번 주 런칭 포스트 돌려줘

에이전트:
$ op status
  business.md: 있음 / 진행 중인 pass 없음 / pending: 0
$ op pass start --goal "런칭 포스트 x·threads 각 1개" --max-steps 6
$ op pass next            → research
  (웹 검색으로 경쟁사 런칭 포스트 톤 조사 → .operator/research/2026-10-29-launch-tone.md, 출처 4개)
$ op pass done research --output .operator/research/2026-10-29-launch-tone.md
$ op pass next            → draft
  (business.md 의 톤·CTA 로 초안 2개 작성)
$ op pass done draft --output .operator/drafts/post-launch-x.md
$ op pass next            → queue
$ op pending add .operator/drafts/post-launch-x.md --type post --channel x --action "curl -X POST https://api.x.com/2/tweets ..."
  검증 (post): PASS → 0001
$ op pending add .operator/drafts/post-launch-threads.md --type post --channel threads
  검증 (post): FAIL  [FAIL] placeholder 없음: \[링크\]
  (초안 고침 → 다시 add → PASS → 0002)
$ op pass done queue
$ op pass end

에이전트 → 사용자:
  pass 2026-10-29-01 끝. 승인 대기 2건 (0001 x, 0002 threads).
  터미널에서 `op pending show 0001` 로 보고 `op pending approve 0001` 하면 보낼게요.
  다음 pass 제안: 승인된 포스트 반응 보고 답글 초안.

사용자 (자기 터미널): op pending approve 0001
사용자: 0001 보내

에이전트:
$ op send 0001 -- curl -X POST https://api.x.com/2/tweets -H "Authorization: Bearer $X_TOKEN" -d @.operator/approved/0001-post-....md
  exit 0 → sent
```

## 세션이 끊긴 뒤

새 세션의 첫 `op status` 가 "진행 중인 pass: ... 다음 단계: draft" 라고 하면, 사용자가 다른 걸 시켜도
먼저 "지난 pass 가 draft 단계에서 멈춰 있어요. 이어서 끝낼까요, 아니면 `op pass end` 로 닫을까요?" 라고 묻는다.
처음부터 다시 리서치하지 않는다. 그게 Temporal 을 흉내 내는 이유다.
