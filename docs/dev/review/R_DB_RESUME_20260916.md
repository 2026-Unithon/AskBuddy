# R Docker 재개 검증 — 2026-09-16

기존 작업의 DB 장애를 해소하고 검증을 재개했다. R 전체 완료나 운영 배포 기록은 아니다.

## 최종 결과

| 검증 | 결과 |
|---|---|
| 원가 원장 실제 DB | 14/14 |
| 요청 제한·매장 격리 실제 DB | 9/9 |
| W 임베딩 계측·R 읽기 집계 실제 DB | 6/6 |
| 신규 M3 문맥·stale 잠금 실제 DB | 21/21 |
| 전체 migration 원본 재구축 | 21/21 |
| API 단위 회귀 | 406 passed / 95 subtests passed |

DB 50개 시나리오는 PostgreSQL 15.19와 17.11에서 각각 통과했다. 전체 migration 원본 재구축은 **17.11**에서 통과했다. 단위 회귀는 별도 Python 프로세스에서 실행했으며 기존 Starlette/AnyIO deprecation warning 1개가 남는다.

새 문맥 검증은 원문 공백 보존, v1 session 불변·v2 격리, 다른 매장/회원/session 거절, composite FK, TTL 조회 시 미연장·만료, 사용자 선택과 추정 분리, 중복 수락 거절, 세 번째 되묻기 차단을 확인했다. 별도 DB 연결로 context/publication/card 갱신을 시도하고 PostgreSQL lock_timeout을 관측했다. 답변 transaction 중 공개 변경이 대기하고 다른 매장은 독립 진행하며 commit 뒤 과거/타 매장 인용이 거절된다.

## 발견·수정

1. Windows에서 PYTHONIOENCODING만 UTF-8로 설정하면 하위 프로세스 stdout을 CP949로 읽는 테스트 2개가 실패했다. 검증 runner에서 PYTHONUTF8와 PYTHONIOENCODING을 함께 설정하고 종료 시 기존 환경값을 복원하도록 수정했다. 테스트의 성공 조건을 완화하지 않았으며 재실행은 전부 통과했다.
2. 이전 R 실행 계획의 전체 재구축 PG15 전제는 잘못됐다. `supabase/config.toml`의 major_version은 17이며 초기 schema의 MAINTAIN 권한도 PG17 기준이다. PG15 원본 재구축에서 `unrecognized privilege type "maintain"`을 재현했다. migration 원문을 변경하거나 권한문을 제거하지 않고 PG17로 검증 환경을 맞췄다. 새 재구축 스크립트는 DB major가 저장소 설정과 다르면 실패한다. PG15 50개 성공은 호환성 검사로만 해석한다.
3. `verify_r_schema_rebuild.py`와 runner의 `-IncludeSchemaRebuild`를 추가했다. .env·기존 서비스 DB를 사용하지 않고 전용 loopback 서버에 새 UUID 이름의 DB를 만든다. 생성한 DB와 컨테이너만 정리한다. 전체 21개 migration을 원문 그대로 순서대로 적용했다.

검증 이미지:
- PG17 `pgvector/pgvector:pg17`, digest `sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f`
- PG15 `pgvector/pgvector:pg15`, digest `sha256:a947c45cdc5906a1bc951f20a8709e321256343ee0f251e4ae00b5e7def4e6da`

재현(저장소 루트; Python과 테스트 의존성 설정 필요):

```powershell
./api/scripts/verify_r_handoff.ps1 -Python <python.exe> -IncludeUnitTests -IncludeSchemaRebuild
```

기존 경량 PG15 검사에는 IncludeSchemaRebuild를 생략한다. 출력의 의도적 ValidationError/TimeoutError/원가 확정 실패 로그는 장애 주입 사례이며 최종 PASS/exit code와 함께 판단한다.

## 완료 범위와 다음 단계

지난 기록의 Docker 장애 및 새 M3 migration/FK/잠금 미실행 상태는 해소됐다. 최소 부모 schema에서의 서비스 검증과 별도의 전체 schema 재구축을 수행한 것이며, 실제 W 공개 서비스→v2 답변 API 종단 인수까지 완료한 것은 아니다.

다음은 R 실행 계획의 M2 승인 준비 manifest·색인 staging 접점과 adapter, 이어서 M3 요청 멱등성·메시지·인용·context 원자 저장 및 v2 API 연결이다. R2~R5 전체와 W 공동 wire 접점은 여전히 미완료다. 운영 DB에 migration을 적용하거나 commit/push하지 않았다.
