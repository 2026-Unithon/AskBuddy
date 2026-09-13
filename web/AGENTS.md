<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Frontend correctness contract

- 서버 데이터는 `lib/query.ts`의 TanStack Query 키와 옵션으로 관리한다. Context나 localStorage에 API 응답을 복사하지 않는다.
- 컴포넌트에서 서버 폴링용 `setInterval`을 만들지 않는다. 진행 상태에 따라 `refetchInterval`을 켜고 끈다.
- mutation 성공 뒤 관련 query key를 invalidate한다. 성공 응답 전에는 완료 UI를 표시하지 않는다.
- 이벤트 핸들러 밖에서 Promise를 방치하지 않는다. 의도적으로 기다리지 않을 때만 `void`를 명시한다.
- `useEffect`는 브라우저 API나 외부 시스템 동기화에만 쓴다. 서버 데이터 로딩은 Query로 처리한다.
- 화면 이동과 새로고침 뒤에도 복원되어야 하는 작업은 서버의 job ID/status를 정본으로 삼는다.
- 작업을 마치기 전에 `pnpm check`를 통과시킨다.


- 서버 데이터는 useState, Context, localStorage에 복사하지 않는다.
- 서버 데이터 조회는 TanStack Query의 query hook으로만 구현한다.
- 생성·수정·삭제는 mutation hook으로 구현하고 성공 후 관련 query를 invalidate한다.
- 컴포넌트 useEffect에서 직접 fetch하지 않는다.
- 페이지 컴포넌트에서 setInterval 기반 폴링을 구현하지 않는다.
- 백그라운드 작업 완료를 이벤트 핸들러에서 기다리지 않는다.
- 작업 생성 API는 job_id를 반환해야 하며, 작업 상태는 서버에서 복원 가능해야 한다.
- 페이지 재진입, 새로고침, 포커스 복귀 시 서버 상태를 다시 동기화한다.
- 초기 로딩과 백그라운드 갱신을 구분한다. 갱신 중 기존 화면을 지우지 않는다.
- 네트워크 오류를 성공 상태로 변환하지 않는다.
- 오류를 빈 배열이나 정상 상태로 조용히 바꾸지 않는다.
- 중복 클릭을 막고 mutation에는 idempotency를 고려한다.
- optimistic update는 실패 시 rollback이 있을 때만 사용한다.
- query key에는 반드시 storeId와 필요한 식별자를 포함한다.
- eslint-disable 주석으로 오류를 숨기지 않는다.
- 변경 완료 전 lint, typecheck, test, build, 관련 E2E를 실행한다.

# 검증 스킬

규칙을 지켰는지 **확인하는 절차**는 저장소 스킬에 있다. 작업을 마쳤다고 보고하기 전에 쓴다.

- `web-async-state-check` — 금지 패턴 탐색, query key·mutation·job 복원 검사. `pnpm check` 포함
- `ui-state-walkthrough` — 브라우저에서 로딩·빈 상태·오류·재시도·이동·복원·연타를 실제로 확인

`web/` 에는 단위 테스트 러너가 없다(vitest·jest 없음). "테스트가 통과했다" 고 쓰지 않는다.
정적 검사와 브라우저 확인을 구분해서 보고한다. 자동 E2E 는 13.3 단계에서 들어온다.
