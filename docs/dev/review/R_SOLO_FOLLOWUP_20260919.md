# R 단독 후속 구현·검토 — 2026-09-19

기준은 `39997bb` 이후다. 사람 정답 검토, 유료 평가, 실제 W 공동 인수는 대기 상태로 유지했다. 별도 W/release 미커밋 변경은 포함하지 않는다.

## 완료한 단독 구현

1. **통합 평가 예산:** QUERY/EMBED/RERANK를 명시한 `additional_calls`를 기존 ANSWER 정책에 추가했다. 모든 단계가 동일 campaign의 금액·호출 수를 DB에서 먼저 예약한다. HTTP 평가 scope는 공급자 호출 전에 EVALUATION/run에 매핑한다. 예산 미설정·대상 불일치·한도 초과는 공급자에 접근하지 않는다.
2. **공급자 제한:** 질문 임베딩은 고정 `text-embedding-3-small`에서 UTF-8 bytes를 토큰 수의 보수적 상한으로 검사한다. 다른 embedding 모델은 이 경로에서 거절한다. 재정렬과 의미 제안은 schema를 포함한 prompt의 count_tokens 검사 및 출력 토큰 제한을 공유한다. 응답 usage 결측/초과는 기존 캠페인 정지 계약을 따른다.
3. **오류 분리:** 재정렬은 BudgetDenied를 FAILED fallback으로 숨기지 않는다. v2 chat은 `429 EVALUATION_BUDGET_DENIED`, retryable=false를 반환하며 답변·pending을 저장하지 않는다. 같은 요청을 반복해도 예산 승인 없이 공급자를 다시 호출할 수 없다.
4. **사람 판정→검토 catalog 도구:** `build_r_reviewed_catalog.py`는 정확한 observation hash의 사람 판정과 별도 interpretation, 승인 근거를 입력받는다. 미검토·오답·과차단·병합/인용 오류·행동 불일치·후보/승인판 변경·RAW 누락을 거절하고 기존 제품 adapter로 재검증한다. 결과 파일은 배타 생성하며 hash만 출력한다. 자동 설치·플래그 변경은 없다.

## 예산의 의미와 사용

단계별로 싼 값을 추정하지 않는다. **허용된 모든 모델에 충분한 공통 입력/출력 단가 상한과 공통 최대 토큰 수**를 정책에 고정하고, 임베딩도 미사용 출력분까지 포함한 최대 비용을 예약한다. 실제 비용보다 많이 예약해 조기에 멈출 수 있지만 총한도 우회는 허용하지 않는다. 단계별 개별 한도·환불 최적화는 현재 구현하지 않았으며 필수 기능이 아니다. 단가/환율/부대비용 상한과 공급자의 토큰 제한 준수가 금액 보장의 전제다.

`additional_calls` 예시 형태는 `[{"stage":"QUERY","model":"text-embedding-3-small"},{"stage":"RERANK","model":"<승인 모델>"}]`다. 실제 모델·금액·승인자는 회의에서 정한다. 기존 `model`은 ANSWER 모델이며 추가 단계도 별도 승인이 필요하다. 확장 정책 hash가 달라지면 기존 캠페인에 덮어쓰지 못한다.

격리된 **동일 프로세스의 HTTP 평가 하네스**에서 `evaluation_usage_scope(store_id=..., evaluation_run_id=...)`와 `evaluation_budget_scope(EvaluationBudget(pool, approved_policy))`를 함께 사용한다. DB에는 RUNNING run이 있어야 한다. ContextVar는 외부 HTTP 요청으로 전달되지 않으므로 원격 서버에는 이 scope를 설치하는 별도 격리 실행 구성이 필요하다. 요청 헤더로 활성화하지 않는다. 기존 오프라인/합성 provider 주입은 유료 SDK를 실행하지 않는다.

이 통합 범위는 현재 R v2의 질문 임베딩·선택적 재정렬·의미 제안이다. W 등록/STT/추출, legacy 자유생성 평가, 저장소 비용 전체의 예산 관리라고 확대하지 않는다. 제품 렌더링에는 새로운 생성 호출이 없다.

임베딩 상한 근거: [OpenAI tiktoken BPE 구현](https://github.com/openai/tiktoken/blob/main/tiktoken/_educational.py)은 UTF-8 byte를 합치는 방식이다. 이를 기반으로 고정 모델 입력의 byte 수를 상한으로 사용하며 모델 변경 시 그대로 허용하지 않는다. 응답의 실제 usage와 예약 한도도 재대조한다.

## 검토 catalog 입력

`python scripts/build_r_reviewed_catalog.py --input <매장 내부 검토 bundle.json> --output <매장 내부 새 catalog.json>`

bundle에는 `acceptance_reference`와 `items`가 필요하다. 각 item은 다음을 포함한다.

- `search`: snapshot, index_revision, candidates. 모델에 실제 제공된 후보 순서까지 일치해야 한다.
- `observation`: semantic shadow의 원본 row 및 row_hash.
- `judgment`: 해당 row_hash의 reviewer/reason/expected_action/semantic_correct/false_block/false_merge/citation_error.
- `interpretation`: 별도로 사람이 확인한 entity/predicate/variant/필수 fact/조건/예외/RAW 적용성. 모델의 구조 유효성만으로 만들지 않는다.
- `approval_id`, `confirmed_slots`: 검토한 정확한 입력의 승인 ID와 확정 슬롯.

비교 질문을 추가한 observation은 제품 입력과 hash가 다르므로 그대로 채택하지 않는다. 실제 catalog에는 검토된 제품 입력을 사용한다. offline 문맥 검증은 세션 권한을 발급하지 않으며 실행 시 기존 세션/문맥 검사를 다시 통과해야 한다. 합성 catalog 테스트가 실제 사람 판정을 대신하지 않는다.

## 검증 및 남은 작업

단위 검증은 scope 매핑·미설정 차단·공급자 전 예약·입력 상한·재정렬 오류 전파와 catalog 반례를 포함한다. DB verifier는 실제 세 adapter와 usage 원장·예약을 연결하고 SDK 응답만 합성 대체한다. 세 호출이 한 계정을 공유하고 네 번째 호출이 SDK 이전에 차단되는 것을 확인한다. 기존 usage 전용 테스트의 budget mock과 이 통합 검증을 구분한다.

실제 자유 표현의 일반화 경로를 무검토 제품 답변으로 확장한 것은 아니다. 기존 모델 제안/shadow와 검토 catalog 연결은 준비됐으며, 일반화 제품 설계 범위·품질 기준, 사람 정답·실제 승인 snapshot·유료 평가, W 공동 종단·운영 설정 증거는 남아 있다. RD-01/02를 자동 재개하지 않았다.

로컬 검증: 전체 814 passed/4 xfailed/119 subtests 이후 CLI 배타 생성 검사를 추가해 해당 13 tests 통과. schema 15개·fixture 3개 최신. PG17 migration 29개(별도 W 미커밋 migration 포함) 전체 회귀와 v2 API 114 checks 통과. 검토 중 발견한 예산 거절의 MODEL_UNAVAILABLE 변환을 수정했고, 최종 DB에서 429/nonretryable 및 답변·pending 미생성을 확인했다. 순수 R 커밋의 최종 수치는 원격 CI를 따른다.
