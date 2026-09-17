# R 단독 후속: 실자료 준비·질문 조건·의미 묶음

2026-09-16, HEAD `4212fec` 위의 기존 R 미커밋 작업을 보존하고 진행했다. 기준은 MVP §31, C0 §5.1~5.3, DEV_TODO R0/R3/R5다. 실자료 수입이 R 전체 완료나 의미 성능 향상을 뜻하지 않는다.

## 구현과 계획 대조

| 항목 | 완료한 범위 | 경계 |
|---|---|---|
| 질문 조건 보존 | 수량·위치·가격·개수의 지원 문형을 질문 전체와 대조한다. 대체 재료·배수·할인·마감 이후 같은 미지원 수식어를 무시하고 기본 사실을 답하지 않는다. planner 버전 `r-explicit-slots/v3` | 정규식으로 일반 한국어 의미 판정을 완료했다고 하지 않는다. 지원 문형 밖은 ESCALATE이며 비교/복합 질문의 과도한 차단은 실제 평가가 필요하다 |
| 자동 의미 묶음 | 명시한 대상·우유/물 속성·HOT/ICE가 같고 조건·예외·선행·크기 축이 없는 단순 질문만 묶는다. 원래 질문 occurrence와 receipt는 각각 보존한다 | 문맥 추정·유사도·모델 단독 판정으로 묶지 않는다. 일반 바꿔 말하기는 미지원 |
| 묶음 저장 방어 | 서버 생성 결과를 저장 시 질문·resolved selection·snapshot과 다시 대조한다. 기존 내부 v1 의미키는 보존한다 | 새 키는 store와 snapshot ID/revision/hash에도 결속한다. 공개판이 달라지면 묶이지 않는 보수적 세분화이며 W wire 계약 변경이 아니다 |
| 실자료 R 검토 준비 | 개발 매장만 읽고 원본 파일 SHA-256, 사실별 의미 ID·출처 라벨·질문 초안을 보존한다. 미확인 규격·조건은 null/UNREVIEWED로 둔다 | W 사실 truth를 승인 카드, R 행동 정답, 점주 확인으로 변환하지 않는다 |
| 사람 검토 수입 | source review hash·사람 질문/행동/적용 범위·금지 주장·필수 표시·승인 fact/revision 및 prerequisite를 검사하고 기존 EvaluationManifest에 연결한다 | 수입은 의미 정답률 측정이 아니다. 미검토/누락/다른 snapshot 참조는 거절한다 |
| 질문 모집단 | 대표 질문을 사전에 선택할 수 있고 선정 이유·전체 사실 수·제외 목록을 남긴다. 선택한 질문은 전부 검토해야 한다 | 사실 180건이 질문 180개라는 강제 규칙을 추가하지 않았다. W 사실 must_have와 R 질문 must_have는 별도 검토다 |

계획의 '확정 슬롯만 묶기', '필수 문맥을 삭제하지 않기', '미판정 분모 유지'를 적용했다. 미지원 의미를 추정으로 승인하는 대안보다 현재 단계에 적합하다. 문형 제한으로 답변율이 떨어질 수 있으므로 안전 회귀 통과를 성능 개선 수치로 해석하지 않는다. 코드·문형 변경이 평가 실행 provenance에 포함되도록 단일/다회 수집기의 source hash 목록도 보강했다.

## 실자료에서 확인한 사실

| 개발 자료 | 사실 수 | W 사실 must_have | variant 값 없음 | 출처 정답 상태 |
|---|---:|---:|---:|---|
| store-a | 132 | 113 | 67 | TEAM_TEST |
| store-b | 48 | 37 | 33 | TEAM_TEST |

기존 manifest/facts 구조 검사 및 브랜드 누출 검사 모두 문제 0건. 규격 값 없음 100건은 오류 100건이라는 뜻이 아니며 적용 범위 확인 대상으로 남긴다. 사람 판정자·판정일은 존재하지만 TEST는 점주 확인이 아니다.

전달 자료의 JSON은 원본 목록·사실 정답·익명화 매핑이며, SQL dump는 evaluation_runs/results/cases 이력이다. R 승인 PublishedKnowledgeSnapshot 또는 질문 행동 검토를 대신하지 않는다. SQL은 DB에 복원하지 않았다. holdout은 읽지 않았다.

생성 결과는 `api/eval/data/store-a/r-review/`와 `store-b/r-review/`에만 저장했고 Git 제외를 확인했다. 공개 문서에는 매장명·메뉴명·실제 주장·질문을 복사하지 않았다.

## 사용법

API 작업 디렉터리에서 필요한 Python 의존성을 설정한 후:

```powershell
python scripts/prepare_r_dev_review.py --store store-a
```

`review-<hash>.json`을 배타 생성한다. 같은 입력의 기존 결과는 덮어쓰지 않는다. `question_draft`는 검토 보조이고 실행 질문이나 정답이 아니다.

검토자는 같은 비공개 `r-review/`에 `judgments.json`과 실제 승인 `approved_snapshot.json`을 제공한다. 제출 형식은 `{ "review_hash": "...", "judgments": [...] }`이며 대표 질문 선택 시 `selected_meaning_ids`, `selection_reason`도 지정한다. judgment 필드는 `ReviewedCase`를 따른다: meaning_id, question, expected_action, must_have, applicability, conditions, exceptions, scope_reason, forbidden_claims, required_fact_revisions, reviewer, reason. 비답변은 UNDETERMINED와 빈 근거를 명시할 수 있지만 ANSWER는 허용하지 않는다.

```powershell
python scripts/finalize_r_dev_review.py --store store-a --store-id 1 --truth-version <검토버전>
```

store-id는 실제 격리 평가 snapshot의 매장 ID로 지정한다. 원본을 다시 hash하므로 검토 후 원본 변경은 기존 review hash와 맞지 않아 거절된다. 출력 `manifest-<hash>.json`의 `manifest`를 기존 v2 수집기에 전달하고 나머지 provenance/mapping도 함께 보존한다. 실행 결과의 정답 여부는 기존 row_hash에 묶인 별도 사람 검토가 필요하다.

## 검증

- 전체 단위: **619 passed, 119 subtests passed**. 기존 Starlette/AnyIO deprecation warning 1건.
- PostgreSQL **17.11**, 일회용 Docker DB에서 **26 migration** 재구축과 R 인수 runner 통과.
- 실제 v2 HTTP/API **101 checks**: 새 planner의 동일 질문 묶음, occurrence 2건, 알림 1건, 복합 조건 질문 비답변을 포함한다. 기존 인증·매장/회원 격리·재시도·문맥·stale·원가·owner delivery도 통과했다.
- 변경 app 파일 7개 매장 격리 AST 검사 위반 0건.
- 실자료 2개 매장, 180건 구조/누출 검사 0건. 이는 사실 내용 정확성 검증이 아니다.
- 최초 DB runner는 PYTHONPATH 누락으로 asyncpg import 단계에서 실패했고, 의존성 경로 지정 후 재실행 및 최종 코드 재검증을 통과했다. 모든 검증용 컨테이너는 runner finally에서 정리됐다.

재현 명령은 기존 `verify_r_handoff.ps1 -IncludeSchemaRebuild -IncludeUnitTests`다. 운영 DB 변경·배포·유료 모델 호출·commit/push는 수행하지 않았다.

## 남은 작업을 구별한다

1. **R 의미 기능/평가**: 일반 RAW 업무 질문, 복합 조건·예외 판단, 폭넓은 의미 중복 묶음은 아직 완성되지 않았다. R 검토 질문/행동/근거와 적용 범위 표본을 먼저 확정해야 지원 범위를 안전하게 확대하고 false abstention을 잴 수 있다. 단순 문형 구현으로 이 항목들을 완료 표시하지 않는다.
2. **사람 검토**: 전달된 사실 정답과 별도로 R 질문·기대 행동·규격/조건 및 필수 질문 선정을 검토해야 한다. 초안과 수입 도구는 준비됐으며 모델이 자신의 초안을 정답으로 승인하지 않는다.
3. **W 공동 인수**: 실제 승인 snapshot 및 안정 fact/card revision 매핑, 실제 공개/제외 교체와 ApplyOwnerAnswer 후속 발행 연결.
4. **실자료 성능**: 위 입력으로 lexical/vector/pooling/oracle, 사전/reranker 비교, 반복 A/B·A/A, 비용·지연을 측정한다. 현재 결과에 실자료 정답률이나 개선율을 붙일 수 없다.

R 단독 기반 작업을 추가 완료했지만 R 전체 또는 일반 의미 판단 완료 선언은 아니다. 다음 실행 입력이 없다는 이유로 W 사실 라벨을 R 승인 snapshot으로 조작하지 않는다.
