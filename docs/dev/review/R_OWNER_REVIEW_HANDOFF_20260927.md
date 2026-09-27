# R REVIEW 후속 승인 연결 — 2026-09-27

## 기준과 범위

- 시작: `codex/wr-joint-workflow-docs`, `68b4756`, 기존 미커밋 문서 3개.
- `git fetch origin` 뒤 변경 파일 비중첩을 확인하고 `git merge --ff-only origin/main`으로 `b22be50`(PR #24)을 반영했다. 기존 문서 변경은 보존했다.
- 입력: [공동 절차](../plan/WR_JOINT_WORKFLOW.md), [W 계약 자료](../plan/W_CONTRACT_INPUT_20260927.md), [최신 W 인계](../plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md).
- 새 변경은 로컬 작업 트리이며 commit/push/PR 생성은 하지 않았다. 운영 플래그·환경 변수·운영 DB는 변경하지 않았다.

## 구현

`api/app/learn/owner_handoff.py`의 `finish_owner_review`는 W 공개 hook이 넘긴 연결에서만 실행한다. 열린 transaction을 요구하고, 기존 `publication_evidence`로 현재 snapshot·활성 색인·승인 포인터를 검증한다. 요청 카드 버전도 비교한다.

제안을 매장 범위에서 잠그고 `proposal_id ↔ answer_id ↔ question_id/revision_no`, 제안의 PUBLISHED 상태·결과 카드/버전을 확인한다. pending 잠금 이후 최신 revision을 재확인한다. REVIEW만 PUBLISHED로 전환하며, 저장 결과에 `review_proposal_id`와 공개 증거를 함께 남긴다. 동일 결과의 재호출은 쓰기·알림을 반복하지 않고 다른 결과는 거절한다. 소비된 원래 사건은 다시 열지 않는다. 알림 예외는 공개 transaction까지 전파한다.

W의 5개 위치 인자 callback은 유지하고 라우트 closure에서 `store_id`와 `proposal_id`를 바인딩했다. 공통 DTO/schema/migration은 변경하지 않았다. 이 로컬 구현을 공동 계약 전체 합의로 간주하지 않는다.

`api/app/learn/router.py`의 제안 승인 라우트는 현재 OWNER 멤버십을 확인하고 `approve_owner_proposal(..., notify_r=...)`로 연결했다. 요청 DB에 transaction을 열고 호출하지 않는다. 재요청 응답 카드/버전은 저장된 제안 결과에서 읽는다. 출처/콘텐츠/경합 실패는 409, 그 외 준비 실패는 retryable 502다. 비용은 OPERATING/PRODUCT/EMBED와 제안 operation ID로 기록한다.

## 검증

저장소 루트에서:

```powershell
Push-Location api
.\.venv\Scripts\python.exe -m pytest tests/test_r_owner_review.py tests/test_w_owner_proposal_approval.py -q --tb=short
# 42 passed

# 기존 시스템 임시 폴더 접근 거절을 피하기 위한 저장소 내부 임시 경로.
# basetemp는 매 실행 새 하위 경로를 지정한다.
New-Item -ItemType Directory -Path tmp -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short -p no:cacheprovider --basetemp=tmp/r-owner-review-next-run
# 이번 실행: 1104 passed, 4 xfailed, 131 subtests passed
.\.venv\Scripts\python.exe scripts/export_contract_schemas.py --check
# schema 15개 최신
.\.venv\Scripts\python.exe scripts/build_contract_fixtures.py --check
# fixture 3개 최신
Pop-Location
```

전체 검사의 첫 시도는 시스템 tmp 접근 거절로 94개 setup error가 발생했다. 두 번째 시도는 basetemp 부모 폴더 누락으로 실패했다. 부모를 만든 뒤 전체 재실행이 통과했다. 잔여 경고는 Starlette/AnyIO deprecation 1개다.

새 단위 검사는 REVIEW 전환, 동일 완료 멱등성, 다른 상태/결과 거절, 최신 revision 변경, 다른 카드 버전/답변/없는 제안, transaction 필수, 알림 예외 전파, 라우트 권한·결과 매핑을 포함한다.

`verify_r_owner_delivery.py`에는 실제 DB용 제안/상태 rollback, 잘못된 참조 거절, 중복 알림 방지, 원래 사건 소비 유지, 새 답변 이후 완료 거절을 추가했다. **이 DB 시나리오는 작성했지만 실행하지 못했다.** Docker Desktop Linux 엔진 named pipe가 없어 권한 밖 재확인에서도 연결 실패했다. 이 시나리오는 기존 승인 snapshot을 사용하는 R 수신 검증이며 실제 W 생산 코드의 왕복 인수와 다르다.

Docker 가동 후 실행:

```powershell
.\api\scripts\verify_r_handoff.ps1 -Python .\api\.venv\Scripts\python.exe -IncludeSchemaRebuild
```

## 남은 작업과 다음 담당

1. R: DB runner 실행·수정 및 실제 W `approve_owner_proposal` hook을 거치는 왕복 사례. 브라우저/CI는 이번에 미실행.
2. R: `RawSpan.source_id=None` 소비 보완. Citation 계약, DB 인용 저장, 과거 응답 overlay, 직원 화면까지 검증한 뒤 RAW 공개 플래그 활성화를 검토한다.
3. R/W: 레거시 제안은 v2 revision/REVIEW 원장이 없어 이 완료 접점의 대상이 아니다. 이관 계약 필요. W의 이미 PUBLISHED 제안 fast path는 hook을 재실행하지 않으므로 과거 미연결 승인까지 복구했다고 간주하지 않는다.
4. R: 후보 검색을 새 색인으로 이전. W: 이후 호환 쓰기·옛 승인 함수 제거 및 `/ingest/cards/*` 정리.
5. 공동: 전체 manifest 비용·재사용, 마지막 카드 제외, 제외/복원 원자성, 카드 매핑·호환 결정. 현재 구현의 best-effort 동작을 기존 공동 목표와 동일하다고 표시하지 않는다.

이번 범위는 W 인계 우선순위 1의 로컬 구현이다. 점주 답변 인용 보완과 DB/통합 인수가 남아 C/D 완료 및 운영 사용 가능으로 표시하지 않는다.
