# R 계획 적합성 재검토 — 2026-09-15

판정: 현재 계측·유입 제한·지표 준비 범위의 회귀/격리 DB 인수는 통과했다. 전체 C0/R 구현 완료 또는 운영 승격 판정은 아니다. 기준은 C0_DECISIONS_AND_PLAN §4/§6, C0_COST_MEASUREMENT_PLAN §7, ASKBUDDY_MVP_CURRENT §20 및 이관경계_실험설계 §6이다.

## 이번에 확인하고 수정한 결함

| 결함 | 계획과의 차이 | 수정 및 검증 |
|---|---|---|
| 임베딩 client.close 실패가 응답/원래 공급자 오류를 덮음 | 수신 usage를 보존해야 하는 원가 규약 위반 | 정리 오류는 예외 종류만 기록. 정상 응답의 토큰/결과 보존 및 원래 timeout 보존 테스트 추가 |
| 채팅 처리 완료 후 lease 정리 중 deadline 도달 시 504 반환 | 이미 저장된 작업 상태를 retryable 실패로 왜곡 | 하나의 absolute deadline 사용. 처리 함수가 정상 반환한 뒤 정리 중 timeout이면 완료 응답 보존. 저장 전 timeout은 계속 504 |
| 모든 CLARIFY/ESCALATE를 block_precision 분모에 포함 | 계획은 지식·근거 충분성 때문에 차단한 질문만 포함 | 평가 입력 knowledge_block=True만 포함, False는 제외. 이유 미분류는 unclassified_block_count로 보고하고 precision=null. 실제 v2 수집기는 이 사람 판정 필드를 연결해야 함 |

앞의 두 결함에 대한 회귀 테스트 3개는 수정 전 실제 실패했고 수정 후 통과했다. 지표는 계획의 분모와 코드를 대조하고 이유 제외/미분류 회귀를 추가했다. block_count는 이유가 확인된 지식 차단 수이며 미분류는 별도 수다.

## 아직 충족하지 못한 계획 항목

- **P1: stale 처리** — learn/router.py의 use_hit 검사에서 현재 인용이 아니면 기존 NO_ANSWER/pending 경로로 진행한다. 결정서의 deadline 내 최대 1회 재검색, 계속 경합 시 STALE_KNOWLEDGE 오류 및 pending 금지와 다르다. 공개 잠금/CAS·멱등 저장을 포함한 M2/M3/R4 후속 구현과 경합 DB 인수가 필요하다. 이번 정리 timeout 수정이 이 문제를 해결하지는 않는다.
- **M2/M3·R1~R5** — 공개 snapshot staging/소비, 실제 질문 적합성 판정, v2 세션·인용·재질문 및 제품 루프 전체는 미완료다. 합성 fixture와 지표 산술 통과는 실제 의미 검증 완료가 아니다. R 자체 몫을 전부 W 의존 작업으로 제외하면 계획과 달라진다.
- **시간 예산의 실측** — 요청에 timeout을 연결했지만 실제 부하에서 p95 5초를 입증하지 않았다. 동기 임베딩 스레드는 coroutine 취소만으로 즉시 중단되지 않으며 관측하지 못한 비용은 UNKNOWN이다. SDK transport 제한은 전체 실행 시간의 실측 증명이 아니다.
- **CP-00C 전체 비용** — 읽기 QUERY/ANSWER 집계는 검증했으나 W의 등록/추가자료/STT/Storage 비용, 배치 기여 링크 및 실관측 요율/환율을 합친 인수는 별도다. 누락 비용을 0으로 놓고 D21 통과로 처리할 수 없다.

## 이번 검증 근거와 한계

- 전체 Python 회귀: **359 passed / 73 subtests passed**, 기존 Starlette/AnyIO 사용 중단 예정 경고 1개.
- PostgreSQL **15.19**, 일회용 localhost 컨테이너: 원장 14, 요청 제한/격리 9, W 임베딩/읽기 집계 6 — **29/29**. runner 종료 및 생성 컨테이너 제거 확인.
- 검증 명령: api/scripts/verify_r_handoff.ps1 -Python <설치된 Python 절대경로> -IncludeUnitTests. 의존성을 사용할 수 있는 PYTHONPATH가 필요하다.
- DB 검증은 최소 의존 테이블 fixture와 해당 migration을 사용한다. 전체 업무 migration 재구축·publication/chat 종단·실제 모델 품질/청구·운영 DB 배포는 검증하지 않았다.
- 이번 수정의 채팅 deadline 회귀는 처리 함수 완료와 후처리 취소의 경계를 검증한다. 실제 DB commit 중 취소/불명확한 결과의 멱등 복구를 입증하지 않는다.

W는 C0_W_START_HANDOFF.md의 CP-00B/C 계측 접점 구현을 시작할 수 있다. R은 위 미완료 항목을 자체 후속 작업으로 유지해야 하며 전체 C0 인수·공개 승격을 병렬 착수 가능 여부와 혼동하지 않는다.
