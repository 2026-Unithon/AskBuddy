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
