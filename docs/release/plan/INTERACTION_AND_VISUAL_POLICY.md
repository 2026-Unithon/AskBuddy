# REL-G3 상호작용·모바일 시각 정책

2026-09-17 · 적용 범위: 현재 Web 공통 primitive와 실제 OWNER/STAFF 화면. 모델·추출·카드 의미는 변경하지 않는다.

## 조작 계약

| 항목 | 공통 규칙 |
|---|---|
| 터치 영역 | 버튼·주요 링크·입력은 최소 44×44px. 아이콘만 있는 조작은 접근성 이름을 제공한다. |
| 포커스 | 키보드 `focus-visible`에 브랜드 색 2px ring과 offset을 표시한다. 포커스를 색 변화만으로 표현하지 않는다. |
| 눌림 | 탭 즉시 active 상태를 표시한다. 서버 성공 전에는 완료 상태로 바꾸지 않는다. |
| 요청 중 | `Button loading`이 spinner, 동사형 label, `aria-busy`, disabled를 함께 적용한다. 동일 요청의 연타를 막되 관계없는 행과 navigation은 유지한다. |
| 오류 | 중요한 오류는 입력과 기존 콘텐츠를 유지한 inline `role=alert`로 표시한다. 재시도는 같은 오류 자리에서 수행한다. |
| 충돌 | 409이면 최신 query를 다시 읽고 이전 화면 상태로 조용히 덮어쓰지 않는다. |
| 공개·제외 | 공개 label에 직원 노출을 명시한다. 제외는 직원 화면·검색에서 사라진다는 영향과 복원 가능 여부를 확인한다. |
| 입력 | Input/Textarea/Select는 16px, 명시적 label 또는 접근성 이름, invalid/disabled/focus 상태를 공유한다. |

업로드 batch는 기존 idempotency key를 유지한다. 카드 공개는 서버가 임베딩 준비 전후 버전을 재검사하고, 초안 저장과 카테고리 이동은 expected version/time을 사용한다. 화면의 disabled만 서버 경합 방지로 간주하지 않는다.

## 시각·모바일 계약

- 기준은 390×844, 보조는 360×800, 콘텐츠 최대 폭은 480px다.
- 하단 navigation과 고정 CTA는 `env(safe-area-inset-bottom)`을 포함한다. 스크롤 콘텐츠도 같은 높이만큼 여유를 둔다.
- 핵심 본문과 입력은 16px, 설명은 14px, badge·시간·상태 같은 보조 정보도 12px 아래로 내리지 않는다.
- 상태색은 brand/warn/danger/muted token을 사용한다. 오류를 임의 hex 색으로 표현하지 않는다.
- `prefers-reduced-motion`에서는 animation과 transition을 사실상 제거한다. skeleton과 상태 점은 `motion-safe`에서만 움직인다.
- background refresh는 기존 콘텐츠를 지우지 않고 별도 `role=status`로 표시한다.

## 검증 후크

공통 오류, 빈 상태, skeleton, background refresh와 업로드/답변/검색의 주요 조작에는 안정적인 `data-testid`를 둔다. 화면 문구나 CSS class를 E2E selector의 정본으로 삼지 않는다.

## REL-G3 완료 확인

- lint, TypeScript 검사, production build 통과
- 금지된 component polling, effect fetch, 서버 응답 localStorage 복제, lint 억제 없음
- OWNER/STAFF 정상·초기 로딩·빈 상태·오류·재시도 확인
- 390×844와 360×800에서 가로 넘침과 44px 미만 앱 조작 요소 없음
- 키보드 focus ring과 입력 16px 확인
- 실제 데이터가 생기는 업로드·공개·답변 연타는 page별 실사용 smoke에서 별도로 검증
