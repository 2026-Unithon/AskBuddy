# R 회의 대기 분리와 검토 수입 준비

사용자는 2026-09-18에 실제 매장 질문 정답 확정과 유료 모델 평가를 대기시키고, 별도 할 일로 정리하도록 지시했다. 현재 의사결정 목록은 [R 회의 결정 대기](../plan/R_MEETING_DECISIONS_20260918.md)를 따른다. 사람 판정·유료 호출은 수행하지 않았다.

## 이번 구현

- `team/review_intake.py`: 승인 snapshot 준비 전 질문별 사람 판단을 수입한다. 미검토 문항을 그대로 남기고 기록 자체는 평가/제품 승격 권한을 갖지 않는다.
- queue/source hash, 명시적 기대 행동·조건/예외·판단 이유·검토자, 요청 멱등키, 예상 intake hash를 검사한다. 수정은 이전 결정과 연결한 새 revision이다.
- 기록된 event와 현재 판단 projection을 재대조한다. 같은 키의 다른 판단, stale 수정, 다른 질문/queue, 기록 없는 판단 변경을 거절한다.
- `record_r_review.py`: 매장 내부 파일만 읽고 revision 파일을 원자적으로 생성한다. 이미 존재하는 다른 revision 내용은 덮어쓰지 않는다. stdout에는 정답·원문 대신 집계/식별자만 남긴다.
- 이후 명시적인 fact/RAW 매핑이 갖춰지면 기존 `finalize_review`에 연결한다. 모든 질문 검토와 실제 승인 snapshot 검증은 여전히 필요하다.

## 검증

`test_r_review_intake.py`, `test_r_reviewed_manifest.py`: 26 passed. 부분 검토, 미판정 유지, 중복 요청, stale 수정, 정정 이력, 근거 매핑 누락, 권한 있는 검토 필드의 매핑 덮어쓰기, queue 변경, projection 불일치, 파일 중복/원자 저장을 검사했다. 실제 매장 판정을 생성하지 않았다.

W/release 기존 미커밋 변경은 이 작업에 포함하지 않았다. 이번 추가는 검토 도구와 문서이며 제품 API·DB schema·프런트 동작은 변경하지 않는다.
