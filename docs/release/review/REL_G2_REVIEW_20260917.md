# REL-G2 조회·오류 기반 구현 검증

2026-09-17 · 브랜치: `dev_mvp`

범위는 현재 Web의 조회·캐시·오류·인증 만료 처리다. `docs/dev`의 모델, 추출, 채점, fact/card 의미는 변경하지 않았다.

## 구현 결과

- 공통 API 오류에 HTTP 상태와 서버 오류 코드, 재시도 가능 여부, request ID, `Retry-After`, timeout/offline/network/사용자 취소 구분을 보존한다.
- Authorization이 포함된 보호 API의 401만 전역 세션 만료로 처리한다. Query cache와 로컬 인증 상태를 지우고 현재 경로를 `next`로 보존한다. 로그인 실패 401은 로그인 폼 오류로 남는다.
- Query별 freshness와 polling 주기를 명시했다. 기존 데이터를 유지한 채 background refetch하며, 재시도는 오류의 `retryable`과 `Retry-After`를 따른다.
- 점주 하단 navigation의 질문·카드·제안별 조회를 제거하고 `/app/bootstrap`의 배지 요약을 공유한다. `pending_cards`에는 검수 대기 카드와 지식 변경 제안을 합산한다.
- 질문 답변, 카드/제안 처리, ingest 완료 때 bootstrap만 정확히 무효화한다. mutation 성공 뒤 화면 이동이나 버튼 해제를 넓은 refetch가 막지 않도록 관련 갱신은 background에서 수행한다.
- 계정 토큰이 바뀌거나 로그아웃되면 Query cache를 비워 다른 계정의 캐시가 보이지 않게 한다.

정책 정본은 [QUERY_AND_ERROR_POLICY.md](../plan/QUERY_AND_ERROR_POLICY.md)다.

## 확인 결과

### 요청 수

production build에서 OWNER 로그인 후 `/owner/upload` 첫 진입을 API 로그로 비교했다.

| 구분 | 최초 진입의 고유 read endpoint |
|---|---:|
| 변경 전 | 7개: bootstrap, jobs, notifications, pending questions, pending cards, review cards, proposals |
| 변경 후 | 3개: bootstrap, jobs, notifications |

하단 navigation이 만들던 별도 배지용 endpoint 4개가 없어졌고, 고유 초기 read endpoint는 7개에서 3개로 줄었다. 개발 모드 Strict Mode의 중복 호출과 CORS preflight는 이 비교에서 제외했다.

업로드 → 질문 → 업로드 화면 왕복에서도 질문 화면의 질문/대기 조회와 stale한 작업 목록, 정해진 주기의 bootstrap/알림만 확인했다. 카드·제안 배지용 목록 요청은 다시 생기지 않았다.

### 오류와 인증 만료

- 실제 DB를 사용한 bootstrap 호출에서 잘못 참조한 테이블명을 500으로 발견했고 `knowledge_change_proposals`로 고친 뒤 200 응답을 확인했다.
- bootstrap 500 화면에서 오류 안내와 재시도 동작을 확인했고, API 재시작 뒤 같은 화면에서 정상 복구했다.
- 로그인 뒤 다른 JWT secret으로 API를 재시작해 보호 API 401을 발생시켰다. 현재 경로 `/owner/upload`가 `next`에 보존된 점주 로그인 화면으로 이동했고 반복 이동은 발생하지 않았다.
- OWNER 첫 진입과 업로드 → 질문 → 업로드 왕복을 production Web에서 확인했다.

### 자동 검사

- API: `pytest` 전체 467 passed, subtests 84 passed.
- Web: lint, TypeScript 검사, production build 통과. 총 23개 route가 build됐다.

## 남은 한계

- Web 전용 자동 테스트 runner가 없어 401 복구와 요청 수는 브라우저/API 로그로 확인했다. 이 흐름은 REL-05 lifecycle E2E에 자동화해야 한다.
- 429의 실제 서버 응답과 브라우저 offline/timeout/사용자 취소 각각을 주입한 자동 검증은 아직 없다. 분류와 재시도 계약만 구현됐다.
- REL-G2는 네트워크·상태 기반만 다룬다. 공통 터치 크기, 입력/버튼 상태, 시각 token은 REL-G3 범위다.
- 업로드/추출 작업의 DB connection 수명과 처리 속도는 REL-01에서 별도로 해결해야 한다.

## 판정

REL-G2 구현 범위는 완료했다. 이것은 전체 파일럿 출시 통과가 아니며, 다음은 REL-G3 공통 상호작용 기반과 REL-00 실제 자료 기준선이다.
