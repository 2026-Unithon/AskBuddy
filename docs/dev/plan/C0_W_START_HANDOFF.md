# W 착수 인계 — R 측 계측 접점

2026-09-15 후속: [W 교정 검증](../review/W_MEASUREMENT_FIXES_20260915.md).
W 승인/수정/OWNER_ANSWER 경로에 `prepare_embedding` → 짧은 DB 저장을 연결했다.
원본 카드의 phase/purpose는 서버 원장의 EXTRACT/ASSEMBLE 귀속을 이어받으며,
귀속 기록이 없는 원본 카드는 추정하지 않고 보류한다. 초기 승인 여부로 등록을 추정하지 않는다.
`verify_r_handoff.ps1`에는 W 연결/CAS 6개와 판정 migration 4개 검증도 추가했다.

> 최신 원격 합류 검토: [C0_WR_PULL_REVIEW_20260915.md](../review/C0_WR_PULL_REVIEW_20260915.md). e43c000 pull 후 374 tests / 73 subtests 및 R DB 29/29 통과. W/R 판정 규칙 차이와 W 코드 결함·실제 adapter 미연결은 별도로 남아 있다. 아래 359개 기록은 pull 이전 인수다.

2026-09-15. 범위는 CP-00B/C의 W 등록/추가자료 계측 착수다. R 전체 완료나 W 공개·품질 승격 허가를 뜻하지 않는다. 이 문서에 나오는 API와 검증 파일을 포함한 **동일 변경 묶음**을 사용하는 checkout이 기준이다.

검증 결과: PostgreSQL 15.19 실제 DB 29/29, 전체 회귀 359 tests / 73 subtests 통과. 검증 범위와 소스 해시는 [C0_W_HANDOFF_VALIDATION.json](../review/C0_W_HANDOFF_VALIDATION.json)에 기록했다.

## 준비한 산출물

| 접점 | 실제 사용할 것 | 책임 |
|---|---|---|
| 임베딩 공급자 | `app.reg.embeddings.embed_texts` | 공급자 호출은 여기 한 곳만 유지 |
| 비동기 계측 호출 | `app.reg.embeddings.recorded_embeddings(texts, context=..., sink=...)` | STARTED 선저장, 단일 배치 1 receipt, usage 보존, 기존 vector 배열 반환 |
| 귀속/저장 | `UsageContext`, `DbUsageSink(pool)` | W가 trusted store·phase·purpose·job/source/campaign·logical call/attempt를 부여 |
| 합성 인계 입력 | `api/tests/fixtures/w_embedding_handoff.json` | 임의 고객 정보가 없는 등록 EMBED 예시와 기대 결과 |
| 실제 DB 인수 | `api/scripts/verify_r_handoff.ps1` | PG15 일회용 DB 생성 → 3개 검증 → 선택적 전체 회귀 → 정리 |
| 운영 원가 소비 | `app.team.operating_cost.operating_scenarios` | W 추가자료·Storage/전송 비용 입력을 R 읽기 단가와 합쳐 가정 계산 |

등록 EMBED의 transport timeout은 `embedding_timeout_seconds`(기본 30초), 직원 검색 QUERY는 `query_embedding_timeout_seconds`(기본 0.8초)다. 짧은 검색 예산을 W의 등록 배치에 적용하지 않는다. PrepareIndex 전체 30초 제한·재시도 조정은 향후 W/R 발행 준비 서비스에서 별도로 책임진다. transport timeout이 곧 전체 준비 서비스 deadline은 아니다.

## W의 첫 구현 순서

1. `ingest/embed/service.py` 등의 장시간 작업을 감싸고 있던 connection 범위를 줄인다. 필요한 승인 내용/버전을 짧게 읽고 반환한 뒤 임베딩한다. 저장 직전에 다시 획득해 버전·내용 hash와 승인 상태를 재검사한다. 현재 `embed_card(conn, ...)`에 인자만 추가하면 외부 호출 동안 connection이 남으므로 그대로 계측 완료로 처리하지 않는다.
2. 아래처럼 기존 R adapter에 trusted context를 전달한다. 초기 등록은 REGISTRATION, 운영 중 추가자료는 OPERATING이다. 개발/평가 호출을 PRODUCT로 표시하지 않는다. W의 pipeline/job에서 이 값을 결정하고 모델이나 브라우저 입력으로 받지 않는다.
3. 같은 실제 공급자 시도는 같은 `(store_id, logical_call_id, attempt_no)`다. 재시도는 다음 attempt_no를 쓴다. 여러 source/card를 한 번에 처리해도 receipt는 하나다. 배치 기여 링크는 이 식별자로 원장을 찾아 W 링크 테이블/서비스에서 연결한다. 카드마다 비용 receipt를 복제하지 않는다.
4. W extract/STT/Storage·추가자료 비용과 R QUERY/ANSWER의 원가를 대조한다. 포함 관계가 미확정인 추가 과금 항목, 요율/환율, Storage 관측 누락이 있으면 전체 CP-00C/D21은 미정으로 남긴다.

```python
from app.contracts.usage import UsageContext
from app.reg.embeddings import recorded_embeddings
from app.usage import DbUsageSink

# 이 지점에 들어오기 전에 호출부가 빌린 DB connection을 반환해야 한다.
vectors = await recorded_embeddings(
    approved_texts,
    context=UsageContext(
        store_id=str(trusted_store_id),
        cost_phase="REGISTRATION",  # 운영 추가자료이면 OPERATING
        cost_purpose="PRODUCT",    # 개발 fixture이면 DEVELOPMENT
        stage="EMBED",
        logical_call_id=logical_call_id,
        attempt_no=attempt_no,
        registration_campaign_id=campaign_id,
    ),
    sink=DbUsageSink(pool),
)
```

시작 기록 저장에 실패하면 공급자를 호출하지 않는다. 응답 파싱/차원 검증에 실패해도 받은 usage는 남는다. 확정 저장 오류는 모델 재호출로 복구하지 않는다. 재시도해도 저장되지 않으면 STARTED/UNKNOWN이며 완전 비용 합계로 쓸 수 없다. 반환값이 vectors라는 사실만으로 비용 기록까지 모두 확정됐다고 판정하지 않는다.

## 동일 검증을 실행하는 방법

Docker 엔진, 공식 `postgres:15-alpine` 이미지, API 의존성을 설치한 Python을 준비한다. 저장소 루트 PowerShell에서:

```powershell
docker pull postgres:15-alpine
& .\api\scripts\verify_r_handoff.ps1 -Python .\api\.venv\Scripts\python.exe -IncludeUnitTests
```

Python 경로는 절대 경로 사용을 권장한다. 스크립트는 API 디렉터리로 이동하므로 상대 경로 대신 다음처럼 해석한 경로를 전달한다:

```powershell
$apiPython = (Resolve-Path .\api\.venv\Scripts\python.exe).Path
& .\api\scripts\verify_r_handoff.ps1 -Python $apiPython -IncludeUnitTests
```

검증 DSN은 `127.0.0.1:55439/usage_verify`로 고정하며 `.env`의 운영 DB를 쓰지 않는다. 포트를 다른 프로세스가 사용하면 새 DB 시작이 실패한다. 기존 컨테이너를 임의로 제거하지 않고, 이번 실행에서 생성한 무작위 이름의 컨테이너만 정리한다.

DB 검증은 MC0 원장·요청 제한 migration과 실제 R 저장 함수를 다룬다. 기존 업무 테이블은 필요한 최소 fixture이며 전체 pgvector/publication/chat schema 재구축 인수는 아니다. 모델·임베딩 응답은 fake이므로 외부 유료 호출은 없다.

## 아직 합류가 필요한 경계

- `PrepareIndex` 토큰/TTL/hash를 W 발행 트랜잭션에서 실제 소비하는 경로와 M2 versioned staging은 별도다. 현재 R 계측 준비를 공개 준비 완료로 해석하지 않는다.
- W snapshot의 규격 적용 범위·조건·예외 판정 계약과 R3 의미 판정, M3 chat v2·M4 이관·OWNER_ANSWER 왕복은 후속 계획을 따른다.
- W가 이 변경 묶음을 받기 전 다른 checkout에서 예전 adapter를 호출하면 위 검증 결과가 적용되지 않는다. 커밋·푸시는 별도 실행 이력이며 이 문서가 전달 완료를 뜻하지 않는다.
