# 미등록 자유 표현의 일반 의미 판단 경로 — 2026-09-19

`713697c` 이후 R 단독 구현. 사용자 요청은 기본 OFF 구현·합성 검증이며 사람 정답 검토/유료 평가/운영 활성화의 대기 해제를 뜻하지 않는다.

## 이번에 달라진 점

기존 reviewed catalog는 질문·문맥·승인판·후보가 검토 입력과 정확히 일치해야 했다. 이번 `general_semantics.py` 경로는 **질문별 사전 등록 없이** 현재 질문과 검증된 사용자 문맥, 승인 검색 후보로 모델이 행동·해석·참조를 제안한다. 운영에서 쓰려면 질문별 승인이 아닌 **해당 모델·코드·매장 승인판에 대한 품질 인수**가 필요하다.

서버는 기존 명시 planner와 reviewed catalog를 먼저 적용한다. 결과가 ESCALATE이고 정책 응답이 아닌 경우에만 일반 해석을 시도한다. 기존 ANSWER/CLARIFY/정책 결과를 덮어쓰지 않는다. 확인되지 않은 문맥은 사용하지 않는다.

1. 모델 제안: GeneralProposal은 기존 AnswerPlan에 entity/predicate/variant/필수 fact 해석과 조건·예외별 사용자 인용을 덧붙인다. 자유 답변/assessment/임의 추가 필드는 받지 않는다.
2. 서버 검사: 매장·snapshot/input hash·후보·참조·확정 entity/predicate/variant의 충돌, 조건/예외의 누락·변조·사용자 인용 존재, dependency closure·단위·RAW 참조를 검사한다. 조건·예외와 RAW ID는 승인 snapshot에서 가져와 서버 assessment를 만든다. 모델 슬롯을 사용자 확정값으로 저장하거나 질문을 자동 병합하지 않는다.
3. 별도 모델 검증: 같은 모델의 별도 호출에서 후보 전체와 제안을 다시 읽고 의미·조건·수치 예외·부정·RAW 완전성·후속 문맥을 점검한다. 판정은 정확한 검증 입력 hash와 검사한 fact/RAW 집합에 결속된다. 두 호출의 오류가 통계적으로 독립이라는 뜻은 아니다.
4. 저장: 검사한 Decision을 기존 `save_answer`에 전달한다. 저장 직전 현재 공개판·선택 카드 상태·권한·문맥·참조 검사를 다시 거친다. 승인 renderer로 답변하고 인용·원가·release/input/proposal/verification hash를 남긴다. 같은 요청은 저장된 결과를 재생한다.

불확실하거나 별도 검증이 거절하면 기존 이관 결정을 유지한다. 잘못된 schema/참조/검증 hash는 503, 시간 초과는 504, 평가 예산 거절은 기존 429로 처리한다. 인프라·구조 오류를 지식 부족으로 바꿔 pending을 생성하지 않는다.

## 지원 범위와 한계

- 자유 표현과 제목 없는 RAW는 모델 제안 및 별도 의미 검증의 입력이다. 서버는 RAW를 임의 재서술하지 않는다.
- 중첩/수치 조건·예외는 승인 문구 전체와 사용자 원문 인용을 요구한다. 누락/새 조건/없는 인용을 차단하지만 **인용이 의미상 그 조건을 충족하는지까지 결정론적으로 증명하지는 않는다.**
- 후속 질문은 기존 서버가 검증한 원래 질문·현재 응답·확정 슬롯만 사용한다. 모델의 UUID 대신 서버 context ID를 사용한다.
- 새 명확화는 승인 후보에 실제 존재하는 temperature/size의 전체 선택지로 제한하고 최대 2회 규칙을 유지한다. 자유형 질문/임의 entity 선택지를 생성하는 명확화는 이번 범위가 아니다.
- 모델 제안과 검증이 함께 틀릴 수 있다. 구조 통과를 사람 정답으로 표시하지 않으며 감사 상태도 `STRUCTURE_AND_MODEL_CHECKED`다. 실자료 오답·과차단·문맥·인용 품질 인수는 남아 있다.

## 활성화·호출 제어

`R_GENERAL_SEMANTICS_ENABLED=false`가 기본이다. 켜더라도 `R_GENERAL_SEMANTICS_PATH`의 private release 파일과 별도 `R_GENERAL_SEMANTICS_HASH`가 없거나 불일치하면 호출 전에 차단한다. release는 다음 정보를 고정한다.

- schema_version `r-general-release/v1`, store_id, snapshot_hash.
- `source_hash()`가 계산한 해석·검증·저장·renderer·문맥·예산 관련 코드 hash, model.
- acceptance_reference, approved_by, timezone이 있는 valid_until.
- max_input_tokens, max_output_tokens, max_prompt_bytes.

**이 기록은 검증 결과 자체나 전자서명이 아니다.** 담당자가 실제 사람 판정·반복/A-A·비용/지연 인수 결과와 대조해 배포해야 한다. 이번에는 합성 테스트용 임시 release만 만들었고 실제 release 파일이나 설정을 설치하지 않았다. 새 snapshot/code/model에는 새 인수가 필요하다. 플래그 OFF로 기존 처리로 돌아가며 데이터는 삭제하지 않는다.

provider는 schema를 포함한 동일 prompt의 count_tokens 후 출력 상한을 설정한다. SDK 재시도는 1회이고 단계별 durable usage를 호출 전에 남긴다. 최대 제안 1회+검증 1회이며 기존 v2 전체 시간 예산 안에서 실행한다. 각 호출 전 만료를 재검사한다. 평가 scope에서는 두 호출 모두 기존 통합 campaign 예산을 예약하고 미설정/초과를 거절한다. 제품 호출은 인수 release와 기존 요청 제한·원가 계측·토큰/시간 제한을 따른다. 실제 요율·평가 예산은 정하지 않았다.

## 검증

- 합성 단위: 기본 OFF/기존 결과 보존/미검증 문맥 무호출, release hash/만료/매장/코드/모델 불일치 차단, 질문 인용·후보·병합·확정 문맥·RAW·정책 반례, 불확실성과 timeout/구조 오류 구분.
- 중첩 수치 조건·예외 누락, 없는 사용자 인용, 규격 근거, 명확화 선택지·서버 context ID·횟수 제한 검사.
- 실제 공급자 adapter를 합성 SDK로 검증: 평가 예산 필수, 출력 한도 적용, 사용량 정산.
- 격리 DB/API: 질문별 catalog 없는 서로 다른 미등록 표현 두 개의 답변·인용·감사 metadata·원가 저장, 모델 2회 호출, 동일 요청 무재호출, 잘못된 참조의 답변/pending 미생성 확인. 기존 migration·권한·현재판·문맥·멱등성·보존 회귀도 실행했다.
- 1차 전체 832 tests/4 xfailed/119 subtests 이후 추가 조건/SDK 검증까지 해당 23 tests 통과. 최종 순수 R 커밋의 집계는 CI 결과를 따른다.

구현 경로는 준비됐으며 **실제 품질 인수와 운영 활성화는 미완료**다. 사람 정답·실제 승인 snapshot·평가 예산/합격 기준 결정 후 격리 평가를 진행하고, 통과 범위만 활성화한다. W 실제 worker 공동 인수와 운영 설정 확인도 별도다.
