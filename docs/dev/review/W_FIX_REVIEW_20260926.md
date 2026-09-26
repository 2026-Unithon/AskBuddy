# W 부분 실패·연결 보유 수정 검토 — 2026-09-26

## 판정

**W/R 인계 계약 검토는 병행 가능하지만, W 결함 수정을 완료로 닫고 바로 병합·종단 인수로 넘어가기는 이르다.** 기존 F01/F02/F03을 겨냥한 수정은 확인했다. 새 부분 재시도의 조립 실패·구간 식별·저장 경계에 보완이 필요하다.

## 가져온 코드와 검증

- `origin/main` pull 결과는 Already up to date, `cf4c96d`다.
- 수정은 별도 원격 `w/partial-and-connection-fix`의 `ef517870d05d2029185098db3e5115a9d338a5e3`에 있다. 해당 ref를 fetch하고 detached checkout에서 검토했다. 검토 후 main으로 복귀했다. main에 병합하지 않았다.
- 열린 PR 없음. 해당 W 브랜치 CI 실행도 조회되지 않았다. 현재 workflow push 필터는 main/codex/**이므로 이 브랜치는 PR 생성 후 CI를 확인해야 한다.
- 전체 API 단위: **941 passed, 4 xfailed, 119 subtests passed**. xfailed는 기존 legacy 의미 회귀이며 신규 실패가 아니다.
- `pnpm check`: lint, TypeScript, production build 통과. `git diff --check main` 통과.
- 이번에 실제 DB/브라우저 종단을 실행하지 않았다. 새 테스트의 DB/provider 대역 통과와 실제 인수를 구분한다. 운영 DB·유료 모델 호출 없음.

## 기존 결함 수정 확인

| 기존 결함 | 수정 확인 | 한계 |
|---|---|---|
| F01 PARTIAL 상세 응답 오류 | API 자료 상태에 PARTIAL 허용, 상세 partial 건수·Web 표시 추가 | 상세 함수 대역 회귀 통과. 실제 GET/화면 인수는 별도 |
| F02 성공 오집계/재시도 누락 | 집계에 PARTIAL 포함, retry 대상과 Web 버튼 추가, 실패 구간만 재추출·기존 카드 보존 | 아래 재시도 반례가 남음 |
| F03 외부 처리 중 연결 보유 | 다운로드·전처리·추출·조립을 acquire 밖으로 이동, checkpoint만 짧게 acquire | 단일 연결 대역 풀에서 receipt 진행 테스트 통과. 실제 작은 DB 풀 부하 검증은 별도 |

## 수정 요청

### N01 / P1 — 재추출 뒤 카드 조립이 실패해도 성공으로 전환

- 위치(검토 SHA 기준): `api/app/ingest/pipeline.py:719`의 `assemble_assertions`, `:198`의 실패 구간 갱신, `api/app/ingest/job_worker.py:163`의 SUCCEEDED 분기.
- 재현: 기존 카드 3개·실패 구간 seg2 → seg2 추출 성공 → `assemble_cards`가 예외. 실제 `assemble_assertions`는 예외를 빈 cards와 unresolved로 바꾼다. 실제 `process_source`는 추출 성공을 기준으로 실패 목록을 비우고 DONE으로 끝낸다. 그 결과를 받은 실제 worker는 기존 카드 3개가 있다는 이유로 SUCCEEDED로 기록한다.
- 합성 DB/provider 대역으로 확인: `source_status=DONE`, `failed_segments=[]`, `new_cards=0`, `unresolved=['조립 실패: synthetic assembly failure']`, worker 결과 `SUCCEEDED`.
- 영향: 복구 사실은 원장에 남지만 카드에는 반영되지 않았는데 작업이 완료되고 정상 재시도 대상에서도 빠진다.
- 필요한 수정: 추출 완료와 조립/카드 반영 완료를 분리하고 조립 실패를 명시적 보류/실패로 보존한다. 이미 저장한 원장을 재사용하여 조립만 복구할 수 있어야 한다. 기존 카드 수로 이번 복구 성공을 판단하지 않는다.
- 완료 기준: 부분 재시도 중 조립 오류→미완료 표시→재시도→기존 카드 중복 없이 복구를 실제 연결 테스트로 고정.

### N02 / P1 — 구간 수가 같으면 다른 내용도 동일 구간으로 인정

- 위치: `api/app/ingest/pipeline.py:244` `_same_layout`, 영상 전처리의 설정 기반 구간 재생성.
- 현재 검사는 전체 개수와 segN 번호 범위뿐이다. 이전 원본/구간 경계/내용 hash·분할 설정을 비교하지 않는다.
- 합성 직접 호출에서 세 구간의 내용을 모두 바꿔도 `expected_total=3`, `retry_segments=['seg2']`이면 true다. 영상 시간 창 설정이 바뀌어도 구간 개수는 같을 수 있으므로 같은 번호가 같은 시간 범위를 뜻하지 않는다.
- 영향: 이전에 실패한 내용은 빠뜨리고 이미 처리한 내용을 다시 뽑을 수 있다.
- 필요한 수정: 최초 시도의 원본·segment 경계/입력 hash·분할 설정을 고정해 재시도와 대조하거나 저장된 동일 segment를 재사용한다. 해당 증거가 없으면 구간 재시도를 명시적으로 보류한다.
- 완료 기준: 개수는 같고 내용/경계/설정만 다른 반례 차단, 동일 입력의 재시도 허용.

### N03 / P1 — 카드 커밋과 실패 구간 갱신 사이의 실패가 중복 재시도 가능

- 위치: `api/app/ingest/pipeline.py:160`~`:201`. `_persist` transaction이 종료된 뒤 `_record_segment_failures`와 DONE을 기록한다.
- 정적 경로 확인: 부분 재시도로 새 카드가 커밋된 직후 실패 구간 기록 저장에 오류가 나면 `_mark_failed`가 실행된다. worker는 PARTIAL과 이전 실패 구간을 보존하므로 다음 재시도가 같은 구간을 다시 추출·조립한다. `_persist`는 새 카드 insert이며 이 복구 시도에 대한 카드 멱등 키는 없다.
- 이 항목은 코드 경계로 확인했으며 실제 DB 장애를 주입해 중복 행을 재현한 결과는 아니다.
- 필요한 수정: 카드 반영·구간 처리 결과·source 완료를 같은 짧은 transaction으로 확정하거나, 카드 저장 멱등 키/단계 checkpoint로 부분 커밋 후 재개를 보장한다.
- 완료 기준: 카드 저장 직후 장애 주입→재시도에서 카드/원장 중복 없음, 성공 구간과 실패 상태 보존.

재현용 로컬 도구는 `api/tmp/audit_w_retry_20260926.py`이며 Git 제외 파일이다. 검토 SHA에서 실행했고 해당 브랜치의 테스트 대역을 재사용했다. N01/N02 재현과 N03 정적 검토를 구분한다.

## 다음 순서

1. **W:** N01~N03 보완 및 연결 회귀 추가, PR 생성 후 unit/DB/browser CI 확인. 기존 상태 수정은 되돌릴 필요가 없다.
2. **W+R, 병행 가능:** 카드별 expected revision, 변경 카드/전체 manifest, W 공개 transaction에서 R activate/finish 호출·실패 rollback 계약 확정.
3. **W:** 불변 revision·occurrence·참조 카드 생산을 구현한 뒤 실제 snapshot→R prepare→W 공개+R activate 연결. 기존 승인 카드 RAW 이관도 포함.
4. **W 구현/R 검토:** OWNER_ANSWER worker→지식화·검수/공개→R finish→FAQ·학습·알림·재질문 왕복. 실제 W 제품 호출자는 이번 브랜치에도 없다.
5. **공동:** 점주 1명/직원 2명 종단·중단/중복/역순/복구 검증. 실제 품질 평가는 검토 정답·실제 snapshot·예산 확정 이후다.

R은 지금 2의 계약 검토를 진행할 수 있다. W 수정 완료를 가정한 main 통합 인수는 1의 재검증 이후다. 사람 정답·외부 AI 판정 방식·유료 예산과 운영 로그 증거는 기존 별도 안건으로 유지한다.
