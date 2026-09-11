# AskBuddy MVP 데이터·API 계약 v1

작성일: 2026-09-10
상태: 구현 기준 확정안
제품 기준: `/Users/chabee/Downloads/ASKBUDDY_MVP_CURRENT.md`

## 1. 문서의 지위

이 문서는 2026-09-09 최종 MVP 명세를 현재 저장소에 구현하기 위한 데이터·API 계약이다.

- 제품 범위와 사용자 흐름은 `ASKBUDDY_MVP_CURRENT.md`가 최우선이다.
- 기존 `CLAUDE.md`, `docs/AskBuddy_개발가이드.md`, `docs/ingest-contract.md`는 현재 코드의 배경 자료로만 사용한다.
- 기존 문서와 충돌하면 이 문서를 구현 기준으로 사용한다.
- 기존 데이터는 삭제하거나 초기화하지 않고 추가 마이그레이션으로 보존한다.
- 이 문서는 테이블과 API의 논리 계약이다. 실제 SQL은 다음 단계의 신규 마이그레이션에서 작성한다.

## 2. 확정한 설계 기본값

| 항목 | 결정 |
|---|---|
| 매장 격리 | 기존과 같이 FastAPI가 JWT의 `store_id`로 강제한다. 요청 본문의 `store_id`는 신뢰하지 않는다. |
| 원본 자료 | 카드 제외·카테고리 삭제와 관계없이 보존한다. |
| 기타 카테고리 | 모든 매장에 시스템 카테고리로 정확히 하나 존재하며 삭제할 수 없다. |
| 삭제 | 카드 삭제는 `EXCLUDED`, 카테고리 삭제는 soft delete로 처리한다. |
| 추출/분류 | 업무 정보 추출과 카테고리 분류를 별도 단계로 실행한다. |
| 신규 카드 | 모두 `PENDING` 또는 불확실하면 `NEEDS_REVIEW`; 승인 전 직원·검색에 노출하지 않는다. |
| 카드 수정 | 수정 초안 저장과 직원 공개를 분리한다. 승인된 본문 수정은 새 버전을 만든 뒤 재승인한다. |
| 분류 이동 | 카드 본문 버전은 만들지 않는다. 수동 분류로 기록하며 승인·학습 이력을 유지한다. |
| 카테고리 변경 | 원본 재추출이 아니라 기존 카드 재분류를 기본으로 한다. |
| 재분류 충돌 | 가장 최신 카테고리 버전만 공개하고 더 최신인 사람의 수정·이동을 보호한다. |
| 로드맵 | 고정 게임판을 사용하지 않고 현재 승인 카드와 카테고리로 동적 구성한다. |
| 학습 완료 | 카드 ID 기준으로 보존한다. 새 본문 버전 공개 시 `RECONFIRM_REQUIRED`가 된다. |
| 점주 답변 | 답변 전송 성공을 승인 행위로 보고 즉시 공개 카드 버전으로 저장한다. |
| 점주 답변 분류 | `Q&A`를 업무 카테고리로 만들지 않는다. `OWNER_ANSWER`를 생성 출처로 보존하고 현재 업무 카테고리로 분류하며, 애매하면 `기타`를 사용한다. |
| 점주 답변 통합 | 유사 카드와의 관계를 동일·보완·충돌·신규로 나눈다. 원문 답변은 보존하고 자동 병합은 보수적으로 제한하며 충돌은 자동 공개하지 않는다. |
| 자주 묻는 질문 | 별도 지식 복제본을 만들지 않고 질문 빈도와 승인된 현재 카드를 연결한 파생 목록으로 제공한다. |
| 생성형 답변 | LLM은 승인된 현재 카드의 표현만 재구성한다. 서버 검증에 실패하면 생성 답변을 버리고 카드 원문 또는 `miss`로 폴백한다. |
| 알림 | 앱 내부 알림은 항상 제공하고, Web Push는 허용된 기기에 추가 전달한다. |
| 사용자 신뢰도 | 모델 confidence와 검색 score를 사용자 화면에 퍼센트로 노출하지 않는다. |
| 목 폴백 | API 실패를 성공으로 바꾸는 프론트 목 폴백은 제품 경로에서 사용하지 않는다. |

## 3. 공통 불변식

1. 브라우저는 PostgreSQL과 Supabase Storage 자격증명을 갖지 않는다.
2. 모든 DB 조회·변경은 JWT에서 구한 `store_id`로 제한한다.
3. LLM 호출은 FastAPI 안에서만 수행한다.
4. `kind: "miss"`이면 답변 LLM을 호출하지 않는다.
5. 검색과 직원 학습은 승인된 현재 공개 버전만 사용한다.
6. `ANSWERED` Buddy 메시지는 인용 카드가 한 건 이상이어야 한다.
7. 비동기 작업 재시도는 카드와 알림을 중복 생성하지 않아야 한다.
8. 오래된 비동기 결과는 최신 카테고리 설정이나 최신 사용자 변경을 덮어쓰지 않는다.
9. 저장 성공 응답을 받기 전에는 UI에서 완료 상태로 확정하지 않는다.
10. 푸시 전송 요청 성공, 사용자 수신, 알림 읽음, 업무 처리 완료는 서로 다른 상태다.

## 4. 식별자와 시간

- DB 기본키는 기존과 같이 `bigint` identity를 사용한다.
- API 필드명은 `snake_case`를 사용한다.
- 시간은 DB와 API 모두 UTC 기준 ISO 8601 `TIMESTAMPTZ`로 저장·전달한다.
- 화면의 KST 변환은 프론트에서만 수행한다.
- 외부 재시도 가능 쓰기 요청은 `Idempotency-Key` 헤더를 지원한다.
- 목록 API는 기본적으로 `limit`, `cursor` 기반 페이지네이션을 사용한다.

## 5. 상태 계약

### 5.1 원본 자료 전송 상태

`sources.upload_status`

```text
REGISTERED | UPLOAD_FAILED
```

- Storage PUT이 완료되고 `/ingest/sources` 등록까지 성공하면 `REGISTERED`다.
- Storage PUT 이전 실패는 서버에 원본 행이 없을 수 있으므로 프론트의 전송 실패 상태로 관리한다.
- 기존 `sources.status`는 마이그레이션 동안 호환 필드로 유지하고, 신규 API는 작업 상태를 사용한다.

### 5.2 추출 작업 상태

`ingest_jobs.status`

```text
QUEUED
  -> EXTRACTING
  -> CLASSIFYING
  -> SUCCEEDED | PARTIAL | NO_RESULT | FAILED
```

| 상태 | 의미 |
|---|---|
| `QUEUED` | 서버가 작업을 접수했지만 아직 실행하지 않음 |
| `EXTRACTING` | 카테고리와 무관하게 업무 정보를 추출 중 |
| `CLASSIFYING` | 추출 카드 후보를 대상 카테고리 버전으로 분류 중 |
| `SUCCEEDED` | 모든 대상 자료 처리 및 결과 저장 성공 |
| `PARTIAL` | 일부 자료 또는 일부 단계만 성공. 성공 결과는 보존 |
| `NO_RESULT` | 정상 처리됐지만 업무 카드가 0개 |
| `FAILED` | 사용할 결과를 저장하지 못하고 종료 |

터미널 상태는 `SUCCEEDED`, `PARTIAL`, `NO_RESULT`, `FAILED`다. 실제 측정값이 없으면 퍼센트나 남은 시간을 응답하지 않는다.

### 5.3 작업 내 자료 상태

`ingest_job_sources.status`

```text
QUEUED | EXTRACTING | CLASSIFYING | SUCCEEDED | NO_RESULT | FAILED
```

작업 상태는 자료 상태를 집계해 결정한다. 성공 자료와 실패 자료가 함께 있으면 `PARTIAL`이다.

### 5.4 카드 검토 상태

`knowledge_cards.review_status`

```text
PENDING | NEEDS_REVIEW | APPROVED | EXCLUDED
```

| 상태 | 의미 |
|---|---|
| `PENDING` | 아직 점주가 결정하지 않은 신규 카드 |
| `NEEDS_REVIEW` | 내용이 불확실하거나 수동 분류 카테고리 삭제 등으로 재확인이 필요 |
| `APPROVED` | 현재 공개 버전이 직원·검색에 노출됨 |
| `EXCLUDED` | 목록에는 기록으로 남지만 직원·검색에서는 제외 |

`기타`는 카테고리이고 `NEEDS_REVIEW`는 검토 상태이므로 서로 대체하지 않는다.

### 5.5 재분류 상태

`reclassification_jobs.status`

```text
QUEUED | RUNNING | SUCCEEDED | FAILED | STALE
```

`STALE`은 실행 도중 더 최신 카테고리 버전이 생겨 결과를 공개하지 않은 상태다.

### 5.6 질문 상태

```text
SUBMITTING | WAITING | ANSWERED | SUBMIT_FAILED
```

- DB 영속 상태는 기존 `WAITING`, `ANSWERED`를 유지한다.
- `SUBMITTING`, `SUBMIT_FAILED`는 요청 전후의 UI 상태다.
- 질문 저장에 실패하면 `WAITING`으로 표시하지 않는다.

### 5.7 학습 상태

```text
NOT_STARTED | DONE | RECONFIRM_REQUIRED
```

- 최신 공개 버전을 완료하면 `DONE`이다.
- 완료 이후 본문 새 버전이 공개되면 `RECONFIRM_REQUIRED`다.
- 카테고리만 이동하면 `DONE`을 유지한다.
- 기존 `LOCKED`, `IN_PROGRESS`는 확장 배포 기간에 DB가 호환 허용하고 신규 API가 `NOT_STARTED`로 해석한다. API 전환이 끝난 뒤 데이터와 제약을 정리한다. 강제 순차 잠금은 MVP 계약이 아니다.

### 5.8 알림 전달 상태

```text
PENDING | REQUESTED | FAILED
```

- `REQUESTED`는 push service에 전달 요청이 성공했다는 의미일 뿐 실제 수신이나 읽음을 뜻하지 않는다.
- 앱 내부 읽음은 별도의 `read_at`으로 기록한다.

## 6. 데이터 모델 변경 계약

### 6.1 기존 테이블 유지·확장

#### `stores`

추가 필드:

- `guide_completed_at timestamptz null`
- `category_version int not null default 1`

`guide_completed_at`은 승인된 카드가 최초 한 건 생겼을 때 설정한다. 이후 카드가 모두 제외돼도 과거 완료 기록 자체는 유지하되, 화면은 현재 승인 카드가 없는 상태를 별도로 보여준다.

#### `task_categories`

추가 필드:

- `is_system boolean not null default false`
- `created_version int not null default 1`
- `deleted_version int null`
- `deleted_at timestamptz null`
- `updated_at timestamptz not null default now()`

규칙:

- `기타`는 `is_system=true`이며 삭제 API가 409를 반환한다.
- 삭제는 행을 제거하지 않고 `deleted_at`과 `deleted_version`을 설정한다.
- 기존 `is_enabled`는 호환을 위해 유지하고 `deleted_at is null`과 동기화한다.

#### `sources`

추가 필드:

- `upload_status varchar(20) not null default 'REGISTERED'`
- `mime_type varchar(100) null`
- `original_filename varchar(200) null`

기존 `file_url`, `content_hash`, 유형별 하위 테이블과 원본 보존 규칙은 유지한다.

#### `knowledge_cards`

안정적인 카드 정체성을 담당한다. 추가 필드:

- `review_status varchar(20) not null default 'PENDING'`
- `assignment_type varchar(20) not null default 'AUTOMATIC'`
- `category_version int not null default 1`
- `origin_job_id bigint null`
- `draft_version_id bigint null`
- `published_version_id bigint null`
- `excluded_at timestamptz null`
- `excluded_by bigint null`
- `needs_review_reason varchar(50) null`

기존 `title`, `content`, `is_verified`는 호환 필드로 유지한다.

- `is_verified=true`는 `review_status='APPROVED'`이고 공개 버전이 있다는 뜻이다.
- 신규 코드의 읽기 기준은 `published_version_id`다.
- 마이그레이션 중 기존 승인 카드에는 현재 제목·본문으로 최초 공개 버전을 생성한다.

#### `card_embeddings`

추가 필드:

- `version_id bigint null`

검색 대상 임베딩은 카드의 `published_version_id`와 일치해야 한다. 기존 임베딩은 기존 카드로 만든 최초 공개 버전에 연결해 보존한다.

#### `roadmap_items`

추가 필드:

- `category_id bigint null`
- `published_version_id bigint null`
- `is_active boolean not null default true`

카드가 승인되면 카드당 활성 로드맵 항목 하나를 보장한다. 카테고리 변경은 같은 항목의 분류만 갱신한다.

#### `learning_progress`

추가 필드:

- `completed_version_id bigint null`
- `reconfirmed_at timestamptz null`

현재 공개 버전과 `completed_version_id`가 다르면 `RECONFIRM_REQUIRED`로 계산한다.

### 6.2 신규 테이블

#### `owner_ui_state`

- `user_id`, `store_id`
- `upload_guide_seen_at`
- `push_guide_seen_at`
- `created_at`, `updated_at`

안내 열람과 가이드 등록 완료를 분리한다.

#### `ingest_jobs`

- `job_id`, `store_id`, `created_by`
- `title`, `status`
- `category_version`
- `prompt_version`, `settings jsonb`
- `total_source_count`, `success_source_count`, `failed_source_count`
- `card_count`, `excluded_candidate_count`
- `error_code`, `error_message`
- `idempotency_key`
- `started_at`, `completed_at`, `created_at`, `updated_at`

#### `ingest_job_sources`

- `store_id`, `job_id`, `source_id`, `status`
- `card_count`
- `error_code`, `error_message`
- `started_at`, `completed_at`
- unique `(job_id, source_id)`

#### `card_versions`

- `version_id`, `store_id`, `card_id`, `version_no`
- `title`, `content`
- `change_source`: `EXTRACTION | OWNER_EDIT | OWNER_ANSWER`
- `created_by`, `created_at`
- unique `(card_id, version_no)`

추출 결과와 수정 이력을 덮어쓰지 않는다.

#### `card_evidence`

- `evidence_id`, `store_id`, `version_id`, `source_id`
- `locator_type`: `TIMESTAMP | PAGE | FRAME | TEXT_RANGE | MESSAGE | WHOLE_SOURCE`
- `locator jsonb`
- `excerpt text null`
- `created_at`

`locator` 예:

```json
{ "timestamp_sec": 41 }
```

```json
{ "page": 3, "start_offset": 220, "end_offset": 368 }
```

#### `card_review_events`

- `event_id`, `store_id`, `card_id`, `actor_id`
- `action`: `APPROVE | EDIT_DRAFT | PUBLISH_EDIT | EXCLUDE | RESTORE | MOVE_CATEGORY`
- `from_status`, `to_status`
- `from_category_id`, `to_category_id`
- `metadata jsonb`
- `created_at`

검수 부담 집계와 실행 취소의 감사 기록으로 사용한다.

#### `reclassification_jobs`

- `reclass_job_id`, `store_id`, `requested_by`
- `target_category_version`, `status`
- `total_count`, `applied_count`, `skipped_count`, `failed_count`
- `error_code`, `error_message`
- `idempotency_key`
- `started_at`, `completed_at`, `created_at`, `updated_at`

#### `reclassification_results`

- `store_id`, `reclass_job_id`, `card_id`
- `source_category_id`, `proposed_category_id`
- `card_updated_at_snapshot`
- `result`: `PENDING | APPLIED | SKIPPED_MANUAL | SKIPPED_NEWER_EDIT | FAILED`
- `reason`, `applied_at`
- unique `(reclass_job_id, card_id)`

결과를 먼저 staging한 뒤 최신 버전 여부를 확인해 공개한다.

#### `push_subscriptions`

- `subscription_id`, `user_id`
- `endpoint`, `p256dh`, `auth`
- `user_agent`, `enabled`
- `created_at`, `updated_at`, `last_success_at`, `last_failure_at`
- unique `(user_id, endpoint)`

#### `notification_events`

- `notification_id`, `store_id`, `recipient_user_id`
- `event_type`: `INGEST_COMPLETED | PENDING_QUESTION`
- `aggregate_type`, `aggregate_id`
- `dedupe_key`
- `title`, `body`, `destination`
- `status`, `read_at`
- `created_at`, `requested_at`
- unique `(recipient_user_id, dedupe_key)`

#### `notification_deliveries`

- `delivery_id`, `store_id`, `notification_id`, `subscription_id`
- `status`, `provider_message`, `attempt_count`
- `requested_at`, `failed_at`
- unique `(notification_id, subscription_id)`

#### `quality_evaluations`

- `evaluation_id`, `store_id`, `job_id`
- `evaluator_id`, `evaluated_at`
- `prompt_version`, `settings jsonb`
- `correct_fact_count`, `evaluated_fact_count`
- `required_item_count`, `covered_item_count`
- `review_duration_sec`
- `edited_card_count`, `excluded_card_count`, `moved_card_count`
- `other_appropriate_count`, `other_evaluated_count`
- `roadmap_rating`, `notes`
- `comparison_group varchar(100) null`

## 7. 동시성 및 보존 규칙

### 7.1 카테고리 버전

카테고리 추가·삭제가 성공할 때마다 `stores.category_version`을 트랜잭션 안에서 1 증가시킨다.

- 추출 작업은 시작 시 대상 버전을 저장한다.
- 분류 결과 공개 직전에 현재 버전을 다시 확인한다.
- 버전이 바뀌었으면 최신 버전으로 다시 분류하고 나서 공개한다.
- 재분류 작업의 대상 버전이 현재 버전보다 낮으면 `STALE`로 끝낸다.

### 7.2 사람의 변경 보호

- 수동 카테고리 이동 시 `assignment_type='MANUAL'`로 저장한다.
- 자동 재분류는 수동 분류를 덮어쓰지 않는다.
- 단, 수동 분류 대상 카테고리가 삭제되면 `기타`로 이동하고 `needs_review_reason='CATEGORY_DELETED'`를 설정한다. 기존 승인 상태는 유지한다.
- 재분류 시작 후 카드가 수정되거나 이동됐으면 `card_updated_at_snapshot` 비교로 적용을 건너뛴다.

### 7.3 카드 공개

- 초안 저장은 `draft_version_id`만 바꾼다.
- 승인 또는 수정 후 확인은 `published_version_id`를 바꾼다.
- 새 공개 버전 임베딩 생성이 실패하면 공개 포인터를 바꾸지 않는다.
- 공개 성공 후 기존 임베딩은 stale 처리한다.
- 카드 제외는 원본, 버전, 근거, 검토 기록을 삭제하지 않는다.

### 7.4 멱등성

- 동일 `content_hash`의 원본 등록은 기존 `source_id`를 반환한다.
- 동일 `Idempotency-Key`의 작업 시작은 기존 `job_id`를 반환한다.
- 카드 후보의 중복 키는 기본적으로 `(job_id, source_id, normalized title, normalized content)`다.
- 알림은 사용자와 이벤트를 포함한 `dedupe_key`로 한 번만 생성한다.
- 질문은 기존 동작과 같이 같은 매장의 동일 문장 `WAITING` 질문을 중복 생성하지 않는다.

## 8. 공통 API 응답

### 8.1 오류

신규·변경 API는 다음 오류 본문을 사용한다.

```json
{
  "error": {
    "code": "CARD_VERSION_CONFLICT",
    "message": "다른 변경이 먼저 저장되었습니다.",
    "retryable": false,
    "request_id": "req_...",
    "details": {}
  }
}
```

| HTTP | 용도 |
|---|---|
| 400 | 유효하지 않은 상태 전이 |
| 401 | 로그인 필요 또는 만료 |
| 403 | 역할·매장 권한 없음 |
| 404 | 없거나 접근할 수 없는 대상 |
| 409 | 중복, 최신 버전 충돌, 삭제 불가 |
| 413 | 파일 크기 초과 |
| 415 | 지원하지 않는 파일 형식 |
| 422 | 요청 필드 검증 실패 |
| 502 | 외부 저장소·AI·Push 서비스 실패 |

권한 없는 매장 데이터는 존재 여부를 노출하지 않기 위해 원칙적으로 404를 반환한다.

### 8.2 목록

```json
{
  "items": [],
  "next_cursor": null,
  "total": 0
}
```

`total` 계산 비용이 큰 목록은 생략할 수 있지만 O03/O05 배지는 별도 카운트 API 또는 bootstrap 응답에서 정확한 값을 제공한다.

## 9. 진입·세션 API

### `GET /app/bootstrap`

현재 로그인 사용자의 역할, 매장 상태, 기본 진입점, 배지를 한 번에 반환한다.

```json
{
  "user": { "user_id": 1, "role": "OWNER", "name": "준혁" },
  "store": {
    "store_id": 10,
    "store_name": "AskBuddy Cafe",
    "guide_completed": true,
    "category_version": 4
  },
  "badges": { "waiting_questions": 2, "pending_cards": 7 },
  "default_destination": "/owner/questions"
}
```

기본 목적지:

- 사장님, 매장 없음: `/owner/setup`
- 사장님, 최초 가이드 미완료: `/owner/upload`
- 사장님, 완료: `/owner/questions`
- 직원, 매장 합류 전: `/staff/join`
- 직원, 합류 완료: `/staff/roadmap`

알림/직접 링크가 있으면 로그인 후 먼저 해당 자원의 권한과 현재 상태를 확인하고 그 목적지를 복원한다.

기존 `/auth/signup`, `/auth/login`, `/auth/join`, `/auth/stores`, `/auth/invites`는 유지한다.

## 10. 카테고리 API

### `GET /categories`

현재 카테고리와 설정 버전을 반환한다.

```json
{
  "version": 4,
  "items": [
    { "category_id": 1, "name": "오픈 업무", "is_system": false, "sort_order": 1 },
    { "category_id": 9, "name": "기타", "is_system": true, "sort_order": 9999 }
  ],
  "reclassification": { "status": "RUNNING", "job_id": 31 }
}
```

### `POST /categories`

```json
{ "name": "고객 응대", "sort_order": 3 }
```

성공 시 새 카테고리, 증가한 `version`, 재분류 대상이 있으면 `reclass_job_id`를 반환한다.

### `DELETE /categories/{category_id}`

- 시스템 `기타` 삭제: 409 `SYSTEM_CATEGORY_IMMUTABLE`
- 일반 카테고리: soft delete 후 버전 증가
- 재분류 카드가 있으면 `202 Accepted`와 `reclass_job_id`
- 카드가 없으면 설정만 저장하고 `200 OK`

### `GET /reclassification-jobs/{job_id}`

재분류 상태와 실제 집계만 반환한다. 진행 퍼센트가 필요하면 `applied_count / total_count`로 계산 가능한 경우에만 표시한다.

### `POST /reclassification-jobs/{job_id}/retry`

실패한 작업을 같은 대상 버전으로 재시도한다. 현재 버전이 이미 달라졌다면 최신 버전의 새 작업을 반환한다.

마이그레이션 기간에는 기존 `/ingest/categories`를 위 API의 호환 어댑터로 유지한다.

## 11. 업로드·추출 API

### `GET /ingest/capabilities`

프론트가 지원 형식과 제한을 하드코딩하지 않도록 서버 설정을 반환한다.

```json
{
  "VOICE": { "extensions": ["mp3", "m4a", "wav"], "max_bytes": null, "max_duration_sec": null },
  "VIDEO": { "extensions": ["mp4", "mov"], "max_bytes": null, "max_duration_sec": null },
  "KAKAO": { "extensions": ["txt", "jpg", "jpeg", "png"], "max_bytes": null },
  "SCAN": { "extensions": ["pdf", "jpg", "jpeg", "png"], "max_bytes": null, "max_pages": null }
}
```

`null` 제한은 무제한이라는 홍보 문구가 아니라 아직 서버에서 계측 제한을 강제하지 않는다는 의미다. 실제 배포 전 실자료 측정 후 설정값으로 확정한다.

### `POST /ingest/upload-url`

기존 서명 URL 계약을 유지한다. 형식 실패는 415, 설정된 크기 초과는 413이다.

### `POST /ingest/sources`

기존 원본 등록 계약을 유지하고 `mime_type`, `original_filename`을 받을 수 있게 확장한다.

### `POST /ingest/jobs`

```json
{
  "title": "9월 오픈 업무 자료",
  "source_ids": [12, 13]
}
```

응답:

```json
{
  "job_id": 44,
  "status": "QUEUED",
  "category_version": 4,
  "source_count": 2
}
```

요청 성공이 서버 접수 완료 기준이다. 그 뒤 화면을 닫아도 작업은 계속된다.

### `GET /ingest/jobs`

O01의 자료·작업 목록이다. `status`, `cursor`, `limit`을 지원한다.

### `GET /ingest/jobs/{job_id}`

```json
{
  "job_id": 44,
  "title": "9월 오픈 업무 자료",
  "status": "PARTIAL",
  "category_version": 4,
  "counts": { "sources": 2, "succeeded": 1, "failed": 1, "cards": 8 },
  "sources": [
    { "source_id": 12, "filename": "오픈.mp3", "status": "SUCCEEDED", "card_count": 8 },
    { "source_id": 13, "filename": "마감.pdf", "status": "FAILED", "error": { "code": "EXTRACTION_FAILED", "message": "자료를 읽지 못했습니다." } }
  ],
  "review_destination": "/owner/cards/review?job_id=44"
}
```

### `POST /ingest/jobs/{job_id}/retry`

실패한 자료만 재시도한다. `NO_RESULT`는 자동 재시도하지 않고 사용자가 원본 확인 후 명시적으로 재시도한다.

기존 `/ingest/process`, `/ingest/status`는 단일 자료 작업 호환 어댑터로 유지한다.

## 12. 카드 API

### `GET /cards`

쿼리:

- `review_status=pending|needs_review|approved|excluded|all` (`needs_review`는 상태 또는 `needs_review_reason`이 있는 카드)
- `job_id`
- `category_id`
- `query`
- `cursor`, `limit`

응답 카드 필수 필드:

```json
{
  "card_id": 81,
  "review_status": "PENDING",
  "title": "우유 보관 위치",
  "content": "제빙기 아래 냉장고 2단에 보관합니다.",
  "category": { "category_id": 9, "name": "기타" },
  "assignment_type": "AUTOMATIC",
  "source": { "source_id": 12, "title": "오픈.mp3" },
  "job_id": 44,
  "has_evidence": true,
  "needs_review_reason": null,
  "updated_at": "2026-09-10T01:00:00Z"
}
```

confidence는 정렬에 사용할 수 있지만 사용자용 응답 필드로 기본 노출하지 않는다.

### `GET /cards/{card_id}`

카드의 초안, 현재 공개 버전, 근거, 검토 이벤트를 반환한다. 직원 역할에는 현재 공개 버전과 허용된 근거만 반환한다.

### `PATCH /cards/{card_id}/draft`

```json
{
  "title": "우유 보관 위치",
  "content": "제빙기 아래 냉장고 두 번째 선반에 보관합니다.",
  "expected_version_id": 101
}
```

- 미확인 카드: 초안만 저장하고 승인하지 않는다.
- 승인 카드: 새 초안을 만들고 기존 공개 버전은 유지한다.
- 버전 충돌: 409 `CARD_VERSION_CONFLICT`

### `POST /cards/{card_id}/approve`

초안 임베딩 생성과 공개 포인터 변경을 하나의 성공 단위로 처리한다. 실패하면 기존 공개 상태를 유지한다.

### `POST /cards/{card_id}/exclude`

카드를 `EXCLUDED`로 바꾸고 `undo_until`을 반환한다. 원본과 버전은 보존한다.

### `POST /cards/{card_id}/restore`

직전 제외 상태에서 복원한다. 이전에 승인된 공개 버전이 있으면 승인 상태로, 없으면 미확인 상태로 돌아간다.

### `PATCH /cards/{card_id}/category`

```json
{
  "category_id": 5,
  "expected_updated_at": "2026-09-10T01:00:00Z"
}
```

- `assignment_type='MANUAL'`
- 승인 상태와 공개 본문 유지
- 본문 재승인 불필요
- 동시 변경 충돌은 409

### `GET /cards/{card_id}/evidence`

원본 제목과 위치 정보를 반환한다. 비공개 Storage 원본이 필요하면 짧은 만료 시간의 읽기 URL을 API가 발급한다.

기존 `/ingest/review`, `/ingest/cards/*`는 마이그레이션 기간에 호환 유지한다.

## 13. 직원 로드맵 API

### `GET /learn/roadmap`

기존 경로를 유지하되 응답을 동적 카테고리 구조로 확장한다.

```json
{
  "store": { "store_id": 10, "name": "AskBuddy Cafe" },
  "counts": { "total": 8, "done": 3, "reconfirm_required": 1 },
  "continue_item_id": 502,
  "stages": [
    {
      "category_id": 5,
      "name": "오픈 업무",
      "order": 1,
      "items": [
        {
          "item_id": 501,
          "card_id": 81,
          "published_version_id": 102,
          "title": "우유 보관 위치",
          "status": "RECONFIRM_REQUIRED"
        }
      ]
    }
  ]
}
```

승인 카드가 없으면 `stages=[]`, 모든 count는 0이며 샘플 카드를 넣지 않는다.

### `GET /learn/items/{item_id}`

현재 공개 카드 본문, 카테고리, 근거, 원래 학습 복귀 정보를 반환한다.

### `PUT /learn/items/{item_id}/completion`

```json
{ "published_version_id": 102, "completed": true }
```

성공 시 현재 버전 완료와 갱신된 실제 count를 반환한다. 오래된 버전을 완료하려 하면 409와 최신 버전을 반환한다.

기존 `PATCH /learn/roadmap/items/{item_id}`는 호환 어댑터로 유지한다.

## 14. 질문·답변 API

### `POST /learn/chat`

기존 단일 진입 흐름을 유지한다.

hit 응답:

```json
{
  "kind": "hit",
  "message_id": 900,
  "answer": "우유는 제빙기 아래 냉장고 두 번째 선반에 보관합니다.",
  "answer_source": "GROUNDED_LLM",
  "grounding_status": "VERIFIED",
  "citations": [{ "card_id": 81, "version_id": 102, "title": "우유 보관 위치" }]
}
```

miss 응답:

```json
{
  "kind": "miss",
  "message_id": 901,
  "question_id": 77,
  "status": "WAITING",
  "message": "사장님께 확인 중이에요."
}
```

miss 응답은 질문 저장까지 성공한 뒤 반환한다. 질문 저장 실패 시 오류를 반환하고 대기 중으로 표시하지 않는다.

hit의 자연어 답변은 다음 게이트를 모두 통과할 때만 사용한다.

1. 검색은 승인된 현재 공개 버전만 사용한다.
2. 검색 근거가 부족하면 LLM을 호출하지 않고 `miss`로 처리한다.
3. LLM 입력에는 선택된 카드 본문과 대화에 필요한 최소 질문만 제공한다.
4. 출력은 답변과 사용한 `card_id`를 함께 반환하도록 제한한다.
5. 서버가 인용 카드 존재 여부와 숫자·시간·위치·고유명사의 근거 일치를 검사한다.
6. 검증 실패 시 생성 답변을 폐기하고 카드 원문을 표시한다. 원문도 질문의 근거가 되지 않으면 `miss`로 처리한다.

프롬프트 지시만으로 환각률 0을 약속하지 않는다. 검색 게이트, 구조화 출력,
서버 검증, 결정적 폴백을 함께 적용하고 골든셋과 실사용 질문으로 반복 측정한다.

`message_citations.version_id`에는 8단계 이후 답변 생성 당시 사용한 공개 버전을 기록한다.
이전 대화는 당시 버전을 소급해 확정할 수 없으므로 `LEGACY`와 `version_id=null`로 보존한다.
`answer_source`는 `GROUNDED_LLM`, `CARD_ORIGINAL`, `MISS`, `OWNER_ANSWER` 중 하나다.
LLM 호출 실패나 서버 검증 실패는 API 실패로 바꾸지 않고 `CARD_ORIGINAL`과
`FALLBACK`으로 저장·반환한다. 검색 이후 카드가 제외되거나 새 버전이 공개되면
그 결과를 답변으로 저장하지 않고 `miss` 흐름으로 전환한다.

### `GET /learn/pending`

O03의 미답변 목록이다. 점주만 접근 가능하며 정확한 대기 건수를 함께 반환한다.

### `GET /learn/pending/{question_id}`

알림 딥링크 검증과 질문 상세에 사용한다. 이미 답변됐으면 현재 답변과 `ANSWERED`를 반환한다.

### `POST /learn/pending/{question_id}/answer`

한 성공 단위:

1. 점주가 입력한 원본 질문·답변을 변경 없이 저장
2. 승인된 현재 카드에서 유사 후보 검색
3. 동일·보완·충돌·신규 관계 판정
4. 기존 카드 연결 또는 `OWNER_ANSWER` 카드 버전 생성
5. 최신 업무 카테고리로 분류, 애매하면 `기타`
6. 안전하게 자동 반영할 수 있는 결과만 승인·공개하고 임베딩 생성
7. 충돌하거나 병합 근거가 불충분하면 기존 공개본을 유지하고 검토 대상으로 저장
8. 질문 `ANSWERED`
9. 같은 질문을 한 직원들의 대화에 원본 사장님 답변 연결

중간 실패 시 `WAITING`을 유지하고 점주 입력을 클라이언트 초안으로 보존할 수 있게 오류를 반환한다.

사장님 답변이 직원에게 전달되는 시점과 LLM이 재구성한 카드 병합본이 공개되는
시점은 분리한다. 직원에게는 사장님 원문을 안전하게 전달할 수 있지만, LLM이 만든
병합 결과는 검증을 통과하기 전 기존 카드에 덮어쓰지 않는다.

반영 관계와 공개 규칙:

| 관계 | 처리 |
|---|---|
| `IDENTICAL` | 기존 현재 카드에 연결하고 중복 카드나 버전을 만들지 않는다. 서버의 엄격한 동일성 검사도 통과해야 한다. |
| `NEW` | 관계·카테고리 분석이 정상 완료된 경우 점주 원문 그대로 `OWNER_ANSWER` 승인 카드를 만들고 공개한다. 분석 실패 시 검토 대기한다. |
| `SUPPLEMENT` | 기존 공개 버전을 유지하고 보완 제안만 `PENDING_REVIEW`로 저장한다. 점주 승인 시 새 공개 버전이 된다. |
| `CONFLICT` | 기존 공개 버전을 유지하며 반드시 `PENDING_REVIEW`로 저장한다. 숫자와 부정 표현 차이는 서버가 충돌로 승격한다. |

같은 질문은 대기 항목 하나를 공유하지만 `pending_question_occurrences`에 모든 질문자와
채팅 메시지를 남긴다. 따라서 점주 답변은 같은 질문을 한 모든 직원에게 전달되며
FAQ 횟수도 대기 행 수가 아니라 실제 질문 발생 수를 사용한다.

점주 검토 API:

- `GET /learn/knowledge-proposals?status=PENDING_REVIEW`
- `POST /learn/knowledge-proposals/{proposal_id}/approve`
- `POST /learn/knowledge-proposals/{proposal_id}/dismiss`

### `GET /learn/faqs`

직원 화면의 `자주 묻는 질문` 목록이다. 새 지식 카드를 복제하지 않고 질문 기록을
의미 단위로 묶어 승인된 현재 공개 카드에 연결한다.

- 정렬 신호: 질문 횟수, 서로 다른 질문자 수, 최근 질문 시점
- 노출 조건: 현재 승인 카드로 답할 수 있는 질문
- 제외 조건: 미답변, 검토 중 제안, 비활성·제외 카드
- 개인정보: 질문자 이름과 개인별 횟수는 직원에게 노출하지 않는다.
- 카드의 공개 버전이 바뀌면 FAQ도 같은 현재 버전을 가리킨다.

## 15. 알림 API

### `GET /notifications/support`

서버의 VAPID 공개키와 안내 버전을 반환한다. 브라우저 기능 지원 및 iOS 홈 화면 설치 여부는 프론트에서 추가 판정한다.

### `POST /notifications/subscriptions`

PushSubscription을 현재 사용자에게 등록한다. 사용자 버튼 동작 뒤 권한을 얻은 경우에만 호출한다.

### `DELETE /notifications/subscriptions/{subscription_id}`

해당 기기 구독을 비활성화한다.

### `GET /notifications`

앱 내부 알림 목록이다. Push 권한 거절·미지원이어도 사용할 수 있다.

### `POST /notifications/{notification_id}/read`

읽음만 기록하며 카드 검토나 질문 답변 상태를 변경하지 않는다.

딥링크:

- 추출 완료: `/owner/cards/review?job_id={job_id}`
- 미답변: `/owner/questions?question_id={question_id}`

알림 생성 조건:

- 추출: 결과 저장 성공 + 검토할 카드 한 건 이상
- 질문: `WAITING` 질문 저장 성공

`NO_RESULT`, 전체 실패, 질문 저장 실패에는 성공 알림을 만들지 않는다.

## 16. 평가 API

### `POST /team/evaluations`

인증된 사용자 중 서버 설정의 평가자 allowlist에 포함된 사용자만 접근할 수 있다. 인증 우회용 별도 엔드포인트나 공용 토큰은 만들지 않는다. 사장님 네 번째 탭도 만들지 않는다.

### `GET /team/evaluations`

`job_id`, `comparison_group`, 평가자, 기간으로 조회한다. 원본 실행과 프롬프트 버전별 결과를 유지한다.

검수 시간과 행동 수는 `card_review_events`에서 서버가 계산하고, 사람 판정이 필요한 정확성·누락·로드맵 평가는 평가 요청으로 저장한다.

## 17. 프론트 화면과 계약 매핑

| 화면 | 주 API |
|---|---|
| A01 로그인·가입 | `/auth/*`, `/app/bootstrap` |
| A02 매장 초기 설정 | `POST /auth/stores`, `/categories` |
| A03 직원 초대·합류 | `/auth/invites`, `/auth/join` |
| O01 업로드 | `/ingest/capabilities`, `/ingest/sources`, `/ingest/jobs` |
| O02 처리 현황 | `GET /ingest/jobs/{job_id}` |
| O03 답변 대기 | `/learn/pending`, 답변 API |
| O04 이번 추출 검토 | `GET /cards?job_id=`, 카드 변경 API |
| O05 카드 목록 | `GET /cards`, bootstrap badge |
| O06 카드 상세 | `GET /cards/{id}`, draft/approve/exclude/category/evidence |
| O07 카테고리 관리 | `/categories`, `/reclassification-jobs/*` |
| O08 알림·초대 | `/notifications/*`, `/auth/invites` |
| S01 로드맵 | `GET /learn/roadmap` |
| S02 학습 상세 | `GET /learn/items/{id}`, completion API |
| S03 Buddy 질문 | `/learn/chat`, 채팅 조회 |
| T01 팀 평가 | `/team/evaluations` |

## 18. 기존 계약의 폐기·호환 규칙

| 기존 동작 | 처리 |
|---|---|
| 카테고리를 추출 허용 범위로 사용 | 폐기. 추출 후 분류로 변경 |
| 카테고리 밖 카드를 버림 | 폐기. 기타로 보존 |
| 카테고리 활성화 토글만 제공 | 호환 유지 후 CRUD로 대체 |
| `sources.status` 하나로 전체 처리 표현 | 호환 유지 후 `ingest_jobs`가 정본 |
| `is_verified` boolean만으로 미확인/제외 표현 | 호환 유지 후 `review_status`가 정본 |
| 승인 카드 본문 즉시 덮어쓰기 | 폐기. 버전 초안 후 재승인 |
| 고정 로드맵 단계 매핑 | 폐기. 카테고리·승인 카드 기반 동적 구성 |
| `Q&A`를 업무 카테고리로 추가 | 폐기. 업무 카테고리와 생성 출처를 분리하고 `OWNER_ANSWER`로 기록 |
| 질문 빈도마다 FAQ 카드 복제 | 폐기. 승인 카드에 연결된 파생 FAQ 목록으로 제공 |
| 프롬프트만으로 무환각 보장 | 폐기. 검색 게이트·서버 검증·원문 폴백을 필수로 사용 |
| API 실패 시 목 성공 처리 | 제품 경로에서 폐기 |
| 50%/80% 업로드 게이트 | 폐기 |
| 기존 사장님 종합 대시보드 | 폐기하고 3탭으로 대체 |
| 폴링 | 앱 내 상태 갱신에 유지 가능. Web Push를 별도로 추가 |

## 19. 다음 단계 DB 마이그레이션 완료 조건

1. 기존 시드와 사용자 데이터를 유지한 채 신규 스키마가 적용된다.
2. 모든 기존 매장에 `기타`가 정확히 하나 생긴다.
3. 기존 승인 카드는 최초 공개 버전과 연결된다.
4. 기존 미승인 카드는 `PENDING`으로 변환된다.
5. 기존 임베딩은 해당 공개 버전에 연결된다.
6. 기존 학습 완료는 기존 공개 버전 완료로 연결된다.
7. 새 상태 CHECK와 인덱스, unique 제약이 적용된다.
8. 마이그레이션을 두 번 실행해도 데이터가 중복되지 않는다.
9. 매장 A 토큰으로 매장 B의 신규 테이블 데이터를 조회·변경할 수 없다.
10. 롤백이 필요할 때 기존 컬럼과 데이터로 현재 앱을 다시 구동할 수 있다.

## 20. 구현 중 남은 운영 확인

아래는 제품 결정이 아니라 실제 환경을 측정해 채울 설정값이다. 기능 구현을 막지 않는다.

- 유형별 최대 파일 크기, 음성·영상 길이, PDF 최대 페이지
- 실제 Push용 VAPID 키와 HTTPS 배포 주소
- 실제 Gemini/OpenAI 키와 production `INGEST_MODE`
- 브라우저·실기기별 Web Push 결과
- 추출 및 검색 품질 기준 자료와 평가자

숫자를 임의로 사용자에게 약속하지 않고 `/ingest/capabilities`의 서버 설정을 단일 출처로 사용한다.

## 21. 2026-09-11 추가 제품 결정과 후속 검증

### 구현 우선순위

- 알림은 이 계약의 15단계 계획대로 앱 내부 알림을 정본으로 하고 Web Push를 추가 전달한다.
- 화면·기능 범위는 현재 15단계 MVP를 우선한다. `AskBuddy 설계 최종본 v4`의 V3·V4 기능은 이후 범위다.
- 디자인은 v4의 현재 코드 토큰을 임시 기준으로 보되, 실제 Figma를 받을 때 옐로·핑크 포인트 색을 다시 확정한다.

### 질문·답변 카드 검증 항목

구현 완료 후 다음을 소수 예제가 아니라 충분한 질문 세트로 반복 검증한다.

1. 새 질문·답변이 적절한 기존 업무 카테고리로 분류되는가.
2. 분류가 애매한 경우 정확히 `기타`로 가는가.
3. 동일 질문이 기존 카드나 FAQ를 불필요하게 복제하지 않는가.
4. 보완 답변이 기존 사실과 조건을 삭제하거나 뜻을 바꾸지 않는가.
5. 숫자·시간·위치·부정 표현의 충돌을 자동 병합하지 않는가.
6. 수동 이동된 `MANUAL` 카드를 자동 재분류가 덮어쓰지 않는가.
7. 제외 카드와 과거 공개 버전이 검색·생성 답변·FAQ·로드맵에 섞이지 않는가.
8. 생성형 답변의 모든 사실이 반환된 인용 카드에 존재하는가.
9. 생성 답변 검증 실패 시 카드 원문 또는 `miss`로 정확히 폴백하는가.
10. 카드 새 버전 공개 후 검색·FAQ·로드맵이 같은 공개 버전을 가리키는가.
