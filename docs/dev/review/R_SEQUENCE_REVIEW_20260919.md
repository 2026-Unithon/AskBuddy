# R 순차 구현 검토 — 2026-09-19

main `e8186f6`에서 `codex/r-sequential-handoff`로 작업했다. [순서·실행 방법·공동 인계](../plan/R_SEQUENCE_HANDOFF_20260919.md)가 현재 전달 문서다. 삭제하기로 한 이전 W 변경을 복원하지 않았으며 W producer/worker·공통 DTO·migration·프론트 파일은 수정하지 않았다.

## 검토 결과

| 항목 | 구현/검토한 경계 | 결과와 남은 조건 |
|---|---|---|
| ① 판정 교환 | source/fact 가명화·비공개 치환표, review/queue/package/import hash, 미판정 포함 전체 분모, AI/사람 구분, 기존 CAS 수입 | 합성 왕복 통과. 실제 반출·사람 확정은 회의 안건 1번 대기 |
| ② 색인 adapter | 신뢰 매장·immutable content·카드 집합·모델/renderer/glossary·요청 hash, durable 멱등, 준비의 비공개성 | 단위 및 DB 통과. expected card revision 매핑과 실제 W producer 연결 미확정 |
| ③ 완료 수신 | 현재 공개/색인/승인 카드·fact 검사, 카드 버전 고정, 알림/소비 원자성, FAQ 연결/철회 | DB 통과. 실제 W 반영·기기 push·학습/재질문 종단 미검증 |
| ④ 의미 범위 | exact-reviewed 자유 표현 병합, 조건/예외/수치/부정/규격 분리, 서버 근거 재검사, 승인 후보 선택형 명확화 | 단위 및 DB 통과. 미검토 자유 표현 자동 병합 금지. 실제 catalog·실자료 품질/활성화 대기 |
| ⑤ 로그 증거 | 환경·배포 commit·관찰 시각·4개 통제 증거의 완전성 checker, UNKNOWN/실패/오래된 증거 차단 | 합성 통과. .env 이름만 확인. 호스팅은 미확인, 회의 안건 |

## 실행한 검증

- API 전체 단위: **866 passed, 4 xfailed, 119 subtests passed**. 기존 Starlette/anyio deprecation warning 1개. 유료 모델 호출 없음.
- 저장소 `store-isolation-check` AST 검사: learn/reg/team 76개 파일, 위반 0건. 격리 DB의 다른 매장·다른 회원·미인증·직원 권한 거부 시나리오도 통과했다.
- 격리 PG17 전체 **28 migration** 재구축 및 기존 R/W DB 검증 통과. 실제 `.env` DB는 사용하지 않았다.
- 주요 DB 묶음: M2 **44**, 답변 저장 **20**, v2 HTTP **117**, 점주 전달/완료 **53**, 보존 **13**, 문맥/stale **21**, reranker 계측 **13** checks. 예산·권한·원가 등 기존 검증도 같은 runner에서 통과했다.
- 새 반례: 위조 공개 revision 거부, 알림 실패 시 knowledge state/outbox consumption 롤백, 완료의 현재 카드 버전 pin, FAQ 반영·카드 철회 시 해제, 실제 검토 근거 없는 묶음 저장 거부, 변경 조건 분리, 타입 기반 prepare 재시도 시 추가 embedding 방지.
- 신규 선택형 명확화 지시는 `api/prompts/r_general_proposal.txt`로 분리하고 release의 source hash에 포함했다. 마지막 프롬프트 파일 분리 후 관련 의미 처리 **34 tests**를 재검증했다. 신규 CLI의 `--help` 진입도 확인했다.
- 브라우저는 이번 작업에서 실행하지 않았다. 기존 refresh hook의 FAQ/roadmap invalidation을 코드로 확인했으며 실제 W 종단 인수를 대신하지 않는다.

재현 명령(저장소 루트, Windows):

```powershell
.\api\scripts\verify_r_handoff.ps1 -Python C:\project\AskBuddy\api\.venv\Scripts\python.exe -IncludeSchemaRebuild
# api 디렉터리에서:
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp=tmp/sequence-check -p no:cacheprovider
```

전체 작업 완료 판정은 하지 않는다. 도구/합성 검증 완료, 실자료 정답·운영 증거·실제 W 연결·품질 인수 미완료를 분리한다.
