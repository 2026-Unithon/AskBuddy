# 페이지별 검토 전 전역 구조 검토

2026-09-16 · `dev_mvp` 브랜치. 앱 코드를 수정하지 않은 read-only 코드 검토와 Web 정적 build 기록이다.
실제 브라우저 조작, API/DB/Storage/모델 호출, 운영 성능 측정은 하지 않았다.

## 발견 사항

| 중요도 | 발견 | 근거 | 영향/후속 |
|---|---|---|---|
| P0 | bootstrap이 Web 진입에 연결되지 않았고 일부 반환 목적지가 실제 route와 다름 | API `bootstrap/router.py`는 `/owner/setup`, `/staff/join`을 반환; Web route 없음. Web API client에도 bootstrap 호출 없음 | 로그인/재진입 목적지·배지·회원 상태를 서버 정본으로 연결하고 실제 route matrix 검증 |
| P0 | 긴 source 처리 동안 DB connection을 잡음 | `ingest/pipeline.py::process_source`의 `pool.acquire()` 범위에 전처리·STT·추출·조립 포함 | 작은 pool에서 모든 버튼/API가 느려질 수 있음. pool 대기 측정 후 외부 I/O를 connection 밖으로 분리 |
| P1 | 전역 navigation이 여러 목록 API를 읽음 | `owner-bottom-nav.tsx`가 pending, card pending, card needs-review, proposals 4 query | bootstrap/경량 attention summary로 합치고 요청 수 전후 비교 |
| P1 | Query 기본 freshness가 0 | `providers.tsx`에 전역 staleTime 없음; 일부 query만 2초 지정 | 탭 remount/focus 때 불필요한 재조회 가능. 데이터별 정책과 mutation 갱신 설계 |
| P1 | 인증 만료·timeout·취소의 중앙 처리 없음 | `api.ts::fetchJson`은 status ApiError, abort/timeout 구분과 401 session handler 없음 | 페이지마다 generic 연결 오류/빈 화면 가능. 공통 error taxonomy·목적지 복원 필요 |
| P1 | 서버 빈/오류와 mock이 섞일 수 있는 legacy 화면 | `owner/category/page.tsx`는 categories가 없으면 `state.categories` mock 사용; store 초기값도 demo 값 | production mock 격리, 정상 empty/error를 그대로 표시. 사용 route 조사 후 legacy 제거/전환 |
| P1 | 업로드와 source job이 각각 순차 처리 | `owner/upload/page.tsx` file loop, `ingest/job_worker.py` source loop | 긴 파일이 뒤 작업을 막을 수 있음. 단계 실측 후 제한 동시성·공정성·재시도 설계 |
| P2 | 본문 기준보다 작은 텍스트가 넓게 사용됨 | page/component 다수 `text-[10/11/12px]`, `text-xs` | 실제 기기 가독성 검토와 공통 typography scale 필요 |
| P2 | 공통 UI 계약이 상태를 충분히 표현하지 않음 | `Button`은 loading/aria-busy 내장 없음; 화면별 임의 class/emoji/shadow 다수 | primitive에 상호작용/접근성/상태를 넣고 페이지별 중복 제거 |
| P2 | hydration 대기 중 owner 화면이 아무것도 렌더하지 않음 | `owner/layout.tsx` + `useAuthGuard`, ready 전 `null` | 느린 기기에서 먹통처럼 보일 수 있음. 최소 app shell/loading 제공 |

코드 구조는 병목 **후보**다. 실제 운영 지연 비율·추출 실패 원인은 REL-00 단계별 측정 전 확정하지 않는다.
특히 DB connection 점유가 사용자의 ‘버튼마다 느림’과 연결되는지는 pool wait/동시 요청으로 재현해야 한다.

## 이미 있는 기반

- Query key에 store scope가 있고 focus/reconnect 재검사, ingest job polling/완료 invalidation 기반이 있다.
- owner 3탭과 공통 header/navigation, loading/error/empty 관련 component가 존재한다.
- 파일 picker와 queue는 여러 형식/파일별 상태를 표현하며 API timeout/AbortController 기반이 있다.
- 서버 bootstrap은 user/store/default destination와 일부 badge를 한 응답으로 제공한다.

따라서 전면 재작성보다 기존 기반을 하나의 전역 계약으로 묶고 중복/거짓 상태를 제거하는 방향이 적절하다.

## 이번 검증

```text
cd web && pnpm check
eslint --max-warnings 0: 통과
tsc --noEmit: 통과
next build: 통과, 23개 page 생성
```

정적 검사/build 통과는 API 연결, 사용자 체감 속도, 모바일 시각 품질 또는 lifecycle E2E 통과가 아니다.

