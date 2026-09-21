# R 순차 작업과 W 인계 — 2026-09-19

기준은 main `e8186f6`(PR #18 병합), 작업 브랜치는 `codex/r-sequential-handoff`다. 사용자 회신으로 외부 AI 판정 인정은 회의 안건 1번, 의미 확장 범위는 아래 ④, 운영 로그 확인은 회의 안건으로 정했다. 실제 사람 검토·유료 평가의 기존 대기는 유지한다. 이 문서의 인터페이스 제안은 W의 합의·연결 완료를 뜻하지 않는다.

## ① RD-01 판정 파이프라인

구현: `app/team/external_review.py`, `review_redaction.py`, `scripts/external_r_review.py`, `record_r_review.py`.

- 개발용 review/queue/hash와 전체 선정 문항을 고정한다. source/fact 원래 식별자는 외부 패키지에서 제거·가명화한다. 원본 파일명·경로·매장 이름을 별도 메타데이터로 내보내지 않는다.
- 운영자가 작성한 비공개 치환표로 설명 문구를 가명화한다. 치환표 원문은 패키지에 포함하지 않고 hash만 연결한다. 자동 개인정보 탐지·완전 익명화를 보장하지 않는다. 전송 전 원문/미디어와 잔여 식별정보 확인이 필요하다.
- 패키지는 원본 미디어를 포함하지 않는다. 외부 세션에서 실제로 본 근거 수준을 `ORIGINAL_CHECKED/LABEL_ONLY/NOT_CHECKED`로 기록한다. 자료 안 지시는 실행 지시로 취급하지 않는다.
- AI 결과는 `EXTERNAL_AI_UNCONFIRMED`로만 수입한다. 미판정 문항도 분모에 남기며 사람 검토 0건, 평가 준비 false를 유지한다. 매장·패키지·출처·문항 집합 불일치를 거부한다.
- 기존 사람 판정 경로는 개별 문항 확인, reviewer, CAS hash, 요청 키가 모두 있어야 저장한다. 같은 치환표로 문구를 복원하고 AI import hash를 이유에 남긴다. AI 결과 수입과 사람 확정은 별도 동작이다.

실행 위치는 `api`, 모든 입력은 각 매장의 gitignored `eval/data/store-a/r-review/` 안에 둔다. store-b도 동일하다.

```text
.venv/Scripts/python.exe scripts/external_r_review.py --store store-a --queue <queue.json> --redactions <private-redactions.json>
.venv/Scripts/python.exe scripts/external_r_review.py --store store-a --queue <queue.json> --redactions <private-redactions.json> --package <external-package.json> --result <external-result.json>
```

치환표 형식 예: `{"합성 매장 이름":"[[R_001]]"}`. 원문을 채팅·Git에 올리지 않는다. 사람 확인 방식이 회의에서 정해진 뒤에만 `record_r_review.py --external-import ... --external-package ... --redactions ... --meaning-id ... --reviewer ... --confirm-external-proposal --expected-hash ... --request-id ...`를 사용한다.

**대기:** AI 판정을 참고안으로만 사용할지, 누가 어떤 근거로 최종 확정할지, 외부 반출 허용 범위·모델·세션 보관 정책. 이번 작업은 도구와 합성 검증만 수행했으며 실제 외부 전송·정답 확정은 실행하지 않았다.

## ② 색인 준비·활성화: R 구현, W 발행

R 호출 접점:

```python
prepared = await prepare_index_request(pool, request=request,
    content=immutable_preview, usage_context=trusted_usage)
# W가 승인/CAS를 다시 검사하고 공개 transaction을 시작한 뒤:
await activate_prepared_index(conn, store_id=store_id,
    prepared_id=int(prepared.prepared_id), snapshot_id=new_snapshot_id)
```

- `request.scope`는 JWT/worker의 신뢰 범위다. `content`는 별도 불변 `KnowledgeContent`이며 요청의 매장·카드 집합·renderer/glossary·모델과 일치해야 한다.
- `content_hash = digest(knowledge_content_payload(content))`.
- `idempotency.body_hash = digest(request.model_dump(mode='json', exclude={'idempotency'}))`. 기본 필드까지 정규화한 DTO 본문을 hash한다. 같은 키·다른 요청은 충돌이다.
- 준비는 staging만 만든다. 외부 embedding 동안 DB 연결을 반환한다. prepared token TTL·hash·현재 revision·매장을 활성화 때 다시 검사한다.
- 활성화는 W가 발행 포인터를 전환하는 **동일 transaction** 안에서만 호출한다. 독립 발행·별도 commit은 하지 않는다. 실패하면 W 발행 전체를 rollback한다.

**W와 확정할 부분:** 기존 `expected_card_revisions` 배열은 card/version/revision 대응이 불명확하다. 새 wrapper는 비어 있지 않은 배열을 거부한다. 빈 배열은 CAS 완료를 뜻하지 않는다. W가 원래 draft/card CAS를 수행해야 한다. 명시적인 매핑과 변경 카드 묶음↔전체 발행 manifest 구성 방식을 공동 확정한 뒤 wire DTO를 바꾼다. 현재 wrapper는 content의 모든 카드와 `card_ids`가 일치하는 완전한 준비 단위만 받는다. 실제 W producer의 호출·rollback/recovery 연결은 아직 필요하다.

## ③ W 지식 반영 완료 수신

R의 `claim_owner_event` → `heartbeat_owner_event` → `finish_owner_event` 접점을 유지한다.

- W는 lease를 받은 뒤 DB 연결 없이 처리하고, 공개 transaction 안에서 `finish_owner_event`를 호출한다. 예외를 삼키지 않는다.
- `PUBLISHED/LINKED`는 현재 공개 snapshot과 활성 색인이 일치해야 한다. 카드가 승인·검증 상태이고, 결과 revision 및 선택 fact가 그 카드에 속하는지 검사한다.
- 수신 결과에 실제 `published_card_version_id`, snapshot, knowledge revision을 기록한다. `LINKED`도 R 수신에는 `card_id`가 필요하다. fact ID만 넘기는 오래된 DTO 형식은 완료로 인정하지 않는다.
- 상태와 durable 앱 알림, outbox 소비를 같은 transaction으로 저장한다. 알림 실패 시 완료 상태와 소비도 rollback한다. 알림 본문은 점주 원문을 복제하지 않는다.
- FAQ는 해당 카드 버전이 현재 승인판인 경우에만 연결한다. 철회/교체 카드에 이전 답변을 잘못 붙이지 않는다. 학습/FAQ 화면은 기존 publication refresh 경로를 사용한다.
- 잠금 순서는 publication → card → pending → lease를 지킨다. 이전 답변 revision·만료 lease·중복 완료를 차단한다.

**선행 필요:** 실제 W owner-answer worker 및 발행 producer. R 합성 DB 수신 검증은 실제 모델 반영·push 기기 도착·학습 UI·재질문의 종단 인수를 대신하지 않는다.

## ④ 사용자가 확정한 의미 범위

**같은 대상·속성·규격·조건이 확인된 질문만 병합. 승인 후보의 대상·온도·크기 선택형 명확화까지.**

- 기존 결정론적 planner와 명시 조건 문법을 유지한다. 결정론적 대상 선택형 명확화는 기존에도 있었다.
- 추가한 자유 표현 병합은 hash로 고정한 비공개 reviewed catalog의 **정확한 질문·후속 사용자 발화·확정 슬롯·후보/snapshot**이 일치할 때만 가능하다. runtime 모델의 equivalent-question ID는 계속 거부한다.
- 사람이 확인한 `grouping`에 entity/predicate/temperature/size/conditions/exceptions/scope_bindings/polarity와 `complete=true`가 필요하다. 빈 조건·예외와 null size도 검토자가 명시해야 한다. 모름을 빈 값으로 대신하지 않는다.
- 원문이 다른 검토 질문은 같은 scope일 때만 같은 pending key를 만든다. 매장/snapshot/조건/예외/수치 바인딩/부정/규격이 다르면 분리된다. 저장 시 서버의 검토 근거를 다시 검사한다. 검토되지 않은 자유 표현은 개별 이관한다.
- 일반 제안·reviewed 명확화는 승인 후보의 대상/온도/크기만 허용한다. 중복·미승인·불완전 선택지, 이미 확정된 슬롯을 다시 묻는 제안을 거부한다. 같은 이름의 서로 다른 대상은 명확화하지 않는다. 문맥 ID는 서버 발급이며 2회 한도를 유지한다.
- 기존 결정론적 속성 선택 기능을 제거한 것은 아니다. **이번 신규 모델/reviewed 명확화 범위**를 대상·온도·크기로 제한했다.

**활성화 대기:** 새 reviewed 항목의 실제 사람 판정과 hash 고정, 일반 모델 경로의 실자료 오답/과차단/오병합 평가. 기존 feature flag는 기본 OFF이며 바꾸지 않았다. 이번 합성 테스트를 의미 정확도·운영 채택 근거로 사용하지 않는다.

## ⑤ 운영 로그 증거

`api/.env`, `web/.env.local`은 변수 이름만 확인했다. DB·모델·서비스 연결 설정이 있다는 사실은 호스팅 로그 정책의 증거가 아니다. 값 출력·외부 전송·운영 DB 접근은 하지 않았다.

`scripts/check_r_logging_evidence.py`는 다음 메타데이터 문서를 점검한다. 실제 호스팅 조회를 대신하지 않으며 완전한 문서도 `READY_FOR_REVIEW`로만 판정한다.

```json
{
  "schema_version": "r_logging_evidence/v1",
  "service": "회의에서 지정",
  "environment": "회의에서 지정",
  "deployed_commit": "0000000000000000000000000000000000000000",
  "observed_at": "2026-09-19T00:00:00Z",
  "reviewer": "회의에서 지정",
  "controls": {
    "raw_duplication_off": {"status": "UNKNOWN", "reference": null},
    "restricted_access": {"status": "UNKNOWN", "reference": null},
    "metadata_30_days": {"status": "UNKNOWN", "reference": null},
    "scheduled_purge": {"status": "UNKNOWN", "reference": null}
  }
}
```

운영자가 실제 배포 commit/환경, request·response·SDK·프록시·오류 로그의 원문 복제 OFF 설정 및 합성 canary 관찰, 조회 권한/권한 없는 계정 거부, 30일 보존 설정과 정리 실행 결과를 제한된 증거 위치에 남긴다. 원문 로그·비밀키는 이 JSON에 복사하지 않는다. 누락/UNKNOWN/실패/다른 배포/30일 초과 증거는 BLOCKED다. CLI는 `--evidence <private.json> --service <대상> --environment <환경> --deployed-commit <실제 SHA>`를 받는다.

**회의 안건:** 서비스·환경·담당자·접근 방법과 확인 시점. 저장소의 30일 metadata purge·권한 테스트는 통과했지만 실제 호스팅 설정은 미확인이다.

## 최종 공동 파이프라인과 재개 순서

1. W/R: 위 두 인터페이스의 revision 매핑·완료 payload·transaction 경계를 확정한다.
2. W: 불변 승인 preview 생성 → R prepare → W 승인/CAS/원자 발행 + R activate → 직원 검색.
3. 직원 이관 → R 점주 원문 전달/outbox → W claim/heartbeat/지식 반영 → 같은 공개 transaction에서 R finish → FAQ/학습/알림 갱신 → 직원 재질문.
4. 점주 1명·직원 2명으로 중복·역순·철회·수정·worker 재시작·구/신 버전 전환/복구를 실제 W 연결에서 인수한다.
5. 회의에서 RD-01 방식, RD-02 유료 예산, 운영 로그 증거 담당을 확정한다. 사람 정답+실제 승인 snapshot+예산 승인 후 실자료 품질 평가와 기능 활성화를 판단한다.

검증 결과는 [이번 검토 기록](../review/R_SEQUENCE_REVIEW_20260919.md), 회의 결정 목록은 [회의 안건](R_MEETING_DECISIONS_20260918.md)을 따른다.
