# R 공개 색인 임베딩 재사용 — 2026-09-27

## 요청과 기준

원격 fetch 결과 `origin/main`은 `b22be50`(PR #24)으로 로컬 HEAD와 같았다. 신규 원격 변경은 없고 이전 REVIEW·인용 작업은 보존했다. [W→R 인계 §5](../plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md) 및 사용자가 첨부한 이미지의 **A 방식: 전체 목록을 유지하면서 같은 블록 벡터 복사**를 구현했다. 후보 검색 이전보다 이 요청을 먼저 처리했다.

## 구현 범위

`api/app/reg/index_preparation.py`에서 새 준비를 만든 뒤 현재 공개 색인의 재사용 가능한 벡터를 한 번에 읽는다. 다음 조건을 모두 만족해야 한다.

- 같은 매장, 현재 `knowledge_publications.current_snapshot_id`에 연결된 CONSUMED 준비.
- 같은 임베딩 모델, 색인 설정 버전, glossary 버전, renderer 버전. 차원은 기존 1536 계약 유지.
- 같은 카드 ID·불변 버전 ID·블록 ID·승인 원문·검색 문자열. 이 다섯 필드의 digest로 조회하고 실제 필드 동등성도 비교한다. 제목/조건이 달라 검색 입력이 바뀌면 재사용하지 않는다.
- 벡터가 유한한 숫자 1536개이고 전부 0이 아니어야 한다. 유효하지 않은 저장 벡터는 cache miss로 처리한다.

일치한 벡터는 기존 DB의 벡터 문자열을 재반올림 없이 새 준비 행에 복사한다. 불일치 블록만 기존 `recorded_embeddings`에 보내며, 전체 일치면 공급자 및 usage 기록 호출을 생략한다. 외부 호출 전에 DB 연결을 반환한다. 새 준비에는 **전체 manifest의 문서·벡터**가 저장된다.

DTO·migration·activation 계약은 이번 재사용 구현에서 변경하지 않았다. 기존 멱등 키/본문 검증, claim fencing, 준비 TTL, 공개 CAS, snapshot hash·전체 manifest 검사 및 공개 rollback을 유지한다. 활성 공개판의 준비 TTL이 지났더라도 그 불변 벡터는 재사용할 수 있으나, 새 준비의 TTL을 우회하지 않는다.

안전한 첫 범위로 현재 활성판만 재사용한다. 미공개 PREPARED·실패 준비·다른 매장·과거 비활성판에서 가져오지 않는다. 따라서 제외 후 복원처럼 활성판에 없던 카드는 다시 임베딩할 수 있다. 별도 범용 캐시나 변경분만 발행하는 B 방식은 구현하지 않았다.

## 검증 결과

| 검사 | 결과 |
|---|---|
| 전체 단위 | **1,124 passed**, 4 xfailed, 131 subtests passed |
| 재사용 실제 DB | 11 checks: 전체 일치 0호출, 전체 벡터 저장, 변경 입력만 호출, 미공개 준비 제외, 새 버전/모델/설정/사전/렌더러 변경 재임베딩, 매장 격리, 공개 포인터 불변 |
| 실제 W A/B 승인 | A만 수정하면 A 블록 1개만 공급자에 전달되고 B는 재사용, 전체 snapshot은 A 새 판+B 기존 판 유지 |
| 격리 DB 전체 runner | migration 33개, M2 42개, RERANK 14개, 답변 저장 20개, v2 API 157개, 점주 전달 60개, 보존 13개, 점주 인용 8개, W 공개 66개 통과 |
| 매장 격리 AST | `api/app/reg` 9개 파일 위반 0 |

M2 장애/lease 시험은 실제 공급자 호출이 일어나도록 cache miss 입력을 명시했다. 동일 입력의 typed 준비가 이제 전부 재사용되어 공급자 내부의 보조 체크 2개가 실행되지 않으므로 M2 출력 수는 이전 44에서 42가 됐다. 장애/timeout/재시도 시나리오는 그대로 통과했다.

```powershell
.\api\scripts\verify_r_handoff.ps1 -Python .\api\.venv\Scripts\python.exe -IncludeSchemaRebuild
Push-Location api
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short -p no:cacheprovider --basetemp=tmp/r-index-reuse-next-run
.\.venv\Scripts\python.exe scripts/export_contract_schemas.py --check
.\.venv\Scripts\python.exe scripts/build_contract_fixtures.py --check
Pop-Location
.\api\.venv\Scripts\python.exe .claude/skills/store-isolation-check/check_store_id.py api/app/reg
```

로그: `api/tmp/r-index-reuse-db.log`(Git 제외). 단위 경고는 기존 Starlette/AnyIO deprecation 1개다. 모델 호출은 합성 대역이며 실자료 비용·지연 측정은 하지 않았다. 이번 범위는 R 백엔드 재사용으로 웹 변경은 없고 브라우저 검사는 이전 인용 작업의 결과와 구분한다.

## 남은 작업

- 전체 manifest 조립·검증·DB 문서 복사는 여전히 전체 카드 수에 비례한다. 이번 개선은 공급자 임베딩 호출량을 줄이는 것이다.
- W 카드/제안 승인에 남아 있는 옛 `card_embeddings` 호환 임베딩 1회는 별개다. 다음 R 작업인 점주 답변 후보 검색의 새 공개 색인 이전 후 W가 제거한다.
- 모델 이름이 같아도 실제 모델/전처리가 변경되면 모델 식별자 또는 `INDEX_CONFIG_VERSION`을 바꿔 이전 벡터와 구분해야 한다.
- 빈 manifest·제외/복원 best-effort·카드별 매핑·실자료/운영 인수는 계속 별도다.

기존 로컬 작업을 포함해 커밋·push·운영 적용은 하지 않았다.
