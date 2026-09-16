# 페이지별 사용자 검토 현황

이 문서는 사용자가 페이지 하나씩 알려주는 불편을 현재 상태로 관리한다.
페이지별 의견을 전역 기반 문제와 구분하되 같은 원인이면 `REL-G*`에 연결한다.

## 기록 형식

```text
페이지/URL:
하려던 일:
불편했던 순간:
기대한 동작:
기기/화면 크기:
재현 빈도:
스크린샷/영상(있으면):
```

사용자는 자연어로 불편만 말해도 된다. 담당 구현자가 위 필드와 재현 조건을 정리한다.
사실 의미·AI 추출 판단이 필요한 경우 release에서 임의로 정책을 바꾸지 않고 docs/dev 항목에 연결한다.

## 공통 기반

| ID | 범위 | 상태 | 연결 |
|---|---|---|---|
| GLOBAL-01 | 진입/bootstrap/auth/mock 진실성 | 계획 완료·구현 대기 | REL-G1 |
| GLOBAL-02 | query/refetch/배지/오류 | 계획 완료·구현 대기 | REL-G2 |
| GLOBAL-03 | 버튼/입력/loading/error | 계획 완료·구현 대기 | REL-G3 |
| GLOBAL-04 | typography/layout/safe area | 계획 완료·구현 대기 | REL-G3 |
| GLOBAL-05 | 긴 job/DB 연결/복구/관측 | 계획 완료·구현 대기 | REL-G4 |

## 페이지 목록

| 영역 | 페이지 | 사용자 검토 | 코드 검토 | 구현 |
|---|---|---|---|---|
| 공통 | `/`, `/role`, 인증/진입 | 대기 | 전역 일부 | 대기 |
| 점주 | `/owner/upload`, `/owner/jobs/[jobId]` | 대기 | 초기 병목 관찰 | 대기 |
| 점주 | `/owner/cards`, `/owner/cards/[cardId]`, `/owner/cards/review` | 대기 | 전역 일부 | 대기 |
| 점주 | `/owner/questions`, `/owner/notifications` | 대기 | 전역 일부 | 대기 |
| 점주 | `/owner/categories`와 legacy/온보딩 화면 | 대기 | route 정리 필요 | 대기 |
| 직원 | `/staff/roadmap`, `/staff/items/[itemId]` | 대기 | 전역 일부 | 대기 |
| 직원 | `/staff/chat`, `/staff/faqs` | 대기 | 전역 일부 | 대기 |

페이지를 검토할 때 대표 행동, 첫/재방문, loading/empty/error/partial/success, 느린 응답,
뒤로가기/새로고침/재연결/연타, 360/390 모바일, 접근성을 함께 확인한다.

