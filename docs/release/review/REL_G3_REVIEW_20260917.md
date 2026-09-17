# REL-G3 공통 상호작용·모바일 기반 검증

2026-09-17 · 브랜치: `dev_mvp`

범위는 공통 버튼·링크·입력·상태·타이포·safe area다. `docs/dev`의 AI 및 평가 작업은 변경하지 않았다.

## 구현 결과

- `Button`에 loading spinner, 동사형 loading label, `aria-busy`, disabled, pressed feedback, focus ring을 통합했다. 요청 중 label과 disabled를 화면마다 따로 조합하던 경로를 주요 mutation에 전파했다.
- Input/Textarea/Select를 16px 공통 입력으로 맞추고 invalid, disabled, keyboard focus를 통일했다.
- TopBar 뒤로가기와 raw icon/button/link를 포함한 앱 조작 영역을 최소 44px로 맞췄다.
- 카드·제안·카테고리·작업 재시도는 현재 처리 중인 행만 막도록 좁혔다. 로그인·업로드·답변 제출은 handler guard와 pending 상태를 함께 사용한다.
- 카드 409 충돌은 최신 목록/상세를 다시 읽는다. 카드 제외는 직원 화면·검색에서 제외되며 복원 가능하다는 확인을 거친다.
- inline 오류와 background refresh에 live region을 제공하고, skeleton/empty/error에 안정적인 test hook을 추가했다.
- 핵심 본문은 16px, 설명은 14px, 보조 정보는 최소 12px로 정리했다. 임의 오류 hex 색을 danger token으로 교체했다.
- 하단 navigation·채팅 입력·CTA에 safe area를 반영하고 reduced-motion 전역 fallback과 `motion-safe` animation을 적용했다.

정책은 [INTERACTION_AND_VISUAL_POLICY.md](../plan/INTERACTION_AND_VISUAL_POLICY.md)에 기록했다.

## 실제 브라우저 확인

실제 로컬 DB/API와 OWNER·STAFF demo 계정을 사용했다.

| 항목 | 결과 |
|---|---|
| 390×844 OWNER 질문 | 초기 skeleton, 데이터, 답변 sheet, 비활성 제출, 하단 navigation 확인 |
| 답변 입력 | computed font 16px, 입력 높이 130px, 제출 버튼 52px 확인 |
| 키보드 focus | 실제 Tab 이동 대상 높이 44px, solid brand outline 확인 |
| OWNER 업로드 | 파일 선택 CTA 358×56px, 실제 서버 작업 상태와 하단 navigation 확인 |
| OWNER 카드 | 검색 입력 16px·48px, filter, 빈 상태, 다음 행동 확인 |
| API 중단 | 빈 목록으로 위장하지 않고 전역 오류·재시도 표시 확인 |
| API 재기동 | 재시도 후 같은 `/owner/cards` URL과 정상 빈 상태로 복구 확인 |
| STAFF 정상 경로 | 로그인 → roadmap → chat → FAQ 이동과 역할별 navigation 확인 |
| 390×844 STAFF | document width 390px, 가로 넘침 없음, 앱 조작 요소 44px 이상 |
| 360×800 OWNER/STAFF | document width 360px, 가로 넘침 없음, 앱 조작 요소 44px 이상 |

자동 DOM 크기 검사에서 44px 미만으로 나온 유일한 항목은 개발 환경의 Next.js Dev Tools 버튼(32px)이었다. 제품 UI가 아니며 production build에는 없다.

## 정적 검증

- `pnpm check`: lint, TypeScript, production build 통과. 23개 route 생성.
- component `setInterval`, effect 내부 fetch, eslint disable 없음.
- localStorage는 최소 인증 session 복원에만 사용하고 서버 응답을 저장하지 않는다.
- `git diff --check` 통과.

## 확인하지 않은 범위

- 실제 파일 업로드, 카드 공개, 점주 답변 제출은 DB 변경과 AI/임베딩 호출을 만들 수 있어 이번 UI walkthrough에서는 실행하지 않았다. 연타 시 서버에 한 건만 생기는지는 REL-03/REL-05 실제 lifecycle smoke에서 확인한다.
- 모바일 가상 키보드가 열린 실제 iOS/Android 기기와 VoiceOver/TalkBack은 확인하지 않았다.
- 카드 30장 이상과 매우 긴 한글 데이터는 page별 검토 자료가 준비된 뒤 확인한다.

## 판정

REL-G3 공통 기반 구현과 현재 데이터로 가능한 브라우저 인수는 완료했다. 전체 파일럿 출시는 아직 보류다. 다음 전역 묶음은 장기 작업 connection 수명·복구·단계 관측(REL-G4)이며, 실제 자료 기준선(REL-00)도 별도 수행해야 한다.
