# W 재시도 보완 검증 — 2026-09-26

## 변경

W 원본 수정 `ef51787` 위에서 [보완 검토](W_FIX_REVIEW_20260926.md)의 N01~N03을 수정했다. 기존 F01~F03 수정도 이 브랜치에 포함한다. 과거 감사 문서는 당시 관찰로 보존한다.

- **N01 조립 실패:** 제품 조립 예외와 사실이 있는데 카드가 없는 결과는 실패로 처리한다. `ingest_job_sources.recovery_state`에 EXTRACTED 사실·원장 ID·추출 결과를 보존한다. 재시도는 같은 입력을 확인하고 저장된 사실로 조립만 다시 수행한다. 기존 카드 수를 이번 조립 성공의 근거로 쓰지 않는다. 미리보기의 unresolved 반환은 유지한다.
- **N02 구간 식별:** 실제 전처리 텍스트·구간 순서/내용·첨부 파일 바이트·분할/프레임/PDF 입력 설정의 SHA-256을 보존해 비교한다. 같은 구간 개수여도 내용·첨부·설정이 다르면 재추출을 거절한다. 이전 manifest가 없는 PARTIAL 자료에도 추정 재시도를 하지 않는다.
- **N03 원자 저장:** 카드 저장·실패 구간 갱신·복구 상태 COMMITTED·source DONE을 한 짧은 transaction으로 확정한다. 중간 장애는 모두 rollback한다. 복구본 CAS는 stale 저장을 거절하고 이미 완료한 작업의 재호출은 카드를 추가하지 않는다. 외부 호출은 DB 연결 밖에서 실행한다.
- COMMITTED에는 지문·미해결 구간 정보만 남기고 조립 완료한 assertion 복제/ledger ID 목록을 비운다. 복구본은 내부 작업 데이터이며 검색 응답/공개 지식으로 제공하지 않는다.

## 검증

- 전체 단위 **944 passed, 4 xfailed, 119 subtests passed**. xfailed는 기존 legacy 의미 취약성 격리 사례다.
- 이번 변경 파일 4개(pipeline/recovery/job_worker/job_repository) 매장 격리 AST 검사 **위반 0건**. ingest 전체 검사는 기존 `repository.py`의 store_id 없는 함수 15건을 보고한다. 이 PR에서 그 파일을 수정하거나 포괄 면제하지 않았으며 전체 폴더 위반 0건으로 보고하지 않는다.
- 일회용 PostgreSQL 17 기반 **30개 migration 재구축 및 전체 R handoff runner 통과**. 운영 `.env` DB를 사용하지 않았다.
- 새 실제 DB 회귀를 schema rebuild runner에 연결했다. 기존 R fixture가 먼저 실행되고, W 검증은 이후 별도 합성 매장을 사용한다.
- 새 DB 검증: 타 매장 복구본 접근 거절, 단일 연결 풀의 외부 호출 중 receipt 연결 획득, 기존 PARTIAL/manifest 없음 차단, 동일 개수 내용 변경 차단, 재추출 성공 후 조립 실패 보존, 카드 저장 뒤 장애의 rollback, FAILED 재접수 시 복구본 보존, 재추출 없이 조립 복구, 카드/사실 중복 없음, 완료 재호출 no-op, stale CAS와 잘못된 recovery shape 거절.
- Web 수정은 W 원본 커밋에 포함된 PARTIAL 표시/버튼이다. 해당 커밋에서 `pnpm check`(lint/typecheck/production build)를 통과했다. 이번 보완에서 Web을 추가 수정하지 않았다. 원격 PR CI는 별도 결과로 확인한다.
- 로컬 DB 로그: Git 제외 `api/tmp/w-recovery-db-final-20260926.log`. 합성 provider 예외는 의도한 장애 주입이다.

## 배포 순서와 제한

1. **migration `20260926090000_w_ingest_recovery.sql` 먼저**, 다음 API/worker 코드, 다음 W PARTIAL UI. 이 작업에서 운영 migration이나 배포를 실행하지 않는다.
2. 운영 중 구버전 worker와 새 worker가 같은 작업을 동시에 처리하지 않도록 실행 중 작업을 정리하고 전환한다. 구버전은 새 복구본 의미를 모르므로 조립 대기 작업을 구버전으로 재처리하지 않는다.
3. migration 이전 PARTIAL 자료는 검증 가능한 입력 지문이 없다. 자동 부분 재시도는 보류한다. 원본·기존 카드 대조 후 별도 복구 절차를 정해야 하며 임의 hash backfill/전체 재추출로 중복을 만들지 않는다.
4. job 없는 legacy 처리와 EVALUATION 실행은 제품 작업 복구본을 재사용하지 않는다. 새 모델 실험을 이전 실행 결과로 대신하지 않는다.
5. 영속 worker/lease/프로세스 재시작 후 작업 회수 전체 구현은 여전히 J2 범위다. 이번 카드/복구 상태 원자성과 영속 worker 완료를 혼동하지 않는다.
6. 전체 segment occurrence·불변 revision·CardPlan·실제 snapshot 발행/OWNER_ANSWER worker는 W 후속 과제다. 이 변경은 그 전체 구현이나 실제 의미 품질 인수가 아니다.

## 다음 순서

PR의 unit/DB/browser CI 확인 후 검토한다. W/R은 카드별 revision 매핑, 변경 카드와 전체 manifest, 공개 transaction의 activate/finish·rollback 규칙을 확정할 수 있다. 이후 W 실제 생산/발행/worker를 연결하고 R이 종단/복구를 검증한다. 사람 정답·AI 판정 인정 방식·유료 평가 예산은 기존 회의 대기를 유지한다.
