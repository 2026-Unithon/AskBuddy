# W 로드맵 — 사실→카드 단일 경로 · 입구 분류기 · 공지·매장 지식 · 로직별 추출기 (2026-10-10)

> **새 Claude Code 세션용 시작 문서.** 이 문서만 읽고 어느 단계든 시작할 수 있게 썼다. 단계마다 새 세션을 열어도 된다.
> 구현은 `superpowers:writing-plans` 로 계획을 쓴 뒤 `superpowers:subagent-driven-development`(권장)로 Task 단위로 진행한다.
> 앞선 W 계획(`W_NEXT_PLAN_20260928.md`)의 W1~W3b 는 끝났다(W3b = main `6d084a1`).

## 0. 세션 시작 절차

1. 저장소 루트 `CLAUDE.md` 를 읽는다. 이어서 이 문서 전체와 해당 단계의 설계 문서를 읽는다.
2. `git switch main && git pull --ff-only` 뒤 **같은 폴더에서** `git switch -c w/<단계-이름>` 으로 브랜치를 판다. 별도 worktree 폴더를 만들지 않는다.
   - 예외: 이 문서를 쓴 브랜치 `w/fact-only-cards` 가 아직 머지 전이면 그 위에서 Phase A 를 이어간다(사용자에게 확인).
3. 작업을 마치면 변경 요약과 브랜치 이름만 보고하고 멈춘다. **`git commit`·`git push` 를 하지 않고, 커밋할지 묻지도 않는다.** 사용자가 직접 PR 을 올리고 main 에 머지한다.
4. 사용자에게 보고는 한국어로, 쉬운 말로 한다. 사용자는 W(쓰기 파이프라인) 담당자다.
5. §4 "사람이 정할 것" 에 걸리면 추정하지 말고 `AskUserQuestion` 으로 묻는다.
6. 유료 모델 호출(`INGEST_MODE=real`, 외부 API)은 사용자 승인 없이 하지 않는다. 합성 대역으로 검증한다. 승인받아 실행하면 실행별·누적 토큰/USD 를 기록한다.

## 0-1. 사용자가 Phase A 전에 할 일

**구현 시작 전**
1. 브랜치 `w/fact-only-cards`(설계 문서·관찰 템플릿·R 인계 §13)를 커밋·PR·main 머지.
2. R 담당자에게 인계 문서 §13 과 R 이 할 일 12·13 을 전달. 특히:
   - 12-(d): v1 `/pending/{id}/answer` 가 W 가 지울 `publish_new_proposal`·`publish_existing_proposal`·`prepare_proposal` 에 기대는지 — **Phase A 의 삭제 과제 전에** 답이 필요하다.
   - 12-(a): W3-4 사실 블록 공개판 검토 — **Phase A 배포 전에** 끝나야 한다(구현은 병행 가능).
3. **Phase 0 — 외부 모델 관찰.** `추출결과/관찰/<로직>/<형식>/자료1/원본/` 에 자료를 넣고(점주답변 칸은 `지시문.md` 에 질문·답변 글도), Claude Code·Codex 어느 세션에서든 "`추출결과/관찰/README.md` 보고 시작해줘". 실행기 `api/scripts/run_observation.py` 가 칸마다 Opus 5.5·Sonnet 5.5·Sol 6.1·Luna 6.0 을 저장소 밖 격리 폴더에서 같은 지시문으로 돌리고 결과·감사를 채운다(구독 사용, 음성·영상 전사는 whisper-1 유료·승인 후). 로직마다 자료 1~2개. A 구현과 병행 가능(결과는 B 분류기 라벨 세트·D 추출기 근거).

**배포 전**(구현이 끝난 뒤, 절차서 `FACT_ONLY_ROLLOUT.md` 가 자세히 안내)
4. 배포 워크플로의 DB 백업 단계가 성공하는지 확인 — 1회 삭제 migration 의 유일한 되돌리기 수단.
5. 배포판 env 에 `W_OWNER_ANSWER_WORKER_ENABLED=true` 확인(점주 답변 순환). 지운 W 플래그 줄은 지워도 되고 남겨도 무시된다.
6. 배포 뒤 Storage 정리 스크립트 실행, 자료 재업로드. 체크리스트 재연결은 Phase B 머지 뒤.

## 1. 단계와 순서

| 순서 | 단계 | 한 줄 목표 | 설계 | 상태 |
|---|---|---|---|---|
| 0 | **Phase 0** 외부 모델 관찰 | 지시문 30개(로직 × 형식) × 4모델(Opus·Sonnet·Sol·Luna)을 실행기가 격리 환경에서 자동 실행(원본은 사용자가 넣음). A 이전에 시작, A~C 와 병행 가능 | `docs/dev/templates/extraction_observation/README.md`, 결과 폴더 `추출결과/관찰/README.md` | 준비 완료(지시문·폴더 2026-10-10). **사용자 실행 대기** |
| 1 | **Phase A** 레거시 제거 | RAW 를 만드는 W 경로 삭제, W 플래그 제거, 점주 답변→사실, 공개 카드 대상 새 사실→새 초안, 1회 삭제 migration | `W_PHASE_A_FACT_ONLY_DESIGN_20261010.md` | 설계 완료, **구현 계획부터** |
| 2 | **Phase B** 분류기·정규화기·체크리스트 | 입구 2곳(업로드·점주 답변) → 정규화기 훑기 → 분류 1회 → 본 추출. 새 확장자 avi·docx·hwp, 점주 답변 첨부, 사실 `ext`, 체크리스트 카드 단위, 분류기 테스트, 다수결 참조 일반화 | `W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md` | 설계 완료 |
| 3 | **Phase C** 공지·매장 지식 탭 | 공지사항(기간·회색·안 본 개수), 매장 지식 탭(맨 위 공지사항 + 카테고리 → 카드) | `W_PHASE_C_NOTICE_KNOWLEDGE_TAB_DESIGN_20261010.md` | 설계 완료(가정 2개 2026-10-10 확정) |
| 4 | **Phase D** 로직별 전용 추출기 | `PROCEDURE`·`POLICY`·`REFERENCE` 전용 추출기와 로직별 본 추출 깊이 | 관찰 분석(`docs/dev/review/OBSERVATION_<LOGIC>_*.md`)이 근거 | 관찰 결과 대기 |
| 5 | **Phase E** 역할별 모델 전환 | 감독·판단·일꾼 역할마다 비슷한 모델끼리 바꿔 쓰기: ① API 오류 시 다른 모델로 넘기기(장애 대비), ② 비용 효율 비교 실험(예: 일꾼 Flash ↔ Haiku 5.5, 판단 Sonnet ↔ Haiku 5.5)과 적용 | 이 문서 §2-1 | 설계 전 |

- A → B → C 는 순서대로. 각 단계는 앞 단계 위에 쌓는다.
- **배포 순서 주의:** A 만 배포하면 체크리스트가 사실 카드 본문을 줄로 잘라 보여 준다. A 의 1회 삭제로 체크리스트 연결이 비므로, **B 를 머지한 뒤 점주가 체크리스트를 다시 연결**한다(또는 A·B 를 같이 배포). A 절차서에 적는다.
- 관찰(0)은 사용자가 외부 앱에서 병행한다. 결과는 B 의 분류기 라벨 세트와 D 의 근거가 된다.
- E 는 D 와 독립이라 B 이후 언제든 시작할 수 있다(이미 있는 SCAN 파이프라인부터 적용 가능).

## 2. 이번에 정해진 것 (2026-10-10 사용자 결정 요약)

자세한 근거는 각 설계 문서 §2.
- **RAW 란** 사실로 쪼개지지 않은 글 덩어리를 카드 본문으로 공개하는 방식. 남기는 길은 "사실 → 서버 렌더링 → 사실 블록 공개" 하나.
- W 플래그 `w_entity_revision_enabled`·`w_upload_proposals_enabled`·`w_fact_assembly_enabled`·`w_fact_card_edit_enabled`·`w_owner_answer_raw_publish` 는 **없앤다**. 배포판 env 에 추가할 것은 없다(`W_OWNER_ANSWER_WORKER_ENABLED=true` 만 확인).
- 점주 답변은 **사실로 전환**한다. 점주 답변에도 **파일 첨부**가 가능하다(Phase B).
- R 소유 코드의 RAW 처리는 지우지 않고 **R 에 인계**한다(`W_TO_R_PUBLICATION_HANDOFF_20260927.md` §13, R 이 할 일 12·13).
- 기존 데이터는 **배포 때 1회 도는 migration** 으로 지운다: 지식 전부 + 업로드 자료 + 답변 인용 기록(R 표 포함). 질문·점주 답변·채팅 문장·비용 원장·매장·계정·카테고리·근무조는 남긴다.
- **분류 호출은 항상** 한다. 자료를 고르게 훑어 싸고 빠르게. 애매하면 **가장 가까운 로직**으로. 분류 결과는 개발용으로 기록. 분류기 테스트를 한다.
- 로직 6종: `RECIPE`·`PROCEDURE`·`POLICY`·`REFERENCE`·`NOTICE`·`NONE`. 확장자 × 로직을 곱하지 않는다: **확장자 → 정규화기(6) → 공통 중간 형식 → 로직 추출기**.
- 정규화기는 **가벼운 훑기 → 분류 → 로직에 맞는 본 추출** 순서(무거운 처리를 두 번 하지 않음, `NONE` 은 본 추출 안 함).
- 사실 형식 = **공통 핵심**(원장·조립·R 이 쓰는 칸, 그대로) + **로직별 속성 사전** + **로직별 `ext`**(원장에만, 공개 계약 밖).
- 체크리스트 항목 = **카드 하나(제목)**. 오늘 뜨는 카드는 근무조 연결 그대로. 연결 제안 없음. 항목을 누르면 카드 상세.
- 공지 자료의 **지식 변경은 카드**, **기간 있는 알림은 공지사항**. 공지 버튼은 마이페이지 버튼 왼쪽(안 본 개수), 매장 지식 탭 맨 위에 공지사항, 공지는 최신순·기간 끝나면 회색.
- 로직은 막 설계하지 않는다. **외부 모델 관찰 → 평균적인 처리 순서 → 추출기** 순서로 정한다.

### 2-1. 추출 구조 원칙 (2026-10-10 사용자 결정)
- **에이전트 완전 위임은 최대한 쓰지 않는다.** 서버에서 에이전트 세션(Managed Agents·코드 실행 도구)에 자료를 통째로 맡기는 방식은 가능하지만 자료당 비용(추정 2~5 USD, Opus)이 우리 파이프라인(실측 1.4~1.7 USD, 레시피북 스캔 참조 대비 85~92%)보다 높고 결과가 실행마다 흔들린다. 장기적으로는 **관찰 → 코드로 굳히기**(SCAN 방식)가 싸고 안정적이다. 에이전트는 굳히기 어려운 드문 형식에만 고려하는 보험으로 남긴다(기본 경로 아님).
- **역할 구조: 감독(코드, 흐름 고정) · 판단(중간 모델, 필요한 곳만) · 일꾼(싼 모델, 반복·병렬).** 모든 로직별 추출기는 이 모양으로 만든다(레시피북 SCAN 파이프라인이 기준: 코드 + Sonnet 판단 + Flash 전사·전개).
- **Phase E — 역할별 모델 전환.** 역할마다 비슷한 수준의 모델을 둘 이상 두고 바꿔 쓴다.
  1. **장애 대비:** API 오류(속도 제한·5xx·크레딧 소진 402·시간 초과)가 나면 같은 역할의 다음 모델로 넘긴다. 넘김은 원장(`ai_usage_attempts`)에 기록하고, 결과 비교가 가능하도록 어느 모델이 처리했는지 사실·구간에 남긴다.
  2. **비용 효율:** 같은 참조·같은 조건으로 역할별 후보를 비교(재현율·비용·지연, D17 반복 규칙)해 기본 모델을 정한다. 예: 일꾼 Gemini Flash ↔ Claude Haiku 5.5, 판단 Sonnet ↔ Haiku 5.5.
  - 모델명·순서는 `config.py` 역할별 목록. 유료 비교 실험은 사용자 승인 뒤.
  - 설계는 E 시작 때 쓴다(지금은 범위만).

## 3. 전 단계 공통 제약

저장소 `CLAUDE.md` 가 우선한다. 특히:
- **매장 격리**: 모든 DB 함수는 `store_id` 필수, `WHERE store_id = ...` 없는 조회 금지, store_id 는 JWT·worker 신뢰 범위. `api/app/`·`supabase/migrations/` 를 건드리면 저장소 스킬 `store-isolation-check` 를 쓴다. `api/app/ingest/repository.py` 의 기존 위반 15건 외 새 위반 0.
- **R 소유 파일은 수정하지 않는다**: `api/app/reg/*`, `api/app/learn/router.py`, `answering.py`, `answer_storage.py`, `owner_handoff.py`, `owner_publication.py`, `owner_delivery.py`, `approved_renderer.py`, `v2_router.py`, `knowledge_loop.py`, auth·notifications. 호출·import 만. R 이 바꿔야 할 것은 인계 문서 "R 이 할 일" 에 더한다. **Phase A 의 1회 삭제 migration 이 R 표의 행을 지우는 것은 사용자 결정**(표 구조는 바꾸지 않는다).
- **W 주 편집 파일**: `api/app/ingest/*`, `api/app/cards/*`, `api/app/learn/knowledge_apply.py`, `api/app/publish/*`, `api/app/checklist/*`(P5, 확인), `api/app/team/extraction.py`·`scoring_rules.py`, `api/prompts/*`(W 프롬프트), W 소유 migration, 관찰 템플릿.
- **공통 파일**(`api/app/config.py`, `api/app/main.py`, `api/app/contracts/*`, `api/scripts/verify_r_schema_rebuild.py`)은 가산 변경만(Phase A 의 플래그 제거는 사용자 결정에 따른 예외). `contracts/*` 는 바꾸지 않는다 — 필요하면 멈추고 사용자에게 알린다.
- **migration 은 가산형**만(Phase A 1회 삭제는 데이터 삭제 migration 으로 사용자 결정). 적용된 migration 파일을 고치지 않는다. 이름 `supabase/migrations/YYYYMMDDHHMMSS_w_<주제>.sql`.
- 이미 발행된 snapshot 의 hash 가 바뀌면 안 된다(Phase A 이후엔 1회 삭제로 옛 snapshot 이 없다).
- 모델명·임계값·상한은 `config.py`, 프롬프트는 `api/prompts/`, 주석은 한국어. LLM 호출마다 원장(`ai_usage_attempts`), 모델 호출 중 DB 연결을 쥐지 않는다(`ShortSession`).
- **평가용 실제 자료의 브랜드·상호·메뉴 고유명을 문서·주석·테스트·커밋 메시지 어디에도 쓰지 않는다.** 관찰 자료는 익명 id. 원본·외부 실행 결과는 Git 제외 `추출결과/`·`api/eval/data/`.
- `docs/release/` 는 요청 없이 읽거나 고치지 않는다. `docs/experience/` 는 사용자가 요청할 때만.

검증 명령(보고 전에 해당하는 것을 모두 돌리고 결과를 사실대로 적는다):

```bash
cd api && .venv/bin/python -m pytest -q tests          # 기준: 2176 passed, 6 skipped, 4 xfailed, 191 subtests (main 6d084a1 의 2156 + 관찰 템플릿·실행기 20)
docker run -d --rm --name askbuddy-w-verify -p 127.0.0.1:55439:5432 \
  -e POSTGRES_PASSWORD=synthetic-local-test -e POSTGRES_DB=usage_verify pgvector/pgvector:pg17
cd api && PYTHONPATH=. PYTHONUTF8=1 .venv/bin/python -B scripts/verify_r_schema_rebuild.py   # 실제 DB 전체 검증
docker stop askbuddy-w-verify
cd web && pnpm check                                     # web 을 건드렸을 때. 단위 테스트 러너 없음 — "테스트 통과" 라고 쓰지 않는다
python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards api/app/publish
```

화면 확인은 합성 API(Playwright 라우트 가로채기)로 한다. 실데이터·운영은 쓰지 않는다.

## 4. 사람이 정할 것 (만나면 멈추고 묻는다)

| 단계 | 결정 | 추천·현재 가정 |
|---|---|---|
| A | 1회 삭제 migration 배포 시점·백업 확인 | 절차서(`FACT_ONLY_ROLLOUT.md`, A 에서 작성)대로 사용자가 배포 |
| B | hwp 5.0 이진 파서(라이선스·컨테이너 크기·품질) | 계획 단계에서 비교표로 제시 |
| B | 같은 영업일에 카드가 재공개되면 체크가 풀리는 지금 규칙 유지 여부 | 유지(판 단위) — 확인 필요 |
| B | 점주 답변 화면 web 파일의 주 편집자(R 이면 첨부 UI 는 인계) | 계획 단계에서 확인 |
| B | 분류기 실제 모델 평가 실행·예산 | 사용자 승인 후 |
| C | 하단 탭 3개(오늘 할 일 / 레시피 / 매장 지식) | **확정(2026-10-10)** |
| C | 공지는 점주 승인 뒤 공개 | **확정(2026-10-10)** |
| C | 직원 화면 web 파일 주 편집자 | 계획 단계에서 확인 |
| D | 어떤 로직부터 전용 추출기를 만들지 | 관찰 분석 결과와 분류 기록(어떤 로직 자료가 많이 오는지)으로 |
| E | 역할별 후보 모델·넘김 순서·비교 실험 예산 | E 설계 때 |

## 5. 단계별 시작 방법

- **Phase A**: 설계 `W_PHASE_A_FACT_ONLY_DESIGN_20261010.md` 를 읽고 `superpowers:writing-plans` 로 `docs/dev/plan/W_PHASE_A_PLAN_<날짜>.md` 를 쓴다. 계획에 반드시 들어갈 것: 플래그 제거 범위, 트리거 제거와 카드 판 명시 생성, 점주 답변 worker 교체(R 함수 호출 제거, `approve_owner_proposal` 모양 유지), A-D4 새 초안, 1회 삭제 migration(지우는 순서·트리거 끄기, 데이터 찬 DB 리허설 시나리오), Storage 정리 스크립트, 데모 시드, 절차서, 인계 문서 갱신. 계획 승인 뒤 subagent-driven-development.
- **Phase B**: 설계 B 를 읽고 계획. 관찰 결과가 있으면 분류기 라벨 세트에 쓴다.
- **Phase C**: 설계 C 를 읽고 계획(§2 가정은 확정됨).
- **Phase E**: 이 문서 §2-1 을 읽고 E 설계 문서부터 쓴다(역할별 모델 목록·넘김 규칙·비교 실험 계획).
- **관찰 분석**: 사용자가 "`<LOGIC>` 관찰 분석해 줘" 라고 하면 `docs/dev/templates/extraction_observation/README.md` 의 "Claude Code 세션이 하는 순서" 를 따른다.

## 6. 관련 문서
- 설계: `W_PHASE_A_FACT_ONLY_DESIGN_20261010.md`, `W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md`, `W_PHASE_C_NOTICE_KNOWLEDGE_TAB_DESIGN_20261010.md`
- R 인계: `W_TO_R_PUBLICATION_HANDOFF_20260927.md` §13, R 이 할 일 12·13
- 관찰 템플릿: `docs/dev/templates/extraction_observation/`
- 앞선 계획·현황: `W_NEXT_PLAN_20260928.md`(W1~W3b), `docs/dev/DEV_TODO_CURRENT.md`, `docs/dev/review/WR_CARD_EDIT_FACT_REVIEW_20261005.md`
- 예전 관찰·참조: `W_REFERENCE_EXTRACTION_20260920.md`, `W_SCAN_LAYOUT_EXTRACTION_DESIGN.md`, `docs/dev/review/W_EXTRACTION_DIAGNOSIS_20261005.md`
