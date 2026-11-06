# 입구 분류기 평가 세트

`cases.json` 은 합성 라벨 세트다. 메뉴·상호는 `음료Z`·`합성매장` 같은 합성 이름만 쓴다.
이미지·음성·영상 칸은 글 전사 표본으로 대신한다. 실제 자료는 Git 제외 경로에 두고
`--cases <경로>` 로 따로 받는다(브랜드·상호를 이 저장소에 남기지 않는다).

형식: `[{case_id, normalizer, hints, candidates:[{candidate_id, locator, text, expected}]}]`
자료 정답은 구간 정답의 다수결이고, 같으면 앞 구간을 따른다.

실행(기본 mock, 비용 0, 배선 확인용):

    cd api && python scripts/run_intake_classifier_eval.py [--out PATH]

실모델은 사용자 승인 뒤에만 `--real --confirm-paid` 로 돌린다(원장 목적 EVALUATION).
mock 실행의 정확도는 모델 성능이 아니다.

실제 자료 라벨은 `api/eval/intake/private/` 아래(.gitignore 로 Git 제외)에 두고
`--cases api/eval/intake/private/<파일>` 로 넘긴다.

## 한 호출 비교 (`--single-call`)

    cd api && python scripts/run_intake_classifier_eval.py --single-call [--out PATH]

사례마다 후보 글을 이어 붙인 한 글로 `extract_facts_with_intake`(분류+추출 한 호출)를 부르고,
`intake_ranking` 으로 자료 판정을 만들어 같은 지표로 채점한다. 구간 정확도는 모든 구간에
같은 판정을 준다. 전체 글자가 `intake_probe_text_chars` 이하인 작은 사례만 쓰고, 쓴 사례 수와
뺀 사례 수를 보고서에 적는다. 기본은 mock(비용 0, DB·네트워크 없음)이며 유료 규칙은 위와 같다.

### 켜기 전 비교 절차 (사용자 승인 뒤 실행)

1. 같은 작은 사례에서 분리 경로(`분류 1회 + 추출 1회`)와 한 호출을 각 3회씩 돌린다(D17).
2. 용도 판정 정확도, 사실 수·참조 대비 재현, 토큰·USD 를 나란히 적는다.
3. 한 호출이 판정 정확도에서 떨어지지 않고 비용이 줄면 `INTAKE_SINGLE_CALL_SMALL=true` 를 켠다.
