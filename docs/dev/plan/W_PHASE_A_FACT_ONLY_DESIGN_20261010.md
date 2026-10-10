# Phase A — 레거시 RAW 제거 · 사실→카드 단일 경로 · 1회 삭제 (설계)

작성: 2026-10-10 (KST). 담당: W. 브랜치: W3b 커밋 뒤 그 위에서 `w/fact-only-cards`.
짝 문서: **Phase B — 입구 라우터·분류기·체크리스트 카드 단위** (`W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md`). A 를 먼저 하고 B 를 그 위에 쌓는다.
결정 출처: 2026-10-10 사용자 대화. 기준: `docs/dev/review/WR_CARD_EDIT_FACT_REVIEW_20261005.md` §3-1, MVP §30~31, W3a·W3b 설계.

---

## 1. 목표

어떤 자료든 `입력 → 사실 추출 → 사실(공통 형식) → 원장 → 사실→카드 조립 → 검수·공개` **한 길**만 남긴다.
카드 본문은 언제나 서버가 사실에서 렌더링하고, 공개판은 사실 블록으로만 싣는다.

**RAW 란:** 사실로 쪼개지지 않은 글 덩어리를 카드 본문으로 그대로 공개하는 방식. 지금 RAW 를 만드는 W 경로는 셋이다.

| 경로 | 사실 추출 | 카드 문장 | 공개 |
|---|---|---|---|
| 업로드 옛 조립(W3a 이전) | 함 | 조립 모델의 자유 문장 | RAW |
| 점주 답변 | 안 함 | 답변 원문 그대로 | RAW |
| 점주 자유 본문 편집 | 안 함 | 점주 본문 그대로 | RAW |
| 업로드 새 조립(W3a·W3b) — **남길 것** | 함 | 서버가 사실을 렌더링 | 사실 블록 |

## 2. 사용자 결정 (2026-10-10)

| # | 결정 |
|---|---|
| A-U1 | W 플래그 `w_entity_revision_enabled`·`w_upload_proposals_enabled`·`w_fact_assembly_enabled`·`w_fact_card_edit_enabled` 를 **없앤다**(항상 켜진 동작) |
| A-U2 | RAW 를 만드는 W 경로 셋을 모두 지운다 |
| A-U3 | 점주 답변은 **사실로 전환**(사실 추출 → 원장 → 조립) |
| A-U4 | R 소유 코드의 RAW 처리(계약 `BlockKind` RAW, R 렌더러·색인)는 지우지 않고 **R 에 인계** |
| A-U5 | 기존 데이터는 **배포 때 1회 도는 migration** 으로 지운다. 범위: 지식 전부 + 업로드 자료 + 답변 인용 기록 |
| A-U6 | 남기는 것: 매장·계정·카테고리·근무조, 질문·점주 답변·채팅 문장, 비용 원장, 알림, 로드맵 틀, 체크리스트 제출 기록 |
| A-U7 | 작업 분리: A = 레거시 제거, B = 분류기 + 체크리스트 + 기타 |

## 3. 코드에서 확인한 것

| # | 사실 | 위치 |
|---|---|---|
| F1 | 업로드 옛 조립 경로 | `api/app/ingest/pipeline.py:215-232`, `assemble_assertions`, `api/prompts/assemble_cards.ko.txt`, `ExtractionResult.cards`(`ingest/schemas.py:40`), mock `_assembled`(`extract/mock.py:92`) |
| F2 | 카드 행 INSERT·제목/본문 UPDATE 시 블록 없는 판을 만드는 트리거 `trg_knowledge_cards_version_legacy_write` | `supabase/migrations/20260910133000_mvp_contract_v1.sql:659`, `20260911090000_card_draft_contract.sql` |
| F3 | 공개 단계 RAW: `ensure_raw_blocks`, `build_knowledge_content` RAW 분기, `_fix_blocks` | `api/app/publish/content.py:134-210·565-585`, `publish/approval.py:241·312` |
| F4 | 자유 본문 편집 `PATCH /cards/{id}/draft` + web textarea | `api/app/cards/router.py` `update_draft`, `cards/repository.py:188` `create_draft`, `web/app/owner/cards/[cardId]/page.tsx`, `web/lib/api.ts` `updateProductCardDraft` |
| F5 | 점주 답변 순환: R 이 답변 저장 → 이벤트 `OWNER_ANSWER_SUBMITTED` → W worker 가 R `knowledge_loop.build_knowledge_plan` 으로 관계 분석 → NEW 는 `create_owner_answer_card`(RAW) 자동 공개, SUPPLEMENT/CONFLICT 는 PENDING_REVIEW → R 라우터가 W `approve_owner_proposal` 호출 | `api/app/cards/owner_answer_worker.py`, `api/app/learn/knowledge_apply.py:91·459·505·569`, `learn/router.py:835`(R) |
| F6 | 점주 답변은 사실이 되지 않는다(`record_owner_answer_fact` 는 검증 스크립트만 호출) | `api/app/ingest/fact_ledger.py:341` |
| F7 | 호출자 없는 옛 함수 `publish_new_proposal`·`publish_existing_proposal`·`prepare_proposal` | `knowledge_apply.py:155·226`, `scripts/verify_w_publication_flow.py:680-685` |
| F8 | 새 사실이 공개·수동·점주 초안 카드 대상에 붙으면 `EXISTING_CARD` 로 보류(DEFER), 보는 화면 없음 | `api/app/ingest/fact_cards.py:184-195` |
| F9 | 작업 `card_count` = 이어진 서로 다른 카드 수 | `api/app/ingest/job_worker.py:126-180` |
| F10 | 설정은 모르는 env 값을 무시(`extra="ignore"`) | `api/app/config.py:35` |
| F11 | 빈 공개판은 첫 직원 질문 때 R 이 만든다(`ensure_initial_publication`, 멱등 키 `r-initial-empty`) | `api/app/publish/empty.py`, `learn/v2_router.py:403`(R) |
| F12 | DELETE 를 막는 불변 트리거: `r_answer_citations`·`r_answer_receipts`(R), `fact_revisions`·`fact_revision_meta`·`knowledge_entity_events`, `knowledge_snapshots`(R), 색인 문서 보존 함수. `api/scripts/reset_eval_store.py:36-100` 이 트랜잭션 안 트리거 끄기·켜기와 삭제 순서를 이미 갖고 있다 | 각 migration |
| F13 | `card_version_blocks` 는 `card_versions` 로 FK 가 없다 → 판을 지워도 블록이 안 지워진다(명시 삭제). 카드 포인터(draft/published)는 RESTRICT, `message_citations` 는 판에 RESTRICT | M1 `20260916100000:156`, 탐색 기록 |
| F14 | 배포: `deploy-api.yml` 이 DB 백업 → `supabase db push` → 서버 배포. env 는 저장소 밖 `/home/ubuntu/askbuddy.env`, W 플래그 줄 없음 | `.github/workflows/deploy-api.yml`, `deploy/compose.yml` |
| F15 | 데모 시드가 RAW 카드를 만든다 | `db/002_seed_demo.sql:8`, `api/scripts/demo_seed.py:271` |
| F16 | 체크리스트 항목은 연결 카드 공개 본문을 줄로 자른 것 | `api/app/checklist/repository.py:261-276` — **Phase B 에서 카드 단위로 바꾼다** |

## 4. 설계

### A-D1 플래그 제거
- 네 플래그와 `w_owner_answer_raw_publish` 를 `config.py` 에서 지우고, 읽는 곳은 "켜짐" 분기만 남긴다. 설정 검증기(`config.py:245-248`)도 지운다.
- 유지: `w_owner_answer_worker_enabled`(운영 스위치 — 꺼지면 순환이 멈춘다), `assemble_concurrency`, `w_entity_candidate_max`, `card_fact_parse_*`.
- 테스트·검증 스크립트의 플래그 토글과 "꺼짐 = 옛 동작" 검사는 지운다.

### A-D2 레거시 W 코드 제거
- **업로드:** F1 전부 삭제. `_persist` 의 옛 카드·레거시 `facts` 쓰기 삭제(사실 카드 경로가 쓰는 공용 도우미는 유지).
- **공개:** `ensure_raw_blocks`·RAW 분기 삭제. **사실 블록 없는 판은 공개 거절**(`InvalidContent`, fail closed). entity_id 이름공간 가드는 "공개판에 RAW 카드가 없다" 확인으로 바꾼다.
- **편집:** `PATCH /cards/{id}/draft`, web 자유 편집기, 레거시 카드 화면 분기 삭제(W3b 사실 편집만). 다른 호출자가 없으면 `repo.create_draft` 삭제.
- **트리거 F2:** 새 migration 으로 `drop trigger`. 사실 카드 경로가 카드 행과 판 1 을 **명시적으로** 만들게 바꾼다(지금은 트리거가 판 1 을 만들고 W3a 가 블록을 단다 — `fact_cards.py:517` 주변).
- **점주 답변 옛 경로:** F7 함수, `create_owner_answer_card`, RAW 판 쓰기(`knowledge_apply.py:272·505`) 삭제 → A-D3 로 대체.
- **데모 시드 F15:** 카드 없이 매장·계정·카테고리·근무조·질문만. 데모 카드는 자료 업로드로 만든다(시연 절차에 적는다).

### A-D3 점주 답변 → 사실 → 카드
1. W worker 가 `OWNER_ANSWER_SUBMITTED` 를 받으면 질문·답변으로 `OWNER_TEXT` 자료(W3b 의 파일 없는 자료 종류)를 만들고 `owner_answer_id` 와 잇는다(기존 `fact_owner_answer_links` 재사용 여부는 계획에서 확인).
2. 그 자료를 업로드와 **같은 파이프라인**으로 처리한다: 사실 추출 → 원장 → 대상 연결 → 사실 조립. **Phase A 에서는 지금 추출 로직에 "점주 답변" 문맥(질문 문장)을 더해 부른다.** 질문 문장은 맥락일 뿐 사실로 저장하지 않는다. Phase B 가 이 지점을 라우터 뒤로 옮기고, 점주 답변 **첨부 파일**(Phase B B-U15)도 이 경로에 붙인다. Phase A 는 답변 글만 다룬다.
3. 결과:
   - **새 대상** → 새 사실 카드 → **자동 공개**(지금의 NEW 자동 공개와 같음, 순환을 빨리 닫는다).
   - **공개된 카드의 대상** → A-D4 "기존 카드 새 초안 + 검수 대기". 점주 승인은 R 라우터가 부르는 `approve_owner_proposal(...)` 모양을 유지하고 안쪽을 새 초안 승인으로 바꾼다.
   - **사실 0개**(잡담·인사) → 검수 대기, R 에 돌려주는 결과는 `ApplyOwnerAnswerResult` 계약 그대로.
4. W 는 R `knowledge_loop.build_knowledge_plan` 을 더 부르지 않는다(R 인계).
5. 원가: 답변마다 추출 1회 + 조립 1회(짧은 글). 원장 문맥 `OWNER_ANSWER`.

### A-D4 공개 카드 대상에 새 사실이 붙을 때 (F8)
- `EXISTING_CARD` 보류 대신: 카드가 **공개됐고 점주가 고치던 초안이 없으면**(초안 판 = 공개 판) 그 카드의 **새 초안 판**(기존 사실 + 새 사실, 서버 렌더링)을 만들고 검수 대기로 둔다. 공개판은 승인 전까지 그대로.
- 점주 초안이 따로 있거나 `MANUAL` 배정 카드(불변식 12)는 지금처럼 `EXISTING_CARD` 보류.
- 완료 알림·작업 문구: "새 카드 N장" → "카드 N장에 반영"(F9). `card_count` 의미 = "이 자료가 이어진 카드 수".

### A-D5 1회 삭제 migration
- 파일 `supabase/migrations/YYYYMMDDHHMMSS_w_wipe_knowledge_once.sql`. migration 은 버전당 한 번만 적용된다. 빈 DB(로컬 `db reset`)에서 다시 돌아도 지울 것이 없어 무해하다.
- 한 트랜잭션. 불변 트리거는 **이 트랜잭션 안에서만** 끄고 지운 뒤 다시 켠다(F12 순서).
- 지우는 순서(자식 먼저):
  1. `r_answer_citations`·`r_answer_receipts`·`message_citations`
  2. `knowledge_change_proposals`·`upload_change_proposal_facts`·`upload_change_proposals`·`card_fact_edits`
  3. `card_version_fact_provenance`·`card_block_facts`·`card_version_blocks`(F13 명시 삭제)·`raw_spans`
  4. `card_evidence`·`card_embeddings`·레거시 `facts`·`card_facts`·`card_review_events`·`checklist_cards`·`reclassification_results`
  5. 사실 원장: `fact_conflicts`·`fact_owner_answer_links`·`source_fact_revision_links`·`fact_occurrences`·`fact_revision_requires`·`fact_revision_meta` → `knowledge_facts.head_revision_id` null → `fact_revisions` → `knowledge_facts`·`knowledge_entity_candidates`·`knowledge_entity_events`·`knowledge_entity_aliases` → `knowledge_cards.entity_id` null → `knowledge_entities`
  6. `source_fact_occurrences`·`source_facts`
  7. 카드 포인터 null → `card_versions` → `knowledge_cards`
  8. 공개판·공개 포인터·색인 준비/문서(R): `knowledge_snapshots`(+`snapshot_card_versions`), `knowledge_publications`, `r_index_publications`·`r_index_preparations`·`r_index_documents`, 지워진 공개판을 가리키는 공개 멱등 기록(`r-initial-empty` 포함)
  9. `ingest_job_sources`·`ingest_jobs`·형식별 자료 표·`source_frames`·`sources`
  10. `checklist_checks`·`checklist_check_events`(지워진 판을 가리킴). `checklist_submissions` 는 남긴다
- 리셋: `stores.guide_completed_at = null`.
- 남기는 것: A-U6. `owner_answers.card_id`·`roadmap_items.card_id`·`learning_progress` 의 카드 연결은 FK 가 SET NULL.
- 비용 원장(`ai_usage_attempts` 등)·원래 응답(`extraction_raw_responses`)은 지우지 않는다(삭제 차단 트리거, 보존 설계). 지운 자료를 가리키는 id 는 남는다(FK 없음).
- Storage 버킷 `sources` 파일은 SQL 로 못 지운다 → `api/scripts/wipe_storage_sources.py`(사용자 실행, 기본 `--dry-run`, 매장별 목록·삭제).
- 지운 뒤 첫 직원 질문 → R `ensure_initial_publication` 이 빈 공개판을 만든다(F11). 실제 DB 로 확인한다.
- 되돌리기는 배포 워크플로의 migration 직전 DB 백업뿐(F14). 절차서 첫 단계에서 백업 성공을 확인한다.

### A-D6 배포판 env
- **추가할 플래그 없음**(A-D1).
- 확인: `W_OWNER_ANSWER_WORKER_ENABLED=true`.
- 지워도 되는 줄(남아도 무시, F10): `W_ENTITY_REVISION_ENABLED`·`W_UPLOAD_PROPOSALS_ENABLED`·`W_FACT_ASSEMBLY_ENABLED`·`W_FACT_CARD_EDIT_ENABLED`·`W_OWNER_ANSWER_RAW_PUBLISH`.
- 절차서 `docs/dev/plan/FACT_ONLY_ROLLOUT.md`: 머지 → 배포(백업·migration·서버) → Storage 정리 스크립트 → 자료 재업로드 → 확인 항목.

### A-D7 R 인계 — `W_TO_R_PUBLICATION_HANDOFF_20260927.md` "R 이 할 일"
- W 는 더 이상 RAW 블록을 공개하지 않는다 → R 렌더러·색인·계약의 RAW 처리 제거 가능(계약 변경은 R 결정).
- W 는 `knowledge_loop.build_knowledge_plan` 을 부르지 않는다.
- 1회 삭제가 R 표(답변 인용·영수증·공개판·색인)를 비웠다.
- 점주 답변 근거가 `OWNER_TEXT` 자료 occurrence 로 온다 → "점주 답변/직접 입력" 표시(기존 11-a 와 합침).

## 5. 검증 (유료 호출 0)
- 단위: 플래그 제거 후 전체 통과, 공개가 블록 없는 판을 거절, 점주 답변 worker(합성 모델 대역) NEW 자동 공개·기존 카드 검수 대기·사실 0개, A-D4 새 초안.
- 실제 DB(재구축 검증에 시나리오 추가):
  - (a) 데이터가 찬 DB 에 삭제 migration → 남길 표 행 수 불변·지울 표 0 → 첫 질문 이관이 빈 공개판으로 동작
  - (b) 점주 답변 → 사실 카드 → 자동 공개 → R 답변이 그 사실을 인용
  - (c) 공개 카드에 새 자료 → 새 초안 → 승인 → 공개 전환
  - (d) 트리거 제거 후 모든 카드 생성 경로에 판 1 존재
- web: `pnpm check`, 저장소 스킬 2개, 합성 API Playwright(카드 화면에서 자유 편집 사라짐).
- 격리 검사, R 소유 파일 무수정 확인.

## 6. 범위 밖
분류기·라우터, 체크리스트 카드 단위(→ Phase B), 보류만 보는 화면, 대상 분리 뒤 영구 보류, R 쪽 RAW 코드 삭제, 추출 품질 실측.

## 7. 위험
| 위험 | 대응 |
|---|---|
| 삭제 migration 은 되돌릴 수 없다 | 배포 백업 확인을 절차서 첫 단계로. 로컬에서 데이터 찬 DB 로 리허설(시나리오 a) |
| W migration 이 R 표를 지운다(소유 경계) | 사용자 결정 A-U5. 인계 문서에 명시, R 표 구조는 바꾸지 않는다 |
| 트리거 제거 후 판 생성 누락 | 시나리오 (d) |
| **A 만 배포하면 체크리스트가 사실 카드 본문을 줄로 잘라 지저분하다** | 삭제로 체크리스트 연결이 비므로 점주가 다시 연결하기 전엔 영향 없음. **B 를 머지한 뒤 체크리스트를 다시 연결**하도록 절차서에 적는다(또는 A·B 를 같이 배포) |
| 점주 답변 순환 지연(추출+조립 2회) | 답변이 짧아 각 1회. 실제 지연은 배포 후 확인 항목 |
