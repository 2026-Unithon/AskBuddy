# R 변경 공유와 다음 작업 — 2026-09-21

R 구현 커밋 `455b06d`, 최신 원격 main `db40813`을 공유 브랜치 `codex/r-sequential-handoff`에 통합했다. W의 최신 추출 결함·PDF 변경은 원격 main에서 받은 내용이며 이번 PR의 R 변경으로 집계하지 않는다. 상세 구현 계약은 [R 순차 인계](R_SEQUENCE_HANDOFF_20260919.md)를 따른다.

## 이번에 공유하는 변경

1. 비공개 가명 치환표 → 외부 AI 판정 패키지 → 제안 수입 → 별도 사람 확인 기록 도구. 실제 외부 전송·정답 확정은 하지 않았다.
2. R 색인 준비 요청의 매장·내용·요청 hash·카드 집합·설정 검증과 멱등성. 준비는 공개가 아니며 W 발행 transaction에서 활성화해야 한다.
3. W 완료 수신 시 현재 승인판·색인을 검사하고 카드 버전·상태·알림·outbox 소비를 원자로 기록한다. FAQ는 동일 승인 카드 버전만 연결한다.
4. 검토된 정확한 입력의 동일 대상·속성·규격·조건/예외/수치/부정 범위만 병합한다. 새 모델/reviewed 명확화는 승인 후보의 대상·온도·크기 선택형으로 제한한다. 기본 OFF를 유지한다.
5. 운영 로그의 배포 범위·조회 권한·보존·정리 증거 점검 도구. 서류 완전성과 실제 호스팅 확인을 구분한다.

## 진행 순서와 담당

| 순서 | 담당 | 작업 | 완료 기준·선행 |
|---|---|---|---|
| 1 | R, W 검토 | R PR 검토·CI 확인 후 병합 판단 | 특히 아래 두 인계 접점의 호환성 확인. 이번 공유가 운영 배포 승인은 아님 |
| 2 | W+R | 색인 요청의 카드별 expected revision 매핑, 변경 카드 묶음과 전체 manifest 관계 확정 | 현재 wrapper는 모호한 비어 있지 않은 expected_card_revisions를 거부. W의 draft/card CAS는 별도 필수 |
| 3 | W | 실제 producer에서 불변 preview → R prepare → W 공개 transaction + R activate 연결 | 준비 실패·TTL·승인 변경·중복 요청에서 잘못 발행하지 않음 |
| 4 | W+R | 완료 payload 합의 후 W owner-answer worker 연결 | claim/heartbeat/재시도, LINKED/PUBLISHED card_id, 공개 transaction에서 R finish, 실패 시 전체 rollback |
| 5 | 운영 담당+R | Railway 실제 배포·로그·DB 보존 확인 | 대상 서비스/환경/배포 SHA와 증거 일치. 아래 절차 참조. 2~4와 독립 진행 가능 |
| 6 | 회의·검토자 | RD-01 외부 AI 판정 인정 방식 확정 후 두 매장 정답 검토 | **회의 안건 1번**. 생성 참조·AI 판정·사람 최종 판단을 구분 |
| 7 | R | 실제 snapshot 기반 품질·원가·지연 평가 | 사람 검토 정답 + W 실제 승인 snapshot + RD-02 유료 예산 승인 |
| 8 | W+R | 점주 1명·직원 2명 종단 및 복구 인수 | 실제 producer/worker 연결. 구/신 버전 전환·철회·중복·역순·중단 복구 포함 |

현재 코드에서 `activate_prepared_index`와 `finish_owner_event`의 제품 W 호출자는 확인되지 않았다. 최신 W 변경은 추출/PDF 영역이며 이 두 연결의 완료로 간주하지 않는다. 새 [W 참조 추출 계획](W_REFERENCE_EXTRACTION_20260920.md)도 참조 생성은 판정/사람 정답과 별개라고 명시한다.

## Railway에서 ⑤를 닫는 방법

사용자가 알려준 배포 주소: https://askbuddy-production.up.railway.app/

이 URL은 점검 대상이며 실제 배포 SHA·환경·로그 정책의 증거는 아니다. Railway 관리자 화면에서 해당 도메인의 프로젝트/서비스/환경, 배포 브랜치와 commit을 먼저 기록한다. 로컬 `.env`와 실제 서비스 Variables가 같다고 가정하지 않는다.

1. 배포·migration 담당자가 실제 적용 코드와 schema를 확인한다. PR 병합 뒤 자동 배포가 걸려 있는지도 확인한다.
2. 일반 로그로 나가는 request/response·SDK·예외 경로를 점검한다. 테스트용 비밀 아닌 표식을 사용해 정상·오류 경로에서 질문/답변 원문이 로그에 복제되는지 대조한다. 실제 매장 원문을 증거 문서에 복사하지 않는다.
3. 프로젝트가 비공개인지, 로그를 볼 수 있는 계정/역할이 누구인지 확인한다. 서비스 공개 URL과 Railway 프로젝트 공개 설정은 다르다.
4. DB의 `20260918090000_r_metadata_retention.sql` 적용과 `R diagnostics retention sweep` 실행/실패 기록, 30일 지난 진단 metadata 잔존 여부를 확인한다. 현재 정리 루프는 실행 중인 API에서 시간 단위로 돈다. 서비스 휴면/중단 조건에서 별도 스케줄러가 필요한지는 운영 담당과 결정한다.
5. Railway 로그 조회 기간과 DB 진단 보존을 분리해 기록한다. 2026-09-19 확인한 공식 문서는 Hobby 7일·Pro 30일 조회를 안내하며 업그레이드 시 이전 로그 복원을 명시했다. 조회 기간을 실제 삭제 보장으로 간주하지 않는다. 로그에도 30일 조회가 필요한지와 비용은 회의에서 결정한다.
6. 비공개 evidence JSON에 확인자·시각·실제 배포 SHA·증거 위치를 기록하고 `check_r_logging_evidence.py`로 점검한다. 이 도구의 `READY_FOR_REVIEW`는 호스팅 자동 검증 완료가 아니다.

참고: [Railway 로그](https://docs.railway.com/observability/logs), [프로젝트 공개 범위](https://docs.railway.com/projects), [프로젝트 권한](https://docs.railway.com/projects/project-members).

## 최종 공동 확인 흐름

직원 질문 → R 검색/이관 → 점주 원문 전달 → W 지식 반영/검토 → R 준비 색인과 W 원자 발행 → R 완료 수신 → FAQ·학습·알림 갱신 → 직원 재질문.

회의에서는 RD-01 판정 방식, RD-02 예산, 로그 점검 담당/정책, W/R 두 인터페이스를 확정하면 된다. 사람 정답과 유료 평가가 대기여도 PR 검토·인터페이스 연결·운영 설정 확인은 진행할 수 있다.
