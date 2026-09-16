# W 평가 캠페인 강제 검증

2026-09-16. `run_extract_eval.py`의 단순 캠페인 JSON 로딩을 사전등록 계약 검증으로 교체했다.
실제 holdout 내용·운영 DB를 열거나 유료 모델을 호출하지 않았다.

## 구현

- split과 manifest/truth/source SHA-256, 후보별 runtime 설정을 정확히 대조한다.
- CONTROL/CANDIDATE/CONTROL_REPEAT, 후보별 최소 3회, 고정 순서·seed·label을 요구한다.
- 실행 수·원본 byte·provider attempt·등록비 상한과 D18/D21 핵심 gate를 실행 전에 검사하고,
  종료 시 앞 slot 누계까지 다시 강제한다. 앞 slot의 비용이 미관측이면 다음 실행을 막는다.
- 캠페인 hash와 slot을 원자적 파일 생성으로 잠근다. 같은 slot 또는 변경된 캠페인은 거절한다.
- holdout 원본/truth는 claim 뒤에만 읽고, OPENED/STARTED/SUCCEEDED/FAILED를 append-only로 남긴다.
- 원가 누락은 0원으로 보지 않는다. 실제 호출 수나 완전 관측 등록비가 상한을 넘으면 실패한다.

## 검증과 한계

합성 캠페인으로 승인/split/hash/설정/반복/실행표/예산/gate 반례와 중복 slot,
변경 캠페인 lock 재사용, 미관측·초과 원가를 검사했다. 전체 API 회귀와 매장 격리 정적 검사를
함께 실행했다.

```text
api/.venv/bin/python -m pytest api/tests/test_eval_campaign.py -q
16 passed

api/.venv/bin/python -m pytest api/tests -q
467 passed, 84 subtests passed

python3 .claude/skills/store-isolation-check/check_store_id.py api/app/team
검사한 파일 13개 / 매장 격리 위반 없음
```

실제 캠페인은 만들거나 실행하지 않았다. 따라서 holdout은 계속 봉인 상태이며 품질 개선,
D21 통과, 전체 CP-05 승격을 주장하지 않는다. 등록된 attempt 상한은 실행 후 원장으로 강제한다.
한 provider 호출 내부에서 이미 발생한 초과 비용을 사전에 되돌릴 수는 없다.
