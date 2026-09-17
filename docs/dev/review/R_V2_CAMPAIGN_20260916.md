# R0 반복 캠페인 대조와 산술 게이트 연결

2026-09-16. 선행 단일 질문 수집은 `R_V2_EVALUATION_20260916.md`를 따른다. dev 평가 도구이며 release 운영 전환은 하지 않는다.

## 구현과 계약

`app/team/v2_campaign.py`가 원본 run과 출력에 연결된 검토를 받아 보고서를 다시 계산한다. 임의로 수정한 요약 점수를 입력으로 받지 않는다.

- plan은 `schema_version=r_v2_campaign_plan/v1`, manifest_hash, repeat_count, control_count, baseline_signature, candidate_signature, cost_neutral, registration_ref를 요구한다. A/B 각 최소 3회와 별도 A/A 대조 최소 3회다. 실제 실행 수가 plan과 정확히 같아야 한다.
- signature는 configuration_hash, source_hashes, provider_mode, scope다. A와 B의 의도된 코드/설정 차이는 각각 고정할 수 있다. 같은 arm의 반복 중 차이, 질문/정답/필수 목록/snapshot manifest 차이는 거절한다. 대조군은 baseline signature와 같아야 하며 A/B의 합성/실제 provider 종류와 프로토콜도 같아야 한다.
- run_id/run_hash 중복으로 같은 출력을 독립 반복처럼 사용하는 것을 차단한다. 배열 순서가 짝 순서이며 input_hash가 plan과 세 배열의 실행 순서를 고정한다. registration_ref나 hash는 실제 사전등록 시점/작성자 인증을 증명하지 않는다. 실제 캠페인은 별도 사전등록 기록을 남겨야 한다.
- 대조군의 검토된 답변 성공 개수에서 max−min을 계산한다. 하나라도 미판정이면 control_width와 문턱은 null이며 통과 불가다. 알 수 없는 폭을 0으로 표시하지 않는다.
- 기존 paired_gate의 중앙값, 2/3 방향, 최소 개선량, 모든 반복의 필수 답변 악화, 전체 미판정 차단을 유지한다. 반환의 eligible은 이 산술·검토 조건의 통과이며 production_promotion은 항상 false다.
- 기대 ANSWER 밖의 필수 정책/비답변도 버리지 않는다. candidate의 필수 행동 불일치는 별도 차단한다. 필수 CLARIFY/ESCALATE의 충분한 의미 검토 계약은 아직 없으므로 일치하더라도 `MUST_HAVE_NONANSWER_REVIEW_REQUIRED`로 보류한다. 이것을 행동 일치만으로 안전성 통과시키지 않는다.
- 비용/원장 인수는 선택적 evidence의 input_hash, cost_gate_passed, ledger_recall_regressed, reviewer, reference로 받는다. 미제공/null은 미확인으로 차단한다. 다른 캠페인의 인수 hash는 거절한다. 이는 별도 검토 결과의 귀속이며 도구가 원가·원장 자체를 자동 측정/인증한 것은 아니다.
- 결과에 run hash 목록, 검토 hash, 계산한 개별 보고와 evaluator 소스 hash를 기록한다. 과거 실행 파일은 덮어쓰지 않는다.

## 실행

`scripts/report_r_campaign.py`는 오프라인 JSON bundle을 읽으며 모델/API 호출이 없다.

```powershell
python api/scripts/report_r_campaign.py --bundle <bundle.json> --output <새로운-campaign.json>
```

bundle에는 `plan`, `baseline`/`candidate`/`control` 원본 run 배열, 선택적 `judgments`(run_hash → 검토 배열), 선택적 `evidence`를 넣는다. 검토 형식은 선행 단일 질문 도구와 같다. 누락 검토를 false나 자동 정답으로 채우지 않는다. 비용/원장 검토가 준비되지 않았다면 evidence를 생략하고 미확인 보고를 유지한다.

## 검증 결과

- 전체 단위 **535 passed / 116 subtests passed**, 기존 deprecation 경고 1개. 캠페인 신규 10개 테스트와 6개 하위 사례 포함.
- 테스트에서 A/B의 고정 설정 차이 허용, 같은 arm의 설정/소스/provider/manifest 변경 거절, 중복/누락 실행, 외부 근거 오연결, 미판정 결과/대조군, 필수 한 번 악화, 필수 정책의 분모 누락 방지, 관측 대조 폭 6→문턱 9를 확인했다.
- PostgreSQL 17.11 **26 migrations**, DB/API **230 PASS 체크**. 직전 205 + 반복 추가 provider 연결 체크 24 + 캠페인 인수 1. 고유 질문/사용자 시나리오 수가 아니다.
- 실제 격리 v2 API에서 합성 6문항을 9회 실행했다. A/B 각각 3회와 대조군 3회 모두 별도 run/session이다. 테스트는 같은 구현을 사용하며 품질 개선 실험이 아니다. 모든 실행의 manifest/설정/코드 일치와 미판정·외부 인수 없음에 따른 보류를 확인했다.
- 실제 수집 bundle은 Git 제외 `api/tmp/r-v2-evaluation/*-bundle.json`에 보존했다. 최종 캠페인 CLI 재생에서도 eligible=false, control_width=null, production_promotion=false를 확인했다. 소스 변경 감지/판정 반례는 단위 회귀, DB 수집 결과는 CLI로 최종 재검증했다.
- 변경 모듈 매장 격리 정적 검사 위반 0. git diff --check 통과. 일회용 DB는 정리했다. 운영 DB·유료 모델·배포·커밋·푸시는 실행하지 않았다.

실자료 사람 truth·30~50개 질문·후보 pooling/oracle·다회 대화 평가·실제 원가/단계 지연 및 원장 무회귀 증명은 남는다. 수집/반복 비교 접점을 구현한 것이며 R0 전체나 R 전체 완료를 뜻하지 않는다.
