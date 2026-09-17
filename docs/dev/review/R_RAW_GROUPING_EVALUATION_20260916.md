# R 단독: RAW 평가 누락 수정·의미 묶음 평가

2026-09-16. Docker, W 구현, DB 변경 및 외부 모델 호출 없이 진행했다. R0/R3/R5의 승인 근거 평가와 잘못된 의미 묶음 검증을 보강했다. 제품 질문 판정 규칙이나 rollout 설정은 변경하지 않았다.

## 발견한 누락과 수정

1. **RAW 정답 수입**: 기존 ReviewedCase는 ANSWER에 typed fact revision을 필수로 요구했다. 승인 RAW만으로 충분한 정상 답변의 truth를 수입할 수 없는 결함이었다. `required_raw_blocks`를 추가하고 card/version/block/raw_span 네 참조를 승인 snapshot과 정확히 대조한다. 존재하지 않는 revision/RAW·중복 참조를 거절한다. typed fact를 가짜로 발급하지 않는다.
2. **RAW 근거 회수율**: 기존 evidence_recall과 oracle은 typed 사실만 셌다. `required_raw` 의미 매핑, RAW 회수율, 누락 RAW 및 원문 검토 정보를 추가했다. fact 회수율은 typed 분모가 없으면 null이다. typed/RAW 혼합 질문은 양쪽 근거가 모두 회수돼야 complete다. 현재 eligible universe에서 제외된 RAW는 정답 근거로 사용할 수 없다.
3. **RAW oracle**: 사람이 정한 RAW 블록도 oracle 후보에 주입한다. 실제 회수 누락과 충분성/판정 문제를 분리한다. oracle ANSWER의 semantic_correct는 여전히 미판정이며 모델·사람 정답 검토를 대신하지 않는다.
4. **의미 묶음 평가**: 질문·매장·snapshot·확정 문맥에 묶인 사람 쌍 판정과 실제 grouping 출력을 비교한다. 잘못 합침, 필요한 묶음의 분리/보류, 미판정, 매장/판본 경계 위반을 기록한다. 출력이 없는 질문을 분모에서 삭제하지 못한다.

## 평가 계약

- `ReviewedCase.required_raw_blocks`: card_id, card_version_id, block_id, raw_span_id의 목록. 기존 typed-only 입력은 그대로 허용한다. 출력 sidecar mappings에 RAW 근거를 보존한다. 기존 EvaluationManifest.required_facts에는 가짜 RAW fact ID를 넣지 않는다. RAW 질문 평가자는 manifest만이 아니라 원래 artifact의 mappings를 함께 확인해야 한다.
- `EvidenceTruth.required_raw`: 위 네 참조와 meaning_id. typed/RAW 간 meaning_id 중복을 거절한다. `r_evidence_recall/v2`로 결과 버전을 올렸다.
- `GroupCase`: question_id, store_id, snapshot_hash, question, confirmed_context.
- assignments: 모든 질문 ID에 group ID 또는 명시적 보류 null을 지정한다. group ID는 서로 다른 매장/판본 사이에도 비교 가능한 실제 식별자를 사용한다. 매장별 숫자나 클러스터 번호를 재사용한 자료는 사전에 scope를 포함한 ID로 변환해야 한다.
- PairJudgment: left/right, pair_hash, should_share_pending, reviewer, reason. pair_hash는 질문과 확정 문맥에 결속하며 변경된 입력의 검토를 재사용하지 못한다. 다른 매장/판본의 공유를 사람이 true로 써도 거절한다.
- precision: 예측한 묶음 쌍이 전부 검토됐을 때만 계산한다. 예측 묶음이 없으면 null. recall: 전체 질문 쌍이 검토되고 양성 분모가 있을 때만 계산한다. 보류된 양성도 miss로 남긴다.
- 보고서에 입력, 판정, 쌍별 결과, 평가기 source hash, report hash를 남긴다. `production_promotion=false`다. 소규모 검토 쌍의 성능을 전체 실서비스의 보장으로 쓰지 않는다.

CLI(API 디렉터리):

```powershell
python scripts/report_r_grouping.py --input <cases-assignments-judgments.json> --output <new-report.json>
```

출력은 배타 생성하여 과거 보고서를 덮어쓰지 않는다. 실자료는 기존 Git 제외 경로에서 다룬다. 질문 1~200개의 전체 쌍을 고정 분모로 다루며 미검토 쌍을 자동 음성으로 라벨링하지 않는다.

## 검증

- 전체 **685 passed / 119 subtests passed**. 기존 Starlette/AnyIO deprecation warning 1건.
- 변경 app 파일 4개 매장 격리 AST 위반 0건.
- RAW-only/typed+RAW 혼합·현재 제외·오래된 참조·중복·빈 근거 거절과 기존 typed oracle 회귀 통과.
- 묶음의 잘못 합침·보류·불필요한 분리·미판정·잘못된 scope·검토 후 문맥 변경·출력 분모 누락 반례 통과.
- 합성 4질문/6쌍을 실제 `decide`→`pending_key`→새 CLI로 연결했다. precision 1.0, recall 0.5, scope 위반 0. 지원 표현 쌍은 묶였고, 동일한 미지원 복합 질문 쌍은 분리돼 false split 1건으로 남았다. **실자료 성능 수치가 아니다.** 원시 입력/보고서는 `api/tmp/r-grouping-evaluation/`에 보존했다.

## 잔여 범위

이번에는 평가 사각지대를 수정했다. 자유 RAW의 의미 충분성·임의 복합 논리·자유로운 표현 간 의미 동치의 제품 지원을 새로 완료한 것이 아니다. R 단독 구현은 계속 가능하지만 이 기록으로 일반 의미 구현 전체나 R 전체 종료를 선언하지 않는다. Docker 통합, 실제 승인 snapshot 연결, 사람 검토 기반 실자료 평가는 여전히 별도다.
