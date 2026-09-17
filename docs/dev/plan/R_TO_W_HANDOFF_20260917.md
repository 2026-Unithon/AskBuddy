# R → W 통합 인계 (2026-09-17)

원격 main `a20f2b6`(W 평가 캠페인·공통 화면 개선)을 pull한 뒤 누적 R 작업을 통합했다. W/R 개발 문서 충돌 2개는 양쪽 기록을 보존해 해결했다. 코드 자동 병합 후 전체 회귀·프론트 빌드·합성 브라우저 검증을 실행했다.

## 이번 R 전달 범위

- M2 불변 승인 snapshot 색인 준비/활성화 접점, lexical/vector/RRF, 승인 사전, 선택형 reranker.
- M3 v2 질문·문맥·참조 답변·원자 저장/인용·stale 재검색·요청 멱등성.
- 명시 조건/예외/수치 구간, 제한 RAW 수량/Q&A/절차 원문, 조건·규격별 의미 묶음.
- 점주 원문 revision·occurrence 전달·앱 내 알림·W outbox 인계·lease/fencing·10회/backoff/종료 실패·수동 재처리.
- v2 FAQ, 직원 채팅/알림 및 점주 질문 화면, 승인 지식 내보내기 권한/감사.
- R 단일/다회 질문 수집·pooling/oracle·RAW 근거·사람 판정 수입·반복 캠페인·묶음 평가 도구.

이 범위는 기반/제한 지원 구현이다. 자유로운 의미 판단 전체, 실자료 품질 승격, W 실제 발행 연결 또는 출시 완료가 아니다. `r_v2_enabled=false`, `r_reranker_enabled=false` 기본값을 유지했다.

## W가 먼저 확인할 연결점

| 순서 | 확인 사항 | 접점/책임 |
|---|---|---|
| 1 | migration 5개와 기존 스키마 재구축 | `20260917103000` question context, `110000` index staging, `120000` answer receipts, `130000` owner delivery, `140000` lexicons. 기존 migration을 고치지 않고 로컬 격리 DB에서 먼저 검증 |
| 2 | PrepareIndex → 발행 원자성 | `api/app/reg/index_preparation.py`: `prepare_index`, `activate_prepared_index`. 현재 공개 포인터와 발행 transaction은 W 소유. TTL/hash/revision/중복/역순/실패를 함께 인수 |
| 3 | OWNER_ANSWER → 지식 반영 | `api/app/learn/owner_handoff.py`: claim/heartbeat/finish. W 작업 중 DB 연결을 점유하지 않고 heartbeat 20초, lease 60초. W 발행과 finish는 같은 transaction; finish 실패 시 전체 rollback |
| 4 | 점주 답변의 결과 계약 | 원문 전달 성공과 지식화 PENDING/LINKED/REVIEW/PUBLISHED/FAILED는 별개. NEW/IDENTICAL 및 SUPPLEMENT/CONFLICT를 실제 W 처리와 연결. 종료 실패는 자동 반복하지 않음 |
| 5 | 발행 후 R 읽기 | 현재 승인 카드/version과 FAQ·로드맵·재질문 검색을 대조. 원문 전달만으로 FAQ나 승인 지식을 생성하지 않음 |
| 6 | 실제 승인 snapshot 제공 | dev 두 매장의 승인 snapshot과 실제 fact revision/RAW 매핑 필요. R 질문 truth/기대 행동/적용 범위는 별도 사람 검토 |

`POST /learn/v2/owner-events/{event_id}/retry`는 점주 권한으로 같은 업무 event를 재처리하며 이전 시도 수·사유·멱등 키를 기록한다. W worker는 내부 인계 함수를 사용하고 별도 중복 지식화기를 만들지 않는다.

R API 경로는 `/learn/v2/*`; 화면은 `/staff/chat/v2`, `/staff/notifications/v2`, `/owner/questions/v2`다. 기존 v1 세션과 응답 enum을 혼합하지 않는다.

## W 캠페인과 R 평가의 구분

이번 pull의 `W_EVAL_CAMPAIGN_V1.md` 사전등록·holdout 잠금 계약은 그대로 유지한다. R `v2_campaign.py`는 R 질문 결과/반복/paired gate를 위한 도구이며 W 캠페인 승인이나 holdout 개봉을 대신하지 않는다. 실제 공동 캠페인은 snapshot·질문 truth·설정·코드·예산을 함께 고정해야 한다.

R 실자료 검토 초안은 두 매장 각각 40개(서로 다른 질문 문구 37개), 검토 완료 0개다. 자료·원본·초안은 Git 제외 경로에 있으므로 이 push에 포함되지 않는다. 필요한 경우 기존 비공개 자료 전달 경로로 별도 공유한다. 초안을 승인 정답으로 사용하지 않는다.

## 이번 통합 검증

- API 전체 **751 passed / 119 subtests passed**. 기존 Starlette/AnyIO deprecation warning 1건.
- `web`의 `pnpm check` 통과: route typegen, lint, typecheck, production build.
- Edge 실제 브라우저 + 합성 API **27 checks 통과**: 복원, 명확화, 인용, 오류/재시도, 원문 전달, 정책 확인, 알림/읽음/이동, 모바일 폭. W의 새 `/app/bootstrap` 계약에 맞춰 합성 fixture를 추가했다.
- 최신 변경의 Docker DB/W 종단 검증은 이번에 실행하지 않았다. 과거 DB 성공 기록을 이번 통합 성공으로 재사용하지 않는다.

Docker 준비 후 저장소 루트에서 실행할 검증:

```powershell
powershell -File api/scripts/verify_r_handoff.ps1 -Python python -IncludeSchemaRebuild -IncludeUnitTests
```

실행 환경에는 프로젝트 Python 의존성이 필요하다. 스크립트는 localhost 전용 임시 컨테이너/DB를 만들고 `.env`나 운영 DB를 사용하지 않는다. 통과 후 실제 W producer→승인→색인→질문→인용과 점주 1명/직원 2명의 전달 루프를 공동 검증한다. 플래그 활성화·운영 배포는 이 커밋과 별도다.

세부 지원 범위/잔여: [R 구현 계획](R_IMPLEMENTATION_PLAN.md), [잔여 감사](../review/R_REMAINING_AUDIT_20260916.md), [최근 수치 조건 검증](../review/R_NUMERIC_SCOPE_AND_COVERAGE_20260916.md).
