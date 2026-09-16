# 페이지별 검토 전 전역 기반 개선 계획

## 이 트랙에서 하는 것

현재 기능의 진입, 데이터 조회, 오류/복구, 버튼 반응, 백그라운드 작업, 모바일 UI의 공통 기반을 고친다.
모든 페이지에 같은 문제를 반복 수정하지 않게 한 번만 해결하는 것이 목적이다.

이 트랙에서는 docs/dev의 모델 프롬프트·추출 schema·채점 기준·fact/card 의미·검색 알고리즘을 바꾸지 않는다.
전역 사용성 수정 중 그 영역의 결함을 발견하면 재현과 영향만 release review에 남기고 해당 소유 트랙으로 연결한다.
단, 사용자를 속이는 성공/빈 상태, 미승인 공개, 매장 누출, 작업 유실은 릴리스 차단 결함으로 즉시 다룬다.

## G1. 진입과 ‘서버가 진실’인 화면

1. 로그인 성공/앱 재진입/직접 링크에서 `/app/bootstrap`으로 현재 사용자·매장·역할·기본 목적지·배지를 확인한다.
2. bootstrap의 목적지를 실제 Web route inventory와 맞춘다. 없는 route를 반환하지 않는다.
3. localStorage는 토큰/최소 세션 복원에만 쓰고, 표시 이름·매장·배지는 bootstrap 결과로 재검증한다.
4. 인증 만료/회원 제거/매장 불일치는 mock이나 빈 화면이 아니라 재로그인/접근 불가로 보낸다. 원래 목적지는 안전하게 보존한다.
5. mock 데이터는 명시적 demo 환경에서만 허용한다. 서버 로딩·오류·정상 빈 배열을 mock으로 채우지 않는다.

완료 확인: 신규/기존 OWNER·STAFF, 매장 있음/없음, 만료 토큰, 다른 매장 직접 링크, 새로고침에서 올바른 한 목적지와 상태가 나온다.

## G2. 조회 수·캐시·오류의 공통 규칙

1. 화면별 query inventory를 만들고 데이터 성격에 따라 `staleTime`, focus/reconnect 재검사, pagination을 정한다.
2. owner layout에서 필요한 배지는 bootstrap/경량 summary 한 번으로 가져온다. 하단 navigation이 카드 목록 2개·질문·제안을 매 mount마다 따로 읽지 않게 한다.
3. notification/header/job monitor의 중복 관찰자는 Query cache를 공유하되 불필요한 refetch를 만들지 않는지 Network 기준으로 검증한다.
4. mutation은 영향을 받은 query만 갱신한다. 화면 전환을 기다리게 하는 광범위 `await invalidateQueries`는 서버 성공과 후속 background refresh를 분리한다.
5. 공통 API client가 HTTP 오류, timeout, AbortSignal 취소, 오프라인을 구분하고 request ID/retryable 정보를 보존한다.
6. 401은 한 번의 중앙 세션 처리, 403/404는 정보 노출 없는 접근 불가, 409는 최신 상태 재조회, 429는 재시도 시간, 503/504는 입력 보존/재시도로 연결한다.

완료 확인: 주요 탭을 왕복해도 같은 데이터의 요청 수가 불필요하게 증가하지 않고, 이전 콘텐츠를 유지한 채 최신 상태로 수렴한다. 오류를 빈 화면이나 무한 loading으로 보이지 않는다.

## G3. 모든 버튼과 입력의 상호작용 계약

- 클릭/탭 즉시 시각 피드백을 준다. 실제 저장·승인 성공은 서버 응답 뒤에만 확정한다.
- 요청 중에는 해당 행/버튼만 막고 다른 화면 탐색은 유지한다. 같은 요청의 연타는 client와 server 양쪽에서 중복 방지한다.
- 버튼 label이 동작을 설명하고 icon-only는 접근성 이름을 갖는다. touch target 44px, 키보드 focus-visible을 공통 primitive에서 보장한다.
- 저장 실패 시 입력·스크롤·현재 공개본을 유지하고 오류 자리에서 재시도한다. 사라지는 toast만으로 중요한 실패를 알리지 않는다.
- destructive/공개 동작은 영향과 현재 상태를 보여주고, stale version이면 덮어쓰지 않고 최신 내용을 다시 보여준다.
- 긴 요청은 단계/대상을 표시하며 화면을 떠나도 계속되는지 명확히 구분한다.

먼저 공통 `Button/LinkButton/Input/TopBar/BottomCta`와 상태 컴포넌트를 정리한 뒤 페이지별 예외를 적용한다.

## G4. 모바일 정보·시각 기반

- 390×844를 기본, 360×800과 최대 480px를 함께 본다. 하단 navigation/safe area/키보드가 CTA를 가리지 않게 한다.
- 본문은 16px를 기본으로 하고 10~12px 남용을 제거한다. 작은 텍스트가 필요한 badge/meta도 명도·행간·의미를 실제 기기에서 확인한다.
- 페이지마다 임의 shadow/radius/색/emoji를 추가하지 않고 semantic token과 상태 component를 사용한다.
- header/title/back/primary action의 위치와 용어를 역할별로 통일한다. 화면마다 같은 상태가 다른 문구·색으로 나오지 않게 한다.
- `prefers-reduced-motion`, skeleton, background refresh, empty/error/partial/no-result를 공통으로 제공한다.
- 로딩 때문에 전체 화면이 흰색이 되거나 auth hydration 동안 설명 없이 멈추지 않게 최소 shell 상태를 제공한다.

이 단계는 브랜드 전면 재디자인이 아니다. 페이지별 취향/정보구조 피드백은 `PAGE_REVIEW_CURRENT.md`에서 별도로 받는다.

## G5. 장기 작업과 운영 진단

1. source/job 처리의 외부 I/O와 모델 호출은 DB connection/lock 밖에서 수행하고 저장 경계에서 상태를 재검사한다.
2. 업로드·source 처리 동시성은 파일 수/크기/DB pool/공급자 제한을 측정해 상한을 둔다. 무제한 병렬화나 항상 순차 처리 중 하나로 고정하지 않는다.
3. worker claim/lease/heartbeat/checkpoint/retry와 API 재시작 회수를 검증한다. 브라우저 폴링이 작업 실행을 소유하지 않는다.
4. 단계별 queue/전송/전처리/STT/추출/조립/저장 시간과 실패 코드를 job/source에 연결한다.
5. client request ID → API → job/source/card를 연결해 지원 시 재현할 수 있게 한다. 원문·토큰·비밀값을 일반 로그에 넣지 않는다.

완료 확인: 긴 작업 중 목록/상세/단순 저장이 응답하고, 새로고침/API 재시작/부분 실패 뒤 정확한 상태와 재시도 대상을 복원한다.

## 구현 묶음 순서

| 묶음 | 변경 범위 | 독립 완료 기준 |
|---|---|---|
| REL-G1 | bootstrap route 정합·Web 연결·mock 격리·auth 오류 | 역할/매장/직접 링크 matrix 통과 |
| REL-G2 | query inventory·배지 summary·API 오류 분류 | 탭 왕복 Network 비교·오류/재연결 검증 |
| REL-G3 | 공통 버튼/입력/상태·타이포/safe area | component 전파 후 모바일/키보드 walkthrough |
| REL-G4 | pipeline connection 수명·작업 복구·단계 관측 | 동시 요청/재시작/부분 실패 API·DB 검증 |
| REL-G5 | 실제 작은 흐름 smoke·성능/지원 runbook | 릴리스 기준선 전후 비교와 알려진 제한 |

각 묶음은 작은 변경으로 구현·검증하고 review를 새로 남긴다. 페이지별 개선은 G1/G2의 진실성 기반 이후 병행할 수 있다.

