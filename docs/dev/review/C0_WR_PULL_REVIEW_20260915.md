# W 변경 pull 후 R 호환성 검토

2026-09-15. origin/main을 691fe5e에서 e43c0009482abd0e3919dacff1293f6c1a4b922b까지 fast-forward pull했다. 신규 W 변경은 70b6317의 W0 평가 하네스 개선이며 로컬 R 수정 파일과 겹치지 않았다. 기존 미커밋 R 변경은 유지했다. 이번에는 구현 코드를 추가 수정하지 않고 호환성과 문제를 검증했다.

**판정: R 계측 접점의 기존 인수는 통과하지만 W 기대 전체 충족은 아니다. 평가 규칙 불일치, 실제 W 임베딩 연결 미완료 및 새 W 코드 결함이 남아 있다.**

## 사용자 결정 — 현재 변경 공유 후 W·R 공동 확인

현재 검증된 변경사항을 먼저 커밋·push해 공유한다. 아래 판정 규칙 불일치와 채점/CLI 결함, 실제 임베딩 연결 항목은 W·R 양쪽에서 확인한 뒤 변경한다. 공유 자체를 정책 합의나 전체 인수 완료로 간주하지 않으며, 어느 한쪽 규칙으로 임의 통일하지 않는다. 합의 후 계획 문서·구현·회귀 테스트를 함께 갱신한다.

## 중요 발견

### P1 — W 반복 판정과 R/계획의 규칙이 다르다

- W `scripts/compare_runs.py:187`은 사실별 반복 만장일치만 개선/악화로 센다. 커밋 설명은 사용자 결정이라고 기록하지만 해당 변경에 계획 문서 수정은 포함되어 있지 않다.
- R `app/team/answer_metrics.py:67`과 결정서 §10, 실험설계 §9는 반복별 Δ_i 중앙값과 2/3 양의 방향을 사용한다. W의 abs(만장일치 순증) 기반 잡음 바닥도 계획의 별도 A/A 성공 개수 max−min과 다르다.
- 재현: 동일 질문 10개, 기준군은 모두 실패, 비교군의 성공 ID를 3회 각각 0~4 / 3~7 / 5~9로 둔다. R은 Δ=[5,5,5]로 다른 게이트를 만족하면 eligible=True다. W식 3회 모두 성공한 ID는 0개다.
- 이 차이는 단순 함수 호환 문제보다 정책/문서 불일치다. 현재 문서에 비추면 R 산술은 맞다. W의 변경 규칙을 공통으로 채택하려면 적용 범위(사실/질문)와 잡음·안전·비용 게이트를 문서 및 양쪽 구현에 함께 반영해야 한다. 한쪽 판정 결과를 다른 쪽의 승격 근거로 재사용하면 안 된다. R eligible도 운영 승격 자체는 아니다.

### P1 — 새 W 출력 채점기가 오답을 MATCHED로 분류한다

`app/team/extraction.py:399`은 속성 일치를 확인하기 전에 값 토큰 일부와 규격만으로 MATCHED를 반환한다. 따라서 정답의 subject=material, attribute=lifetime, value="14 days", variant=null에 대해 아래 두 입력 모두 실제 MATCHED로 재현됐다.

1. attribute=order_cycle, value="14 days": 다른 속성이므로 정답 확인 근거가 없다.
2. attribute=lifetime, value="90 days": days 토큰만 겹치는데 숫자가 다르다.

이 결과를 precision_lower에 포함하므로 하한조차 신뢰할 수 없다. W의 출력 쪽 채점 보강 의도는 타당하지만, 현재 자동 MATCHED를 사람이 확정한 정확도나 R 의미 판정의 truth로 소비해서는 안 된다. 속성 및 값 의미 일치가 확인되지 않은 경우에는 판정 유보가 필요하다.

### P2 — 비교 스크립트 --detail이 종료되지 않는다

`scripts/compare_runs.py:293`의 `unstable`은 정의되지 않았다. 이번 변경에서 사용하는 변수는 `wobbly`다. 양쪽 3개 실행과 정답 1개를 합성한 CLI 호출에서 `NameError: name 'unstable' is not defined`를 재현했다. .env 로드 및 DB 접속은 mock으로 막았으며 실제 DB나 유료 호출은 사용하지 않았다.

### 연결 미완료 — W 카드 임베딩에 R 계측이 아직 주입되지 않았다

`app/ingest/embed/service.py::embed_card`는 여전히 connection을 받은 상태에서 `to_thread(embed_texts, ...)`를 직접 호출한다. `recorded_embeddings`/UsageContext/DbUsageSink 연결은 없다. 이번 pull은 이 파일을 변경하지 않았다.

R은 기존 embed_texts 호출 형태와 단일 공급자 진입점, 등록 30초/질문 0.8초 transport 구분을 유지하므로 기존 W 호출을 깨지는 않는다. 그러나 실제 W 등록 임베딩 비용이 원장에 기록된다고 판정할 수 없다. W_START_HANDOFF의 연결 수명 분리 → trusted context 주입 → 배치 기여 링크 → 전체 원가 대조 순서는 그대로 남는다.

## 기대에 맞는 부분

- W가 수정한 재추출 실행 범위와 마찬가지로 R 평가는 `eval:{run_id}:case:{case_id}:answer/query`, 채팅은 새 operation UUID를 사용한다. run을 달리한 재평가가 자료 ID 하나로 충돌하는 기존 W 문제와 구조가 다르다. 실제 시도 번호와 중복 원장 보호는 유지된다.
- R의 공통 원장은 STARTED 선저장, usage의 0/null 구분, 실패 호출 비용 보존, store별 격리와 완료 receipt 동결을 유지한다. 실패한 실행/미확정 비용을 정상 관측이나 0원으로 둔갑시키지 않는 W의 의도와 일치한다.
- W의 PARTIAL extraction_runs 상태와 R의 QUESTION/ANSWER usage 상태는 다른 축이다. R 읽기 집계를 W 추출 성공률·전체 원가 완료로 간주하지 않는다. W 새 상태 migration의 적용 인수는 아래 R DB suite에 포함되지 않는다.

## 검증

- pull 이후 전체 회귀 **374 passed / 73 subtests passed**, 기존 경고 1개. W가 추가한 테스트 15개가 포함됐다.
- PostgreSQL **15.19** R DB suite **29/29**: 원장 14, 제한/격리 9, W 합성 임베딩 접점/읽기 집계 6. 컨테이너 제거 확인.
- 추가 합성 probe에서 채점 오판 2개, --detail NameError, W/R 판정 차이를 확인했다. 따라서 기존 테스트 통과만으로 신규 W 코드의 정확성을 보증하지 않는다.
- 운영 DB 변경, 실제 고객/모델 호출, 새 W PARTIAL migration 실제 DB 인수, 전체 migration 재구축 및 실제 W ingest → R 검색/답변 종단은 수행하지 않았다.
- 이전 검토의 stale→pending 경로 및 M2/M3·R1~R5 미완료 사항도 해소되지 않았다.

다음 공동 정리 우선순위는 판정 규칙의 문서 일치, W 채점/CLI 결함 수정, W 실제 임베딩 계측 연결이다. R은 자체 M2/M3·stale 처리 후속을 유지하며, 이번 pull을 전체 WR 완료로 취급하지 않는다.
