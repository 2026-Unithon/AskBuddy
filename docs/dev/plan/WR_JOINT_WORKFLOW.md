# W/R 공동 작업 실행 절차

**추가 우선 요청 완료:** [W 인계 §5](W_TO_R_PUBLICATION_HANDOFF_20260927.md)의 임베딩 재사용을 사용자 이미지의 A 방식으로 구현했다. 동일 매장·현재 공개판에서 버전/블록/입력/모델/사전/설정이 같은 벡터만 복사하며 전체 manifest 계약은 유지한다. [단위 1,124개·재사용 DB 11개·W 공개 66개 검증](../review/R_INDEX_REUSE_20260927.md). 다음 R 후보 검색 이전은 계속 남아 있다.

**최신 재개 결과:** Docker를 켠 뒤 REVIEW DB 검사와 점주 답변 인용의 저장·이력·근거 화면 보완을 진행했다. 단위 1,110개, 브라우저 42+36개, migration 33개 및 실제 W 제안 승인→R 완료→검색·인용 합성 검증이 통과했다. 아래의 Docker/출처 소비 대기는 이전 시점 기록이다. [최신 검증·배포 순서](../review/R_OWNER_CITATION_INTEGRATION_20260927.md)를 먼저 확인한다. 다음 R 작업은 점주 답변 후보 검색의 새 색인 이전이며, 운영 플래그·공동 계약 전체 확정·실자료 인수는 별도다.

## 2026-09-27 재개 현황 — PR #24 이후

원격 `origin/main`의 `b22be50`(PR #24)을 현재 작업 브랜치에 fast-forward 반영했다. 기존 미커밋 문서 변경은 보존했다. **아래 §1~9의 `68b4756` 기준 관찰보다 이 재개 현황과 [새 W 인계](W_TO_R_PUBLICATION_HANDOFF_20260927.md)를 먼저 읽는다.** 과거의 “W 생산·조정자·worker 없음”은 더 이상 현재 상태가 아니다.

| 구분 | 현재 상태 / 다음 행동 |
|---|---|
| 원격에 포함된 W 구현 | `publish/content.py`, `publish/approval.py`, 카드 승인 연결, `owner_answer_worker.py`, `approve_owner_proposal`, RAW 점주 답변 출처 migration·계약 및 합성 DB 검증 스크립트 |
| 이번 R 로컬 구현 | `finish_owner_review` 및 제안 승인 라우트 연결. proposal ID를 추가로 바인딩하고 REVIEW·최신 답변·현재 공개 버전 확인, 동일 결과 멱등 처리, 상태·알림을 동일 transaction에 기록 |
| 검증 | 전체 단위 1,104 passed / 4 xfailed / 131 subtests passed, schema 15개·fixture 3개 최신. Docker 엔진 미실행으로 DB 검증 대기. [실행 기록](../review/R_OWNER_REVIEW_HANDOFF_20260927.md) |
| R 다음 우선 작업 | `Citation`·`approved_renderer`·`answer_storage`의 점주 답변 출처 소비, 저장·이력·화면 호환 검증. 이후 실제 W 제안 승인→R 완료→재질문 DB 통합 |
| W 후속 | 레거시 `/ingest/cards/*` 공개 경로, 점주 편집 시 출처 보존. 기존 W 인계의 파일 소유 경계를 유지 |
| 공동 미확정 | 카드 매핑 DTO, 빈 manifest, 전체 재임베딩 비용·재사용, 제외/복원 best-effort의 계약 차이. 구현 존재를 J-C01~05 합의 완료로 바꾸지 않음 |

`W_OWNER_ANSWER_WORKER_ENABLED`와 `W_OWNER_ANSWER_RAW_PUBLISH` 설정은 이번에 변경하지 않았다. 원격 기본값은 둘 다 false다. REVIEW 완료 연결만으로 출처 인용이나 공동 왕복 C/D가 완료된 것은 아니다. 새 승인 라우트의 완료 접점은 R v2 REVIEW 원장이 있는 제안용이며, 레거시 답변의 원장 이관은 별도다.

작성일: 2026-09-27. 코드 확인 기준: `main`의 `68b4756`(PR #23 통합 머지).

이 문서는 다음 공동 작업을 재개할 때 사용하는 실행 안내다. 사용자가 제공한 공동 작업 설명을 현재 코드 및 [W 계약 검토 자료](W_CONTRACT_INPUT_20260927.md)와 대조했다. 제품 정본은 [MVP §30~31](../ASKBUDDY_MVP_CURRENT.md), 전체 실행 순서는 [개발 TODO](../DEV_TODO_CURRENT.md)다. 아래 **제안·미확정**은 합의나 구현 완료를 뜻하지 않는다.

## 1. 목표와 현재 출발점

연결할 접점은 두 가지다.

1. **W 승인 → R 검색:** 검수한 불변 카드 버전과 R이 검색·인용하는 버전을 일치시킨다. 공개와 색인 활성화는 함께 성공하거나 함께 취소한다.
2. **R 점주 답변 → W 지식 반영 → R 완료:** 직원에게 원문 답변이 도착한 상태와 승인 지식으로 반영된 상태를 구분하고, 검토 대기 후 나중 승인까지 연결한다.

| 항목 | 기준 커밋에서 확인한 상태 | 다음 작업 |
|---|---|---|
| W 재시도·복구 | PR #20의 복구·원자 저장과 #22의 실행별 원가 ID가 #23으로 main에 포함됨 | 공동 공개 경로의 완료로 간주하지 않음 |
| R CI | #23 및 머지 후 main의 단위·계약/DB/브라우저/필수 검사 통과 | 계약 변경 후 같은 검사 재실행 |
| R 색인 접점 | `prepare_index_request`, `activate_prepared_index` 구현·합성 DB 검증 있음 | 실제 W 승인 호출부와 연결 |
| W 카드 승인 | `approve_card`는 현재 카드 공개 포인터와 기존 `embed_card` 경로 사용 | 불변 참조 콘텐츠 생산 및 새 승인 조정 흐름 필요 |
| W 공개 서비스 | `publish_knowledge`는 존재하나 현재 카드 승인 경로와 연결되지 않음 | 권한·카드 CAS·activate까지 한 transaction으로 묶기 |
| R 점주 답변 접점 | claim/heartbeat/finish, 현재 승인판 확인, 재시도·알림 구현 | 실제 W worker와 연결 |
| REVIEW 이후 승인 | 기존 제안 승인 함수는 있으나 R 후속 완료 접점은 없음 | 새 완료 함수 또는 이벤트 계약 결정·구현 |

R 확인의 핵심은 **“검수한 내용과 검색하는 내용이 같은가, 실패하면 이전 공개판이 유지되는가”**다. 함수가 존재하거나 합성 fixture가 통과했다는 이유만으로 실제 W 생산 경로까지 완료 처리하지 않는다.

## 2. 다음 작업을 시작할 때

1. 현재 브랜치·미커밋 변경을 확인한다. 변경이 있으면 보존하고, 다른 사람의 수정까지 함께 커밋하거나 삭제하지 않는다.
2. 최신 main을 확인하고 이 문서의 기준 이후 변경을 대조한다. 아래 명령의 pull은 작업 트리가 깨끗하고 main에서 실행할 때만 사용한다.
3. [W 검토 자료](W_CONTRACT_INPUT_20260927.md)를 읽는다. W가 요청받았던 다섯 항목을 이미 정리했으므로, 자료를 처음부터 다시 요청하지 말고 미확정 항목을 확인한다.
4. §3 결정표를 공동 계약 PR에 옮기고, 각 항목의 담당·확정 내용·코드/fixture·검증 결과를 채운다.
5. **계약 PR A를 먼저 확정**한 뒤 W/R 구현을 각각 진행한다. 실제 운영 공개나 유료 평가는 별도 승인·인수 범위다.

```powershell
# 저장소 루트에서 확인
git status --short
git branch --show-current
git log -1 --oneline
git fetch origin

# 깨끗한 main인 경우에만 동기화
git pull --ff-only origin main
```

## 3. 첫 공동 계약 PR에서 확정할 항목

| ID | 확정할 것 | 현재 상태·제안 | 주 담당 / R 검토 |
|---|---|---|---|
| J-C01 | 카드별 초안·공개 버전 매핑 | 현재 `expected_card_revisions`는 카드와 대응이 모호하여 R wrapper가 비어 있지 않으면 거절. W는 `card_id / expected_draft_version_id / target_card_version_id` 제안 | W 저장 의미 제시 / R DTO·검증·호환 검토 |
| J-C02 | 변경 목록과 전체 공개 manifest | 현재 R은 준비 콘텐츠와 snapshot의 카드·버전 집합이 정확히 같아야 함. 첫 연결은 전체 manifest 방식 제안 | W 전체 목록 생산 / R 누락·제외·중복 검사 |
| J-C03 | 공개 transaction과 오류·재전송 | W가 승인·CAS·공개를 조정하고 같은 연결에서 R activate 호출. 실패 시 전체 rollback | W 호출부 / R 실패 주입·현재판 대조 |
| J-C04 | 점주 답변 상태별 결과·출처 | LINKED/PUBLISHED는 실제 승인판 증거 필요. REVIEW/FAILED는 공개 성공 아님 | W 결과·출처 생산 / R 완료 수신·재시도 |
| J-C05 | REVIEW → 나중 승인 완료 | 원래 사건은 REVIEW에서도 소비 완료됨. W의 `finish_owner_review` 제안은 아직 미구현·미확정 | W 승인 호출 위치 / R 완료 API 또는 이벤트 설계 |

합의할 때 공통 DTO/schema/fixture/migration 파일의 **주 편집자 한 명**을 정한다. 두 담당자가 같은 파일을 동시에 변경하지 않는다.

### J-C01 — 카드 버전 매핑

W 현재 구조는 수정마다 불변 `card_versions.version_id`를 만들고, `knowledge_cards.draft_version_id`와 `published_version_id`가 이를 가리킨다. 새 revision 번호를 추가해야 한다는 뜻은 아니다.

다음은 **합의용 예시이며 현재 DTO에 그대로 넣을 수 없다.**

```json
{
  "card_id": "1001",
  "expected_draft_version_id": "2003",
  "target_card_version_id": "2003"
}
```

R 확인 사항:

- 수정 전 → 수정 후 → 승인 후의 실제 필드 변화와 비교 코드를 확보한다.
- 승인 대상 초안과 공개할 불변 버전의 관계를 명시한다. 현재 W 제안에서는 두 version ID가 같다.
- 준비 중 수정·제외·권한 변경을 공개 transaction에서 재검사한다.
- 같은 카드 중복, 타 매장 카드, 없는 버전, 다른 카드의 버전을 거절한다.
- 기존 `expected_card_revisions` 처리와 schema 버전·호환 정책을 함께 확정한다. 매핑을 임의로 추정하지 않는다.

### J-C02 — 변경 카드와 전체 manifest

| 상황 | 변경 목록 | 발행 후 전체 검색 목록 |
|---|---|---|
| A만 수정·승인 | A v2003 | A v2003 + B v1500 |
| A 제외 | A 제외 | B v1500 |
| B 초안만 수정 | 공개 변경 없음 | 기존 A 공개판 + B v1500 |

R은 W에게 **준비 요청과 발행 후 전체 snapshot의 한 쌍**을 받는다. `card_ids`, `KnowledgeContent.cards`, `snapshot_card_versions`가 뜻하는 집합을 일치시킨다. 변경하지 않은 B의 새 초안을 끼워 넣거나 B 자체를 누락하면 안 된다.

추가 결정 사항:

- **색인 재사용:** 현재 동일 요청의 준비 결과 재사용은 있으나, 새 준비에서 변경하지 않은 카드의 벡터를 선별 재사용하는 기능과는 다르다. 첫 연결에서 전체를 준비할지, 증분 재사용을 구현할지 명시한다. 재사용한다면 매장·불변 버전·콘텐츠·모델·사전·색인 설정 동일성 검사가 필요하다.
- **전체 카드 제외:** 현재 `PrepareIndexRequest.card_ids`는 최소 1개다. 빈 공개판의 준비·활성화 계약은 별도로 정해야 한다. A/B 중 하나만 제외한 테스트로 마지막 카드 제외까지 완료 처리하지 않는다.

### J-C03 — 공개 transaction

아래는 목표 순서다. 현재 승인 함수가 이 전체를 실행하는 것은 아니다.

```text
transaction 밖
  W: 검수 대상 버전 고정 → 전체 manifest·KnowledgeContent 생산
  W → R: prepare_index_request
  R: 범위·hash·요청 동일성 검사 → 임베딩·색인 준비 (아직 비공개)

하나의 짧은 transaction / 같은 DB 연결
  W: 현재 승인 권한 확인, publication·카드 잠금, 예상 revision·초안 CAS
  W: publish_knowledge와 카드 공개 포인터·승인 상태·snapshot·참조 저장
  W → R: activate_prepared_index
  W: 모든 단계 성공 시 commit, 실패 시 전체 rollback

commit 후
  R: 새 질문 → 새 공개판 검색 → 답변·인용
```

- 외부 모델 호출 동안 transaction·DB 연결을 계속 점유하지 않는다.
- 공개 관련 잠금은 publication → card → pending/context → lease 순서를 기준으로 한다. 준비 행·멱등 작업 잠금까지 포함한 실제 순서는 공동 PR에서 코드로 검토한다.
- `publish_knowledge`의 STALE/ALREADY_APPLIED 결과를 구분하고, 재전송 때 무조건 새 activate나 finish를 반복하지 않는다. 동일 키에 다른 본문은 거절한다.
- 현재 준비 토큰 TTL은 15분이다. 만료된 준비를 공개하지 않으며, 기존 코드상 TTL 만료 후 재준비는 새 키가 필요하다.
- 준비 content hash·발행 snapshot hash는 각 계약의 해시 함수로 만든다. 버전 숫자나 문자열을 임의 조립해 대체하지 않는다.
- 기존 승인·제외·복원·점주 제안 승인 경로의 전환 범위를 함께 정한다. 새 경로와 옛 즉시 공개를 중복 실행하지 않는다.

### J-C04 — 점주 답변 결과

| 상태 | W가 제시할 것 | R 수용 조건 |
|---|---|---|
| LINKED | 기존 승인 카드와 연결 근거 | 현재 활성 snapshot·카드 공개 버전이 일치. fact 참조를 주면 해당 승인 블록에 포함 |
| PUBLISHED | 새 공개판·카드·필요한 사실 참조 | 공개와 activate가 성공하고 현재 knowledge revision과 일치 |
| REVIEW | 검토 제안과 owner_answer_id 연결 | 원문 전달과 별개로 검토 대기 표시. 새 지식 공개·완료 알림으로 처리하지 않음 |
| FAILED | 구조화 오류·재시도 여부 | 오류 계약 및 시도 제한에 따라 복구·종료. 공개 성공으로 처리하지 않음 |

현재 `ApplyOwnerAnswerResult`의 필드는 `status`, `fact_revision_id`, `card_id`, `knowledge_revision`, `retryable`, `error`다. `proposal_id`는 현재 결과 DTO에 없다. 검토 제안 연결을 DTO로 전달할지 서버에서 조회할지도 결정한다.

현재 `publication_evidence`는 LINKED/PUBLISHED의 카드·활성 색인·실제 승인 포인터를 대조한다. fact ID만으로 완료할 수 없다. LINKED의 revision, fact 필드 필수 여부를 강화하려면 호환 정책도 함께 바꾼다.

파일 없는 OWNER_ANSWER의 provenance도 확인한다. 현재 snapshot의 typed provenance와 RAW span에는 `source_id`가 필요하므로 임의 파일 source를 만들어 채우지 않는다. W의 실제 점주 답변 출처 저장 방식과 snapshot 계약을 대조하고 필요한 변경을 계약 PR에 포함한다.

### J-C05 — REVIEW 이후 승인

현재 `finish_owner_event(REVIEW)`는 원래 outbox 사건을 소비 완료로 남긴다. 나중 승인 때 그 사건을 다시 claim하는 흐름은 사용할 수 없다.

선택지는 **새 승인 완료 이벤트** 또는 **공개 transaction 안에서 호출하는 R 전용 완료 함수**다. W는 후자인 `finish_owner_review`를 제안했으나 아직 존재하는 API가 아니다.

어느 방식을 선택하든 다음을 확정한다.

- `proposal_id ↔ owner_answer_id ↔ question_id/revision_no` 연결과 매장 범위.
- REVIEW에서 허용되는 전환, 중복 완료의 응답, 같은 키·다른 결과 충돌 처리.
- 점주 답변이 바뀐 경우 이전 제안의 발행을 차단하는 최신 revision 재검사.
- 공개·색인과 R 완료의 원자성. 직접 호출이면 동일 transaction에서 실패 시 전체 rollback. 이벤트면 발행/outbox 원자 저장, 완료 지연·재처리·중복 방지 계약을 별도로 명시.
- 승인 취소·제외 후 신규 FAQ/검색/학습 상태와 과거 인용 보존.

## 4. 실제 구현 순서와 완료 기준

| 순서 / PR | 담당 | 선행 조건 | 완료 기준 |
|---|---|---|---|
| A. 공동 계약 | W 주 작성, R 필수 검토 | W 검토 자료와 현재 R 코드 | J-C01~05 결정, DTO/schema, 정상·거절 fixture, 호환·파일 소유자 확정 |
| B-W. 생산·승인 경로 | W | A | 불변 버전·블록·fact/RAW 참조 → 전체 콘텐츠·snapshot → 승인 조정자. 기존 공개판 보존 |
| B-R. 소비 보완 | R | A | 확정 매핑·manifest·오류 검사, 후속 REVIEW 완료 계약 구현, 계약 테스트 |
| C. 승인→검색 첫 통합 | W+R | B-W/B-R 최소 구현 | 실제 W 코드가 만든 합성 카드 A/B의 발행→검색→인용과 장애 반례 통과 |
| D. 점주 답변 왕복 | W worker + R 완료 수신 | C와 J-C05 구현 | 원문 전달→지식 반영→FAQ/학습/알림→재질문, REVIEW 이후 승인·복구까지 통과 |

B-W/B-R은 A 이후 별도 브랜치에서 병행할 수 있다. W가 합성 JSON을 손으로 작성한 fixture만 전달한 상태와 실제 W 생산 코드가 그 JSON을 만든 상태는 구분한다. 첫 통합의 규모는 카드 2장·카드당 최소 블록 1개로 작게 잡되 필수 참조·출처·검수 정보는 생략하지 않는다.

## 5. 점주 답변 왕복의 실행 순서

1. **R:** 직원 질문·관련 occurrence를 보존하고, 점주 원문/새 revision과 outbox를 원자 저장한다. 직원 원문 전달은 지식 발행과 구분한다.
2. **W:** `claim_owner_event`로 사건을 확보하고, stale 결과면 처리하지 않는다. 실제 처리 중 heartbeat를 유지한다. 현재 기본 lease는 60초, heartbeat 간격 상수는 20초다.
3. **W:** DB 연결을 놓고 연결/신규/보완/충돌을 판단하며 원문·출처·제안을 보존한다. 임의 모델 재서술을 점주 승인 원문으로 취급하지 않는다.
4. **W+R:** PUBLISHED는 §3 공개 흐름으로 발행하고, 같은 transaction에서 activate → `finish_owner_event`를 실행한다. finish 예외를 삼키지 않는다.
5. **W+R:** LINKED는 새 공개 없이 현재판 확인과 finish를 짧은 transaction으로 처리한다. REVIEW는 제안을 보존하고 원래 사건을 완료하되 후속 승인 연결을 남긴다.
6. **W+R:** 공개 실패 시 공개 transaction을 rollback한 뒤 실패 결과를 별도 transaction으로 기록한다. 현재 claim 유효성·최신 답변 검사는 유지한다. 재시도는 계약상 허용된 오류만, 자동 최대 10회이며 이후 명시적 재처리 경로를 사용한다.
7. **R:** 완료 증거·지식 상태·소비 기록·앱 알림을 저장하고 FAQ/학습/대화 갱신 및 재질문을 확인한다. 실제 모바일 push 수신은 앱 내 알림 저장과 별도 인수다.
8. **W+R:** REVIEW를 나중 승인할 때 J-C05에서 정한 경로로 R 완료를 전달한다. 원래 사건을 다시 claim하지 않는다.

## 6. 첫 통합의 필수 검증표

각 행에 사용한 commit·fixture·실행 명령·기대/실제 결과를 기록한다. 아래는 앞으로 실행할 체크리스트이며 현재 통과 기록이 아니다.

| ID | 주입 상황 | 기대 결과 | 주 검증 |
|---|---|---|---|
| PUB-01 | A/B 공개 후 A만 수정·승인 | A 새 버전 + B 기존 버전 검색·인용 | R |
| PUB-02 | 준비 중 A 재수정·제외 또는 승인 권한 변경 | 오래된 승인 거절, 이전 공개판 유지 | W+R |
| PUB-03 | 준비 토큰 만료·다른 매장·내용/manifest/hash 불일치 | 발행 거절, 부분 공개 없음 | R |
| PUB-04 | activate에서 예외 주입 | 카드 포인터·snapshot·현재판 변경까지 rollback | W+R |
| PUB-05 | 같은 요청 재전송 / 같은 키에 다른 본문 | 같은 결과 재사용 / 충돌 거절, 중복 발행 없음 | W+R |
| PUB-06 | A 제외·복원 | 신규 검색/FAQ/학습이 현재 공개판 반영, 과거 인용 보존 | R |
| PUB-07 | 마지막 카드 제외 | 합의된 빈 공개판 계약대로 처리 | W+R |
| OWN-01 | 직원 2명의 관련 질문에 점주 1명이 답변 | 두 직원의 원문·전달 대상 보존, 지식 상태 별도 표시 | R |
| OWN-02 | 사건 중복·worker 중단·lease 만료 | 카드/원문/알림 중복 없음, 이전 claim 완료 차단, 복구 가능 | W+R |
| OWN-03 | 처리 중 점주 답변 수정 | 이전 revision의 발행·완료 거절 | W+R |
| OWN-04 | finish 또는 완료 알림 저장에서 예외 | 같은 공개 transaction 전체 rollback | W+R |
| OWN-05 | REVIEW → 나중 승인 → 중복 완료 | R 상태 한 번 갱신, 재질문에서 승인 지식 조회 | W+R |
| OWN-06 | 재시도 가능한/불가능한 오류, 시도 소진 | 제한·backoff·종료·명시적 재시도 구분 | R |
| ISO-01 | 타 매장 카드·사건·제안·인용, 직원의 승인 시도 | 권한/매장 차단, 데이터 노출 없음 | W+R |

## 7. 확인할 코드와 검증 출발점

경로는 이 문서 기준 상대 링크다. 줄 번호보다 함수명을 기준으로 찾는다.

| 용도 | 코드·함수 |
|---|---|
| 현재 카드 수정·승인 | [cards/router.py](../../../api/app/cards/router.py): `update_draft`, `approve_card` |
| 내부 DTO | [contracts/publication.py](../../../api/app/contracts/publication.py): `PrepareIndexRequest`, `ApplyOwnerAnswerResult` |
| 승인 콘텐츠·snapshot | [contracts/snapshot.py](../../../api/app/contracts/snapshot.py): `KnowledgeContent`, `PublishedKnowledgeSnapshot` |
| 준비·활성화 | [reg/index_preparation.py](../../../api/app/reg/index_preparation.py): `prepare_index_request`, `activate_prepared_index` |
| W 공개 서비스 | [publish/service.py](../../../api/app/publish/service.py): `publish_knowledge` |
| 점주 사건 수신 | [learn/owner_handoff.py](../../../api/app/learn/owner_handoff.py): claim/heartbeat/finish/retry |
| 실제 공개 증거 검사 | [learn/owner_publication.py](../../../api/app/learn/owner_publication.py): `publication_evidence` |
| 기존 제안 승인 | [learn/knowledge_apply.py](../../../api/app/learn/knowledge_apply.py): `publish_new_proposal`, `publish_existing_proposal` |
| 준비 DTO 계약 테스트 | [test_r_w_index_contract.py](../../../api/tests/test_r_w_index_contract.py) |
| 색인 DB 검증 | [verify_r_index.py](../../../api/scripts/verify_r_index.py) |
| 점주 왕복 DB 검증 | [verify_r_owner_delivery.py](../../../api/scripts/verify_r_owner_delivery.py) |
| 실제 v2 API 검증 | [verify_r_v2_api.py](../../../api/scripts/verify_r_v2_api.py) |
| W 복구 검증 | [verify_w_ingest_recovery.py](../../../api/scripts/verify_w_ingest_recovery.py) |

현재 검증에 실제 W 승인 조정자/worker를 연결한 통합 사례를 추가해야 한다. 기존 검증만 재실행한 것을 C/D 완료로 적지 않는다.

Windows 저장소 루트, Python 가상환경·Docker가 준비된 개발 환경에서:

```powershell
Push-Location api
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short
.\.venv\Scripts\python.exe scripts/export_contract_schemas.py --check
.\.venv\Scripts\python.exe scripts/build_contract_fixtures.py --check
Pop-Location

# 이 스크립트가 만드는 일회용 loopback DB만 사용한다. 운영 .env DB가 아니다.
.\api\scripts\verify_r_handoff.ps1 -Python .\api\.venv\Scripts\python.exe -IncludeSchemaRebuild
```

계약 변경 시 schema/fixture를 생성 도구로 갱신한 뒤 `--check`와 양쪽 테스트를 통과시킨다. CI의 브라우저 검증도 확인한다. 위 runner가 요구하는 로컬 포트 `55439`를 다른 서비스가 사용 중이면 임의 종료하지 말고 원인을 기록한다.

## 8. 사람이 결정할 일과 착수 조건

| 항목 | 현재 상태 | 막히는 범위 / 지금 가능한 것 |
|---|---|---|
| J-C01~05 인터페이스 합의 | 미확정 | 공동 계약 A의 확정이 필요. W 자료 검토·R 반례·fixture 초안 준비 가능 |
| W 불변 참조 콘텐츠 생산 | 최소 생산 경로 필요 | 실제 C 통합의 선행. A와 독립 모듈 구현·합성 검증 가능 |
| 사람 검토 완료 정답·승인 snapshot | 실자료 인수 대기 | 실제 품질 평가를 막음. 합성 공동 개발은 가능 |
| 외부 AI 판정의 정답 수입 기준 | 사용자 지정 회의 안건 1번 | 자동 정답 채택 보류. 판정 자료 준비 가능 |
| 유료 모델 평가 예산 | 회의 결정 대기 | 실제 유료 평가 보류. 합성 provider 검증 가능 |
| Railway 운영 로그·접근·보존 | 회의/실환경 증거 확인 필요 | `.env` 존재만으로 입증 불가. 원문 중복 OFF·권한·30일 보존의 실제 설정/정리 증거 수집 필요 |

## 9. 공동 검토 기록 양식

계약 PR 본문에 아래 표를 복사해 사용한다. 미확정 상태를 임의로 확정하거나 구현 완료로 바꾸지 않는다.

| 결정 ID | W 근거·입출력 예시 | R 판정 | 합의한 필드·호환·실패 처리 | 구현 담당·파일 | 검증 사례·결과 | 확정 PR |
|---|---|---|---|---|---|---|
| J-C01 | W 자료 §① | R 수정 필요·공동 결정 필요 | 미확정 | 미배정 | PUB-02/03 | 미정 |
| J-C02 | W 자료 §② | 전체 manifest 수용 가능·빈 목록/재사용 결정 필요 | 미확정 | 미배정 | PUB-01/06/07 | 미정 |
| J-C03 | W 자료 §③ | R 접점 있음·W 호출부 필요 | 미확정 | 미배정 | PUB-02~05 | 미정 |
| J-C04 | W 자료 §④ | R 완료 검사 있음·W 생산/출처 필요 | 미확정 | 미배정 | OWN-01~04 | 미정 |
| J-C05 | W 자료 §⑤ | 새 R 완료 경로·공동 결정 필요 | 미확정 | 미배정 | OWN-03/05 | 미정 |

작업 종료 시 기준 커밋, 결정한 항목, 아직 막힌 항목과 이유, 다음 PR 담당, 실행한 검증 및 미실행 검증을 기록한다. 새 검증 결과는 `docs/dev/review/`에 별도 문서로 남기고 과거 기록을 고쳐 쓰지 않는다.
