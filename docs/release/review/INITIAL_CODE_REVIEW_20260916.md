# 현재 사용성 릴리스 최초 코드 관찰

2026-09-16 · 범위: 사용자 보고를 작업으로 분해하고 현재 코드 경로를 읽었다.
브라우저/실기기·운영 환경·실제 모델/DB/Storage 성능을 새로 테스트하지 않았다.
사용자 보고는 ‘추출 안 됨·전체 느림·버튼 느림·UI 조잡함’이며 각각의 재현 기준선을 아직 측정하지 않았다.

| 관찰 | 코드 근거 | 해석/다음 검증 |
|---|---|---|
| 파일 전송/등록 순차 | `web/app/owner/upload/page.tsx::handleStartBatchUpload`가 for 안에서 서명 URL→PUT→해시→등록을 await | 다중 파일 전체 대기를 증가시키는 경로. 네트워크/해시 실측 후 제한 동시성 검토 |
| source 처리도 순차 | `api/app/ingest/job_worker.py::process_ingest_job`의 source for/await | 작은 자료가 긴 영상 뒤에 기다릴 수 있음. 실제 순서/queue 시간과 자원 상한 측정 필요 |
| 추출 동안 DB 연결 점유 | `api/app/ingest/pipeline.py::process_source`의 pool.acquire가 전처리/사실 모델/조립까지 감쌈 | 기존 승인 임베딩의 연결 분리와 별개 잔여. 1개/작은 pool에서 다른 요청 대기를 재현해야 함 |
| PDF 전체 텍스트 중심 | `preprocess/document.py::read_pdf`가 페이지 텍스트를 병합해 전체 판독률 확인 | 혼합 스캔/표/페이지 관계 누락 위험. 자료별 전처리 출력과 카드 누락을 먼저 대조 |
| 영상/분할 기본값 | `api/app/config.py`: frame 상한 20, segment 0 | 코드 기본값만 확인. 실제 배포 설정/길이/프레임/전사 품질을 확인하지 않고 원인 확정 금지 |
| 일부 UI 기반 이미 존재 | 파일 추가 picker, Queue 상태, TanStack Query 작업 폴링/카드 query | 전면 새 구현을 가정하지 않음. 실제 피드백/갱신/복원/시각 품질은 브라우저 확인 필요 |
| 프론트 지원 형식 하드코딩 | `upload-file-picker.tsx`의 확장자 목록 | 서버 capabilities와 실제 처리 지원의 일치 검증 필요 |

DB 연결 점유·순차 처리는 관측한 코드 구조다. 현재 모든 느림의 원인이나 운영 장애를 입증한 것은 아니다.
추출 실패는 실효 설정, 원본/STT, 모델/잘림, 조립, 저장 중 어디인지 REL-00에서 분리한다.
UI 조잡함은 사용자 보고이며 이번에는 화면을 시각 검증하지 않았다.

## 이번 변경

`docs/release`의 README/TODO/plan/review와 상위 문서 입구만 추가했다.
시작 시 있던 분류/worker/관계 계측 수정·새 파일은 다른 진행 작업으로 보존했다.
앱 코드 변경, 의존성 설치, 유료 호출, 운영 배포는 하지 않았다.

