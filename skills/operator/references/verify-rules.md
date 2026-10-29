# 검증 게이트 규칙

Foundable 은 사이트만 "테스트 통과 후 저장"했다. 이 스킬은 **모든 산출물**에 같은 원칙을 적용한다.
검증은 `op pending add` 때 자동으로 돌고, 실패하면 pending 에도 올라가지 않는다. 따라서 사람이 보는
건 전부 최소 기준을 넘은 것이다. 미리 보려면 `op verify <file> --type ...`.

## 공통 (모든 타입)

| 검사 | 기본값 | config.json 키 |
|---|---|---|
| placeholder 없음 | `\[TODO[^\]]*\]`, `\bTODO\b`, `\bTBD\b`, `\{\{`, `lorem ipsum`, `\bXXX\b`, `<여기에`, `\[\[.*?\]\]`, `\[링크\]`, `\[이름\]` | `verify.placeholders` (정규식 목록. 정규식이 아니면 리터럴로 취급) |
| 금지어 없음 | 없음 | `verify.banned_words` (plan 단계에서 채움) |
| 필수어 포함 | 없음 | `verify.required_words` (예: 브랜드명) — 비어 있으면 검사 생략 |

## post

- 길이: 본문(front matter 제외) 글자 수가 `min_len`(20) 이상, 채널별 `max_len` 이하.
- 채널은 `--channel` 또는 front matter `channel:`. 모르면 `default`(3000).
- 기본 `max_len`: x 280 · threads 500 · instagram 2200 · linkedin 3000.

## email

- front matter 에 `to:`, `subject:` 가 있어야 한다 (`verify.email.require`).
- 본문 40~4000자.

## research

- 본문에 서로 다른 URL 이 `min_sources`(3) 개 이상. `https?://` 로 시작하는 걸 센다.
- 본문 200자 이상.
- 권장 구조: `## 요약` / `## 근거` / `## 출처`. (구조는 검사하지 않지만 사람이 읽기 쉽다.)

## site

- `verify.site.command` 를 프로젝트 루트에서 실행해 exit 0 이어야 한다. 예: `npm run build`, `npm test && npm run build`.
- 비어 있으면 **실패**다. 빌드 명령 없이 "사이트 변경을 검증했다"고 할 수 없기 때문이다. 사용자에게 물어서 채워라.
- 타임아웃 `verify.site.timeout` (600초).

## other

- 10자 이상이면 통과. 타입을 모를 때만 써라.

## 규칙을 바꾸고 싶을 때

에이전트는 검증을 통과시키려고 `config.json` 을 고치지 않는다. 기준이 틀렸다고 판단되면 사용자에게
"x 는 280자인데 이 초안은 310자다. 줄일까, 아니면 기준을 바꿀까?" 라고 묻는다. 기준 변경은 사용자가 한다.
