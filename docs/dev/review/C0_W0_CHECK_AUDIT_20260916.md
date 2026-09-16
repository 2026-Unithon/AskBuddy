# C0·W0 완료 체크 감사

2026-09-16 · 요청: 코드와 기존 review를 대조해 완료 항목을 체크하고 W의 선행 잔여 작업을 확인.

## 범위와 판정

현재 코드, C0/W0 검증 기록, W 측정 교정·표본 복구·v3·레거시 제거 기록을 대조했다.
TODO의 큰 항목을 계약/도구 구현과 제품 연결/실자료 인수로 나눴다.
`[x]`는 명시한 범위만 완료이고 `[~]`는 부분 완료다. C0/W0 전체 완료를 선언하지 않는다.
기존 review는 당시 증거이므로 수정하지 않았다. 운영 DB/Storage 조회·변경, 유료 호출,
holdout C/D 내용 열람, 카드 재생성, 커밋/푸시는 수행하지 않았다.

## 완료 근거

| 항목 | 현재 코드·산출물 | 검증 근거 |
|---|---|---|
| C0 계약·참조·hash·RAW·occurrence | `api/app/contracts/`, `api/schema/`, `test_contracts*`, `test_wr_answer_boundary.py` | 이번 probe 19 PASS / GAP 0 / ERROR 0, schema 15개 최신 |
| C0 합성 생산자/소비자 | `api/tests/fixtures/contracts/v1/`, `test_fixtures_cp03.py`, `api/app/fakes/` | fixture 3개 최신, 전체 회귀 포함; 실제 모델 품질 아님 |
| C0 W DB 기반 | M0/M1 migration, `api/app/publish/service.py` | MVP §22-5와 TODO의 과거 DB 12/12·17 migration 재구축 기록. 이번에는 DB 재실행하지 않음 |
| C0 호출 계측 | `usage/recorder.py`, Gemini/STT, `reg/embeddings.py::recorded_embeddings`, `learn/answering.py`, team runner/읽기 집계 | R 순차 검증, W 측정 교정 기록, 현재 회귀 |
| W 임베딩 연결 수명·귀속 | `ingest/embed/service.py::prepare_embedding/card_usage_context`, 승인/수정/지식 제안 저장 경로 | W 교정 기록의 PG15 W 연결/CAS 6개·기존 R 29개·판정 migration 4개. 공급자 fake, pgvector 경계 mock |
| 원가 계산 도구 | `usage/report.py`, `scripts/cost_report.py`, `team/operating_cost.py` | 계산 도구 구현/회귀. 요율/환율·전체 관측을 가진 실자료 D21 PASS 아님 |
| W0 자료 감사·4형식·익명 관리 | `audit_truth.py`, W0 기준선 §1/3, Git 추적/제외 설정 | 과거 감사 278(dev 180/holdout 98), TEST 라벨, hash 보강·노출 0 기록. 이번 holdout 내용 재열람 없음 |
| W0 채점·반복·입력 보존 | `team/extraction.py`, `repeat_metrics.py`, `run_extract_eval.py`, `compare_runs.py`, `variance_report.py`, `rescore_extract_report.py` | W 교정·v3 기록, 현재 회귀. 새 리포트 입력 보존은 과거 입력 복구와 다름 |
| AI 표본/사용자 판정/조건부 재평가 | `prepare_w_review.py`, `annotate_w_review.py`, `api/eval/policies/w_user_confirmed_20260916.json` | 표본 68건 AI 대조·사용자 표시 8개·A run78/B run86 조건부 재평가. 독립 전체 사람 인수 아님 |

`git ls-files api/eval`에 실제 매장 원본·truth·reports는 없고
`git check-ignore api/eval/data/store-a api/eval/data/store-b api/eval/reports`가 제외를 확인했다.
공개 Git 이력 전체나 외부 데모/발표의 무노출을 새로 증명한 검사는 아니다.

## 남은 C0 — W가 챙길 것

1. **CP-00B/C 전체 원가 인수:** `categories/classifier.py`와 `learn/knowledge_loop.py`는
   현재 모델을 직접 호출하며 공통 durable receipt가 없다. CLASSIFY/RELATION 계측 연결과 모든 실제 호출의 누락 대조,
   다중 source/card 배치 기여 링크, 실제 Storage byte-time/전송과 매장 귀속,
   요율/환율·등록/추가자료/읽기 비용 통합. Storage 목록/bytes 수집만으로 월 비용 인수는 끝나지 않는다.
2. **CP-05:** W manifest와 R runner/지표를 연결해 D18 품질·필수 안전성·원가·지연 판정을
   함께 검증. `repeat_metrics`의 중앙값/안정성 산술 구현만으로 전체 gate가 완성된 것은 아니다.
3. **W/R 접점:** W의 실제 승인 snapshot 생산·규격 적용 범위 메타데이터,
   R PrepareIndex prepared_id/TTL/hash 소비, OWNER_ANSWER outbox→W revision/발행 왕복.
   C0 DTO는 완료, 제품 연결은 W2~W4/J0와 연동해 남음.
4. **D20 마무리:** 원본 파일 접근 해제·현재 source availability API/UI 통합.
   tombstone/보존 FK 검증은 완료; 삭제된 원본 접근까지 종료됐다는 증거는 없음.
5. **호환/전환:** 독립 W/R 플래그, legacy 승인 RAW 이관, 지원 조합별 검증과 교차 검토.
   담당/호환 설계는 확정됐지만 실제 전환 인수는 미완료.

M2 versioned index staging, M3 chat v2/session/context, R1~R5 본구현은 R 자체 몫이다.
공동 인수가 필요하다는 이유로 W의 단독 구현 작업으로 바꾸지 않는다.

## 남은 W0 — W가 챙길 것

1. 자료/업무/오류 유형의 세부 커버리지 표와 사람 정답 확정.
   네 입력 형식은 존재하지만 PDF/개별 이미지, 공지, 다중 자료, 충돌·조건·예외·순서 등
   전체 요구의 충족은 별도 확인해야 한다. 원본 음성 청취·영상 동작·적용 범위와 점주 확인도 남음.
2. 자동 확신/보류/PARTIAL 및 거짓 양성·음성의 독립 사람 검수.
   사용자 표시 8개 결정과 AI 68건 대조를 전체 인수로 확대하지 않는다.
3. 캠페인 강제 검증: 현재 `run_extract_eval.py`는 holdout에 옵션/캠페인 파일을 요구하고
   truth 읽기 전에 차단하지만, 캠페인을 JSON으로 읽고 hash를 남기는 수준이다.
   split/hash/후보 설정/반복 실행표/예산 검증·개봉 기록/lock·반복 설정 동결까지 완성해야 한다.
4. 과거 18개 유효 실행 중 16개 입력 복구와 같은 채점 기준 재평가.
   A/B 각 마지막 1개도 실행 당시 동결 원본이 아닌 조건부 보존 입력이다.
   백업이 없으면 과거 점수를 추정하지 않고 별도 승인/사전등록된 새 dev 기준선으로 전환한다.
5. 전 단계 원가 인수 뒤 교정 채점/라벨·입력 snapshot·프롬프트/schema/config를
   동결한 최소 3회+A/A 기준선. 과거 최초 실행 완료 체크는 유지하되 현재 기준선 인수와 구분한다.

즉시 선행은 원가 전체 인수 범위·평가 manifest/캠페인 검증과 사람 라벨 확인이다.
실제 발행 접점/D20/RAW 전환은 해당 W2~W4/J0 개발과 함께 닫으며,
모든 C0 제품 통합을 끝낼 때까지 W1 개발 전체를 멈추는 직렬 순서를 만들지 않는다.

## 이번 재검증

```text
api/.venv/bin/python -m pytest api/tests -q
434 passed, 80 subtests passed in 5.34s

api/.venv/bin/python api/scripts/audit_c0_contracts.py
PASS 19 / GAP 0 / ERROR 0

api/.venv/bin/python api/scripts/export_contract_schemas.py --check
export 15개 최신

api/.venv/bin/python api/scripts/build_contract_fixtures.py --check
fixture 3개 최신
```

문서 체크 변경만 수행했다. 이번 offline 회귀를 새 PG15/pgvector/제품 HTTP/E2E,
실제 Gemini/STT 품질·비용 또는 운영 인수로 보고하지 않는다.
