# REL-G2 조회·캐시·오류 정책

2026-09-16 · 적용 범위: 현재 Web Query와 공통 API client. 모델·추출·카드 의미는 변경하지 않는다.

## Query 정책

| 데이터 | key 범위 | fresh 시간 | 자동 갱신 | 이유 |
|---|---|---:|---|---|
| bootstrap·배지 | userId + storeId | 30초 | 하단 nav가 보일 때 30초 | 역할·매장 검증과 전역 배지를 한 요청으로 공유 |
| ingest 목록·상세 | storeId + jobId | 2초 | 활성 작업만 2초 | 장기 작업 복원과 완료 감지 |
| 업무 category 설정 | storeId | 5분 | focus/reconnect | 온보딩 중 드물게 변경 |
| 카드 목록·상세·제안 | storeId + filter/cardId | 15초 | focus/reconnect, mutation invalidate | 검수 결과는 즉시 무효화하고 탭 왕복은 캐시 재사용 |
| 상품 category·재분류 | storeId + jobId | 2초 | 활성 재분류만 2초 | 작업 상태 수렴 |
| 질문·답변대기 | storeId | 3초 | 화면에서 5초 | 점주 응답 대기 상태 |
| 알림 header·목록 | storeId | 10초 | 화면에서 15초 | 동일 observer는 Query cache 공유 |
| 직원·학습·roadmap | storeId + userId/itemId | 15~30초 | focus/reconnect, mutation invalidate | 사용자별 진행 상태 격리 |
| 채팅 | storeId + userId | 3초 | 화면에서 5초 | 다른 기기/응답 반영 |

모든 query는 기본적으로 focus와 reconnect 때 stale 여부를 다시 확인한다. 백그라운드 갱신 중 기존 데이터를 지우지 않는다.

## 전역 배지

- 하단 nav는 질문 목록, 카드 `pending`, 카드 `needs_review`, 제안 목록을 각각 조회하지 않는다.
- `/app/bootstrap`이 `waiting_questions`와 카드·제안 합산 `pending_cards`를 반환한다.
- 카드/제안/질문 mutation과 ingest 완료는 bootstrap key도 무효화한다.

## 오류 정책

공통 `ApiError`는 `kind`, HTTP `status`, 서버 `code`, `retryable`, `requestId`, `retryAfterMs`, `details`를 보존한다.

| 종류 | 처리 |
|---|---|
| 보호 API 401 | 한 번만 cache를 비우고 역할별 로그인으로 이동, 현재 URL을 `next`로 보존 |
| 403·404 | 존재 정보를 추가 노출하지 않고 화면별 접근 불가/없음 처리 |
| 409 | 현재 데이터 재조회 후 사용자가 다시 판단 |
| 422 | 서버 field detail을 보존하고 입력 화면에 표시 가능하게 유지 |
| 429 | `Retry-After`를 보존하고 최대 30초 범위에서 Query retry delay에 사용 |
| 503·504 | retryable로 분류, 입력과 기존 화면 유지 |
| timeout | HTTP와 구분, retryable |
| offline/network | 서로 구분, reconnect 때 stale query 재조회 |
| AbortSignal 취소 | `aborted`, 자동 재시도하지 않음 |

로그인 API의 401은 Authorization header가 없으므로 전역 세션 만료로 처리하지 않고 해당 폼 오류로 남긴다.
