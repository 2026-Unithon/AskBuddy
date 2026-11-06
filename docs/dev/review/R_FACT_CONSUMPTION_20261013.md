# P2 사실 카드 소비·OWNER_TEXT 출처 — 2026-10-13

기준은 main `770659b`에 P1 및 기존 R 로컬 변경을 보존한 작업 트리다. P2 구현은 미커밋 상태이며 운영 배포·운영 DB 변경·유료 모델 평가를 실행하지 않았다.

## 구현

- R은 공개 snapshot의 사실 `subject`와 `entity_id`로 대상을 찾는다. `2/3` 같은 카드 분할 번호를 대상 이름으로 요구하지 않는다. 별칭은 명시적 선택을 거치며 이름 부분문자열로 대상을 확정하지 않는다.
- lexical/vector와 같은 repeatable-read 트랜잭션에서 같은 대상의 공개 블록을 회수한다. 현재 승인 포인터·매장·prepared index 범위를 모두 적용한다. 보충 후보에는 검색 점수를 만들어 넣지 않는다. 재정렬 계약에 맞춰 전체 보충 조회가 100개를 넘으면 확장하지 않고 기존의 근거 부족 판정을 유지한다.
- 선행 사실을 블록 간 의존 순서로 배치하고, 블록 내부의 승인 순서를 지킨다. HOT/ICE·크기·조건·예외 검증은 유지한다. 부족한 선행·규격·충돌 사실은 답변으로 통과시키지 않는다.
- 새 W 공개판은 `r-approved/v2`로 저장한다. 대상/규격 머리줄의 중복을 줄이고 승인 문장·조건·예외는 그대로 싣는다. v1 렌더링과 저장된 과거 응답은 보존한다.
- 인용 상세에 `source_type`, `source_kind`, `related_owner_answer_id`, `source_locations`를 추가했다. `owner_answer_sources`의 같은 매장 연결이 있으면 **점주 답변**, 직접 편집 OWNER_TEXT면 **사장님 직접 입력**으로 표시한다. 파일 종류·알 수 없는 종류도 구분한다. 기존 `source_id XOR owner_answer_id`는 그대로다.
- 위치는 해당 인용의 불변 snapshot에서 읽는다. MESSAGE locator는 새 공개판 작성 시 기존 계약의 LINE으로 변환한다. 과거 snapshot/hash를 수정하지 않는다. 삭제 자료도 당시 승인 문장을 보여 주고 원본 열람 불가를 따로 표시한다.
- 완료 이력의 `knowledge_status`는 보존하며 `knowledge_availability`로 현재 공개 여부를 분리한다. 같은 판 CURRENT, 이후 판 CHANGED, 삭제/제외/제안 유실 UNAVAILABLE이다. 점주 상세와 직원 대화는 삭제된 카드를 현재 공개 완료로 표시하지 않는다. 제안 없는 REVIEW·닫힌 제안은 직원 이력을 영구 폴링하지 않는다. 적용된 초기화 migration은 수정하지 않았다.

## 검증 범위

`api/scripts/verify_r_fact_consumption.py`는 실제 W 원장→조립→편집→공개 서비스를 사용한다. 분할 상한만 테스트에서 작게 설정하고 외부 추출/임베딩을 합성 대역으로 바꾼다. snapshot을 손으로 만들어 생산 경로를 대신하지 않는다.

검증 항목: 분할 3장·순위 1개에서 동일 대상 회수, HOT/ICE, 대상/규격 명확화, 추가/정정/삭제/재정렬, 초안 미노출, 승인 후 새 판, 과거 인용과 OWNER_REMOVED, 직접 입력 줄 위치, 자료 tombstone, 실제 점주 답변 worker, 타 매장 404, 현재 공개/이후 변경 분리. 기존 W3b·R 조건/예외/회원 경계 검증도 유지한다.

초기화 리허설은 기존 `verify_w_fact_only.py`에 완료 이력의 UNAVAILABLE 표시, 남은 명확화 문맥의 사용자 선택 보존·추정 폐기, 빈 지식으로 답변 금지, 만료 lease 회수, 첫 점주 답변의 재공개를 추가했다. UUID 임시 DB에서만 기존 초기화 파일을 실행한다.

브라우저는 합성 API 응답으로 직원 질문 화면 및 기존 v2 알림 주소의 이동, 출처 구분, 삭제 자료, 오류/재시도/404, 인용이 지워진 옛 채팅, 점주 공개 이력의 재진입·새로고침을 검증한다. 모바일 기준은 390×844와 360×800이다. API/DB 실동작과 화면 상태 검증을 구분한다.

## 최종 결과

| 검사 | 결과 |
|---|---|
| `pytest tests -q -p no:cacheprovider` | **2,377 passed**, 6 skipped, 4 xfailed, 188 subtests passed. 기존 Starlette/AnyIO deprecation warning 1건 |
| `verify_r_schema_rebuild.py` | PostgreSQL 17.11, migration **50개**, W/R 전체 합성 통합·카카오 DB 6개·P1/P2·초기화 리허설 통과 |
| P2 독립 재검증 | 최종 후보 상한 100과 renderer v2로 실제 W→R **22개 검사 통과** |
| 매장 격리 AST 검사 | learn/reg/publish 58개 파일, 위반 0 |
| `pnpm check` | Next typegen·ESLint·TypeScript·프로덕션 build 통과 |
| 실제 Edge 모바일 | 8개 결과 그룹 통과, 390×844·360×800 가로 넘침 없음, 브라우저 runtime error 0 |

중간 실패도 구분한다. 초기에는 제안 없는 REVIEW의 영구 폴링을 기대하던 옛 테스트를 수정했다. 초기화 검사에 문맥 fixture를 추가한 뒤에는 보존 건수 기준도 fixture 생성 뒤에 측정하도록 고쳤다. 독립 W 초기화 검사는 전체 통합 fixture가 필요해 단독 실행 결과를 인수 근거로 쓰지 않았다. **최종 전체 재구축은 처음부터 끝까지 통과**했다. 브라우저 검사는 Next 개발 서버의 허용 호스트 `localhost`, 기존 v2 주소의 실제 리다이렉트, 공통 503 문구를 기준으로 바로잡았다.

최종 명령 결과와 화면 증거는 `output/r-fact-consumption-20261013/`에 보존한다. 임시 UUID DB는 runner가 삭제하고 검증용 컨테이너·웹 서버는 종료한다. 이 기록은 Phase A 소비 계약의 로컬 검증이며 P3 평가 입력 전환, P4 실제 모델 품질·지연, 운영 인수를 대신하지 않는다.
