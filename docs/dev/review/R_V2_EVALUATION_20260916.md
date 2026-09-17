# R0 v2 단일 질문 평가 수집·보고

2026-09-16. `4212fec`와 미커밋 R 구현 기준. dev의 평가 도구 작업이며 release 기능·사용감·배포 작업이 아니다.

## 구현

- `app/team/v2_evaluation.py`: manifest의 질문 ID·질문·기대 행동·must_have·필수 사실·금지 주장을 보존한다. snapshot ID/revision/hash와 truth 버전을 명시한다. 중복 ID와 빈 질문을 거절한다.
- `collect_v2_run`: 호출자가 제공한 격리 HTTP client로 질문마다 세션 생성 후 v2 chat을 실행한다. 자동 재시도나 실패 행 삭제를 하지 않는다. 5행동을 그대로 수집하고 API 오류·전송 오류·응답 계약 오류·snapshot 불일치를 구분한다. request/receipt ID, 실제 응답, HTTP 상태·오류 코드, 세션 생성 포함 관측 지연을 저장한다.
- 실행/manifest/설정/행 hash와 주요 실행 소스 hash를 기록한다. 실행 중 소스 변경은 보고 단계에서 거절한다. snapshot hash는 사전 manifest 값이며 HTTP에서는 ID/revision을 대조한다. 내용 hash 자체의 검증은 호출 환경의 승인 snapshot 확인이 필요하다. 이번 DB 인수는 실제 승인 fixture와 durable receipt를 대조했다.
- `build_v2_report`: 행동 일치율과 의미 정답을 분리한다. 의미 정답은 recorded ANSWER에만 검토자가 붙일 수 있다. block_precision은 CLARIFY/ESCALATE의 knowledge_block·block_correct 판정을 별도로 요구한다. 사람 판정 없는 ANSWER는 미판정이다.
- `paired_gate_input`은 기대 ANSWER인 고정 질문 집합만 포함한다. 명확한 비답변/API·전송 실패는 False, 미검토 ANSWER 및 수집 계약 오류/snapshot 불일치는 None이다. 필수 답변 질문 ID도 함께 제공한다. 정책 행동을 정답 답변 증가로 계산하지 않는다.
- 검토 파일은 question_id와 row_hash로 정확한 출력에 연결한다. 다른 실행 출력·중복/분모 밖 검토·빈 검토자/이유·부적절한 action 판정을 거절한다. hash는 오연결 검출이며 검토자 인증이나 전자 서명이 아니다.
- `scripts/report_r_v2.py`: 저장된 실행과 선택적 검토 JSON에서 보고서를 재생한다. 새 출력 파일만 허용한다. API/모델을 호출하지 않는다.

## 실행과 검토

격리 실제 DB/API 수집 인수는 기존 `verify_r_handoff.ps1 -IncludeSchemaRebuild -IncludeUnitTests`에서 실행된다. 테스트 환경은 `PYTHONPATH=api/tmp/test-deps`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTEST_PLUGINS=pytest_asyncio.plugin`을 사용했다. 산출물은 Git 제외 `api/tmp/r-v2-evaluation/<run_id>-run.json`, `-report.json`이다. DB와 provider 응답은 각각 실제 격리 PostgreSQL과 명시적 합성 adapter다.

오프라인 재생:

```powershell
python api/scripts/report_r_v2.py --run <새로운-run.json> --output <새로운-report.json>
python api/scripts/report_r_v2.py --run <run.json> --judgments <검토.json> --output <새로운-reviewed-report.json>
```

검토 파일은 배열이며 각 항목에 `question_id`, 해당 실행 행의 `row_hash`, `reviewer`, `reason`을 넣는다. 의미 답변 판정에는 `semantic_correct: true/false`, 지식 차단 판정에는 `knowledge_block: true/false`와 필요한 경우 `block_correct: true/false`를 쓴다. 미검토 항목은 생략 또는 null로 유지한다. 필수 사실·금지 주장·조건·규격을 검토자가 대조해야 하며 도구가 낱말 일치로 자동 확정하지 않는다.

수집기는 세션과 pending을 생성할 수 있으므로 격리 평가 client만 연결한다. 일반 운영 호출 CLI는 추가하지 않았다. LIVE provider 실행, 평가 원가 귀속, 실제 모델/prompt/단계 지연의 원장 결합은 후속이다. 현재 보고의 cost_status는 항상 UNKNOWN이며 production_promotion은 false다. 호출자 configuration은 추적 정보이고 실제 환경을 자동 증명하지 않는다.

## 검증

- 전체 단위 **525 passed / 110 subtests passed**, 기존 deprecation 경고 1개. 신규 평가 테스트 10개와 오류 유형 하위 사례 4개 포함.
- 실제 PG17.11 **26 migrations**, DB/API **205 PASS 체크**. 종전 198 + 추가 provider 연결 경계 3 + 평가 인수 4. 고유 사용자 시나리오 수가 아니다.
- 합성 6문항: ANSWER/CLARIFY/ESCALATE/REFUSE/SAFE_ROUTE 각 1개와 의도적 timeout 1개. 질문 6개 모두 보존, 답변 가능 분모 2개 중 정상 ANSWER는 None·timeout은 False. grounded_answer_rate는 null이다. 이는 품질 점수가 아니다.
- 모든 정상 수집 응답을 실제 DB receipt의 응답·원문과 대조했다. 산출물 생성 후 별도 보고 CLI로 재생하여 질문 수 6·미판정 답변 1개를 확인했다.
- 응답 변조·삭제된 행·다른 출력의 검토·중복 검토·snapshot 불일치·취소 전파·소스 변경·차단 판정 분리 반례 통과. 매장 격리 정적 검사 1파일 위반 0, git diff --check 통과.
- 일회용 Docker/DB는 정리했다. 유료 호출·운영 DB·프런트 수정·브라우저 신규 검증·커밋·푸시는 없다.

## 완료 경계

이번 완료는 단일 질문의 실제 v2 API 수집→고정 분모/미판정 보고 접점이다. R0 전체·30~50문항 실자료 품질·다회 대화·후보 pooling/oracle·반복 A/B 캠페인 검증·원가/지연 승격은 완료가 아니다. 다음 dev 항목은 반복 실행의 manifest/설정/버전 동일성 검사와 기존 paired gate의 결합이다. release 인수 항목은 변경하지 않았다.
