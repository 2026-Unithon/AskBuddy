# 현재 기능 사용성 릴리스

2026-09-16 · 상태: 계획/초기 코드 조사 완료, 개선 구현·실사용 인수·배포는 미착수.

목표는 현재 구현된 기능을 제한된 실제 사용자가 혼자 사용할 수 있도록 안정화하는 것이다.
C0/W0~W5 전체 AI 구조 완성을 릴리스 목표로 확대하지 않는다. 반대로 미승인 공개·매장 격리·
오답 방지·원문/이력 보존 같은 필수 조건을 사용성 개선을 이유로 생략하지 않는다.

## 문서 구조

| 위치 | 역할 |
|---|---|
| [RELEASE_TODO_CURRENT.md](RELEASE_TODO_CURRENT.md) | 현재 상태·우선순위·담당·완료 체크 |
| [plan/USABILITY_RELEASE_PLAN.md](plan/USABILITY_RELEASE_PLAN.md) | 개선 범위·실행 순서·사용자 인수 기준 |
| [plan/BASELINE_AND_ACCEPTANCE.md](plan/BASELINE_AND_ACCEPTANCE.md) | 속도/품질/화면의 실제 측정 방법과 비교 기준 |
| [review/INITIAL_CODE_REVIEW_20260916.md](review/INITIAL_CODE_REVIEW_20260916.md) | 최초 코드 관찰과 아직 확인하지 않은 사항 |

`plan/`과 TODO는 진행에 맞춰 갱신한다. `review/`는 당시 관찰 기록이므로 수정하지 않고 새 기록을 추가한다.
제품·승인·보안 계약은 상위 [MVP 정본](../ASKBUDDY_MVP_CURRENT.md),
장기 개발은 [개발 TODO](../DEV_TODO_CURRENT.md)를 따른다. release는 별도 제품 정본이 아니다.
같은 결함을 양쪽에서 구현할 때 담당/코드/검증을 연결하고 중복 작업하지 않는다.

이번 작업은 문서 구조와 계획 작성이다. 운영 데이터 변경·실제 과금 호출·배포는 하지 않았다.

