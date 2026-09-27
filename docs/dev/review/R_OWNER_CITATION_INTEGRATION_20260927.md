# R 점주 답변 출처·W 승인 통합 검증 — 2026-09-27

기준: `b22be50`(PR #24) + 이전 REVIEW 완료 로컬 변경. [이전 기록](R_OWNER_REVIEW_HANDOFF_20260927.md)의 Docker 미실행 상태 이후, 사용자가 Docker를 켠 뒤 검증·후속 구현을 진행했다. 이전 관찰 기록은 유지한다.

## 변경

- `Citation`에 nullable `source_id`와 `owner_answer_id`를 두고 정확히 한 출처를 요구한다. 점주 답변 출처는 RAW 인용만 허용한다. 기존 파일 인용 입력은 그대로 수용한다. `chat_response.json`은 생성 도구로 갱신했다.
- 승인 렌더러·합성 렌더러가 점주 답변 ID를 보존한다. 저장·재시도·이력 overlay에서 `int(None)`을 피하며, 파일 삭제 상태를 점주 답변에 적용하지 않는다. 점주 답변 원문은 RAW/FK로 보존되므로 AVAILABLE이다.
- `20260927140000_r_owner_answer_citations.sql`: 인용 원장의 파일 ID NOT NULL 해제, 점주 답변 ID 추가, 출처 XOR 및 RAW 제약, `(store_id, raw_span_id, owner_answer_id)` 복합 FK 추가. 다른 매장·다른 원문 출처를 단순 답변 ID로 바꿔 저장할 수 없다.
- 근거 상세 조회가 점주 답변 ID와 보존된 승인 원문을 반환하고, 직원 화면은 `출처: 점주 답변 · 승인된 내용`을 표시한다. 기존 TanStack Query와 매장/사용자/receipt/order 캐시 키를 유지했다.
- W DB 검증의 가짜 notify callback을 실제 `finish_owner_review` 호출로 교체했다. SUPPLEMENT·NEW의 나중 승인이 실제 R PUBLISHED 상태로 이어진다.
- W가 생산한 새 공개 카드를 검색한 뒤 R의 답변 저장·멱등 재조회·출처 조회·DB 위조 거절을 검사한다. 임베딩·관계 분석·질문 적합성 판정은 합성 대역이다. 실제 모델의 답변 품질 인수로 해석하지 않는다.

## 실행 결과

| 검사 | 결과 |
|---|---|
| 전체 단위 | 1,110 passed / 4 xfailed / 131 subtests passed |
| 합성 렌더러 마지막 보완 후 관련 회귀 | 55 passed / 24 subtests passed |
| schema / fixture | 15개 / 3개 최신 |
| API 매장 격리 AST | `api/app/learn` 31파일 위반 0 |
| 웹 `pnpm check` | route typegen, lint, typecheck, production build 통과 |
| 실제 브라우저 합성 API 검사 | UI 42개, 이력 36개 통과. 점주 출처 라벨·새로고침 복원 포함 |
| PostgreSQL 17 격리 재구축 | migration 33개 적용, M2 44개, RERANK 14개, M3 저장 20개, v2 API 157개, 점주 전달 60개, 보존 13개 통과 |
| W/R 연결 | W 공개 65개 및 점주 인용 8개 통과. 실제 W 공개 hook의 R 알림 실패가 공개 포인터·snapshot·제안·R 상태를 함께 rollback하는 반례 포함 |

Docker 컨테이너는 runner가 임의 이름으로 loopback `55439`에 생성하고 실행 후 정리했다. 실제 `.env` DB와 유료 공급자는 사용하지 않았다. 첫 추가 인용 DB 실행은 타 매장 접근의 정상 HTTPException(403)을 테스트가 받지 못해 중단됐다. 기대 예외 처리를 수정한 재실행은 통과했다.

명령(저장소 루트):

```powershell
.\api\scripts\verify_r_handoff.ps1 -Python .\api\.venv\Scripts\python.exe -IncludeSchemaRebuild
Push-Location api
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short -p no:cacheprovider --basetemp=tmp/r-owner-citations-next-run
.\.venv\Scripts\python.exe scripts/export_contract_schemas.py --check
.\.venv\Scripts\python.exe scripts/build_contract_fixtures.py --check
Pop-Location
pnpm --dir web check
# web production server :3011 + bundled Playwright NODE_PATH에서
node api/scripts/verify_r_ui.cjs
node api/scripts/verify_r_history_ui.cjs
```

브라우저는 390×844·360×800에서 기존 오류·재시도·이동·입력 보존·하단 버튼·가로 넘침을 검사했다. UI 데이터는 합성 API이며 PostgreSQL 실행과 별개다. 클라우드 CI는 실행하지 않았다. 최종 DB 로그는 `api/tmp/r-owner-citations-atomic-final.log`, UI 결과는 `api/tmp/r-ui/`에 있으며 Git 제외다.

## 배포·호환·남은 작업

1. 새 migration을 **API 배포 전에** 적용해야 한다. 새 API는 파일 인용에도 새 nullable 컬럼을 사용한다. 기존 코드의 파일 인용 쓰기는 migration 이후에도 유효하다.
2. API·근거 UI 배포 및 검증 후 `W_OWNER_ANSWER_RAW_PUBLISH` 활성화를 검토한다. 이번 작업은 운영 설정과 두 W 플래그를 변경하지 않았다. 구형 strict DTO 소비자는 nullable 출처를 받지 못하므로 새 출처를 보내기 전에 함께 갱신해야 한다.
3. REVIEW 완료와 출처 소비의 합성 연결은 확인했지만 모든 공동 PUB/OWN 반례·운영 인수가 끝난 것은 아니다. 특히 레거시 제안 원장 이관, 이미 PUBLISHED인 과거 미연결 제안 복구는 남는다.
4. 다음 R 작업은 점주 답변 후보 검색을 새 공개 색인으로 이전하는 것이다. 이후 W가 옛 `card_embeddings` 호환 쓰기를 제거할 수 있다.
5. 공동 결정은 카드별 매핑 DTO, 빈 manifest/마지막 카드 제외, 제외·복원 best-effort, 전체 재임베딩 비용·재사용 정책이다. W의 점주 편집본 출처 보존과 레거시 `/ingest/cards/*` 정리도 남아 있다.

변경은 로컬 작업 트리다. 커밋·push·운영 배포는 하지 않았다.
