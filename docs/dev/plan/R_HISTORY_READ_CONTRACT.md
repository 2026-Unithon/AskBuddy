# R v2 최신 대화·대기 상태 조회 계약

2026-09-21. R-F01/R-F02 수정에 추가한 하위 호환 조회 계약이다. W producer/worker 계약이나 답변 생성 정책은 변경하지 않는다.

## 요청과 페이지

`GET /learn/v2/sessions/{session_id}/history`는 JWT 매장과 현재 회원의 v2 세션만 허용한다.

| 요청 | 의미 | 다음 cursor |
|---|---|---|
| 인자 없음 또는 `after=<id>` | 기존 오름차순 조회 유지 | `next_after` |
| `latest=true` | 최신 메시지부터 최대 limit개 선택, 응답 안에서는 시간 순서대로 표시 | `next_before` |
| `latest=true&before=<id>` | 해당 ID 이전의 기록을 뒤에서부터 선택, 응답 안에서는 시간 순서대로 표시 | `next_before` |

- `limit`은 1~100, 기본 100이다. 서버가 limit+1개를 읽어 실제 다음 행 존재를 판정한다. 정확히 limit개라고 빈 페이지 cursor를 만들지 않는다.
- `latest=true`와 `after`의 조합, `latest` 없이 `before` 사용은 422다. 기존 EntityId 검증도 적용한다.
- 응답에 `messages`, `next_after`, `next_before`, `has_pending_updates`를 제공한다. 사용하지 않는 방향의 cursor는 null이다.
- 각 페이지의 메시지는 오름차순이다. 새 UI의 Query pages는 최신 페이지가 첫 번째이고, 표시는 페이지 순서만 뒤집어 전체를 과거→최신으로 연결한다. 페이지 안의 메시지 순서는 뒤집지 않는다.
- 최신 페이지가 항상 첫 페이지이므로 질문 성공·재진입·새로고침·포커스 복귀의 refetch가 최신 답변을 회수한다. 과거 페이지 존재 여부는 최신 명확화/안전 확인 버튼을 숨길 이유가 아니다.

## 세션 대기 요약

`has_pending_updates`는 현재 페이지가 아닌 해당 매장·회원·세션 전체를 대상으로 한다. 다음 중 하나가 있으면 true다.

1. 해당 세션의 receipt가 연결된 WAITING 질문.
2. 해당 세션에 전달된 최신 점주 답변 revision의 지식 상태가 PENDING 또는 REVIEW.
3. 해당 최신 revision이 FAILED지만 W_OWNER_ANSWER_V2 lease가 FAILED/CLAIMED이며 TERMINAL 실패가 아닌 경우.

PUBLISHED/LINKED, 종료된 실패, 새 revision으로 대체된 과거 답변의 PENDING은 대기 요약을 유지하지 않는다. REVIEW는 사람의 후속 검토가 남은 상태이므로 조회를 유지한다. 요약은 작업을 실행하거나 W 상태를 변경하지 않는다.

메시지와 요약은 동일한 repeatable-read transaction에서 조회한다. 메시지 조회 직후 점주 답변/지식 공개가 커밋되더라도 옛 메시지에 새 종료 요약을 붙여 폴링을 중단하지 않는다. 경합으로 DB가 serialization 실패를 반환하면 기존 v2의 재시도 가능한 STORAGE_FAILED 계약을 따른다.

UI는 최신 페이지의 서버 요약이 true일 때 TanStack Query의 5초 refetchInterval을 사용한다. 마지막 메시지의 action이나 클라이언트가 이미 로드한 과거 ESCALATE만으로 세션의 대기 상태를 추정하지 않는다. 모든 대기가 끝나면 interval을 중단한다.

## 배포와 검증

- **API 먼저, Web 다음** 순서로 반영한다. 기존 Web의 after 조회는 새 API에서 유지된다. 새 Web은 이 계약의 최신 조회·요약을 제공하는 API가 필요하다.
- DB migration은 추가하지 않는다. 기존 R receipt·revision·delivery·lease 테이블을 읽는다.
- 일반 의미 release의 source hash는 v2 router도 포함하므로, 해당 기능을 활성화한 환경에서는 기존 절차로 새 코드에 맞는 인수 artifact를 확인해야 한다. 이 수정으로 기능을 자동 활성화하거나 승인 hash를 자동 교체하지 않는다.
- 격리 DB/API 회귀: `api/scripts/verify_r_history.py`, 기존 전체 R DB runner에서 실행.
- 실제 화면+합성 API 회귀: `api/scripts/verify_r_history_ui.cjs`, 기존 UI 40개 검사와 함께 CI browser job에서 실행.
- 확인 범위: 99/100/101/200/201개 경계, 최신 선택/안전 확인, 모든 과거 기록 복원·중복 방지, 앞 페이지의 미해결 질문, 복수 pending, 재시도/종료 실패, revision 교체, 조회 중 상태 변경, 완료 후 갱신 종료.
