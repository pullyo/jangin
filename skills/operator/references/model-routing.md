# 모델 라우팅

참고 서비스(Foundable)는 TypeSafe AI 로 답변마다 reasoning 양을 정하고, 코드·자율 실행은 Claude, 일반 대화·임베딩은
OpenAI 로 나눴다. 1인 개발자에게 같은 효과를 내는 가장 싼 방법은 **역할로 자른다**:

| 역할 | 어디서 | 이유 |
|---|---|---|
| classify, summarize, tag, extract | 로컬 모델 (맥미니 Ollama / LM Studio 의 OpenAI 호환 API) | 정답이 좁고 틀려도 싸게 다시 함. 매일 도는 루틴이면 비용 차이가 난다 |
| draft, judge, code, plan | 지금 이 에이전트 (Claude / Codex / ...) | 톤·판단·코드는 품질이 곧 결과 |

`op llm --role <role> "프롬프트"` 는:
- role 이 `routing.local_roles` 에 있고 로컬 엔드포인트가 응답하면 → `ROUTE=local:<model>` + 결과 출력.
- 아니면 → `ROUTE=self` 와 exit 3. **에이전트가 직접 한다.** 로컬 모델이 없어도 아무것도 깨지지 않는다.

설정 (`.operator/config.json`):

```json
"routing": {
  "local_endpoint": "http://localhost:11434/v1",
  "local_model": "qwen2.5:7b",
  "local_roles": ["classify", "summarize", "tag", "extract"],
  "timeout": 120
}
```

쓰는 자리 예:
- research 단계에서 긁어온 긴 원문 → `op llm --role summarize --input raw.md "핵심 5줄"`
- 인박스/댓글 분류 → `op llm --role classify "다음 메시지가 문의/스팸/리드 중 뭔지 한 단어로: ..."`

로컬 결과를 그대로 밖에 내보내지 않는다. 로컬은 재료를 만들고, 초안은 네가 쓴다. 그래야 검증 게이트와 승인 큐의
의미가 유지된다.
