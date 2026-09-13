---
name: web-async-state-check
description: AskBuddy 프론트(web/)의 서버 상태·비동기 조회·컴포넌트 lifecycle 을 검증한다. TanStack Query hook, mutation, 폴링, job 복원, useEffect 를 추가하거나 고쳤을 때 쓴다. 화면 컴포넌트가 서버 작업의 생명주기를 소유하지 않는지 코드로 확인한다.
---

# 서버 상태·비동기 조회 검증

불변식 13 — **서버 작업의 상태는 서버 DB 가 정본이다.** 화면 컴포넌트의 로컬 상태가
작업 생명주기를 소유하면 새로고침 한 번에 사용자가 작업을 잃는다.

`web/AGENTS.md` 가 규칙을 적어둔 문서라면, 이 스킬은 **그 규칙이 지켜졌는지 찾아내는 절차**다.

## 언제 쓰는가

- `web/` 에 query/mutation hook 을 추가하거나 고쳤을 때
- 업로드·추출 같은 장기 작업 화면을 건드렸을 때
- `useEffect`·`setInterval`·`useState` 를 새로 썼을 때

---

## 1. 금지 패턴 탐색

아래 grep 이 한 건이라도 걸리면 그 자리에서 멈추고 고친다.

```bash
cd web

# (1) 컴포넌트에서 직접 폴링 — refetchInterval 을 쓴다
grep -rn "setInterval" app/ components/

# (2) useEffect 안에서 서버 fetch — Query 로 옮긴다
grep -rn "useEffect" -A 8 app/ components/ | grep -E "fetch\(|apiFetch|api\."

# (3) 서버 응답을 로컬 상태로 복사 — query 결과를 그대로 읽는다
grep -rn "useState" -A 4 app/ components/ | grep -E "data\b|response|result"

# (4) 오류를 조용히 정상으로 바꾸기
grep -rn "catch" -A 3 app/ components/ lib/ | grep -E "\[\]|null|return;|setError\(null\)"

# (5) lint 억제
grep -rn "eslint-disable" app/ components/ lib/
```

`localStorage` 에 API 응답을 넣는 곳도 같이 본다.

```bash
grep -rn "localStorage" app/ components/ lib/
```

화면 설정(접힘 상태, 마지막 탭)은 괜찮다. **서버 데이터는 안 된다.**

---

## 2. query key 검사

query key 에 `storeId` 와 필요한 식별자가 다 들어있는지 본다. 빠지면 매장을 바꿔도
이전 매장 캐시가 그대로 보인다.

```bash
grep -n "queryKey" -A 2 lib/query.ts app/**/*.tsx
```

---

## 3. mutation 검사

각 mutation 에 대해 확인한다.

- 성공 응답 **전에** 완료 UI 를 켜지 않는다 (불변식 15)
- 성공 후 관련 query key 를 `invalidateQueries` 한다
- 중복 클릭이 막혀 있다 (`isPending` 동안 버튼 비활성)
- optimistic update 를 썼다면 실패 시 rollback 이 있다

```bash
grep -rn "useMutation" -A 20 app/ components/ | grep -E "onSuccess|invalidateQueries|isPending"
```

`invalidateQueries` 가 없는 mutation 이 있으면 사용자가 수동 새로고침을 해야 한다는 뜻이다.

---

## 4. 장기 작업 복원 검사

업로드·추출처럼 오래 걸리는 작업은 아래를 만족해야 한다.

| 요구 | 확인 방법 |
|---|---|
| 접수 응답에 서버 job id 가 있다 | 네트워크 탭 또는 hook 반환값 |
| 접수 후 즉시 다른 화면으로 갈 수 있다 | 이벤트 핸들러가 작업 완료를 `await` 하지 않는다 |
| 재진입·새로고침에 상태가 복원된다 | 컴포넌트 mount 시 서버 job 상태를 조회한다 |
| 진행 중일 때만 폴링한다 | `refetchInterval` 이 상태에 따라 켜지고 꺼진다 |

```bash
# 이벤트 핸들러가 작업 완료를 기다리고 있지 않은지
grep -rn "await" -B 3 app/**/upload/*.tsx | grep -E "onClick|onSubmit|handle"
```

---

## 5. 정적 검증 실행

```bash
cd web && pnpm check     # lint --max-warnings 0 + typecheck + build
```

`@tanstack/eslint-plugin-query` 가 붙어 있으므로 query 규칙 위반은 lint 가 잡는다.
lint 를 `eslint-disable` 로 넘기지 않는다.

---

## 이 저장소의 현재 한계

`web/` 에는 **단위 테스트 러너가 없다** (vitest·jest 없음). 그래서 이 스킬은 정적 검사 +
브라우저 수동 확인으로 성립한다. 실제 동작 확인은 `ui-state-walkthrough` 스킬로 넘긴다.
자동 E2E 는 13.6 단계에서 Playwright 로 들어온다 — 그 전까지 "테스트가 통과했다" 고 말하지 않는다.

---

## 완료 판정

- [ ] 1절 금지 패턴 grep 이 전부 비었다 (또는 정당한 예외를 주석으로 남겼다)
- [ ] 모든 query key 에 storeId 가 있다
- [ ] 모든 mutation 이 성공 후 invalidate 하고 중복 클릭을 막는다
- [ ] 장기 작업이 job id 기반으로 복원된다
- [ ] `pnpm check` 통과
- [ ] 실제 동작은 `ui-state-walkthrough` 로 확인했다
