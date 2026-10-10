## name

문서(글자) — pdf(글자 있음)·docx·hwp·txt
## step_examples

원본을 그대로 봄 / 텍스트 레이어·문서 구조 추출 / 표를 행 단위로 전사 / 코드로 변환 / 재검증
## why_example

"표가 두 쪽에 걸쳐 있어 행 번호를 이어 붙임"
## meta_amount

"amount": {"pages": 쪽 수, "paragraphs": 문단 수 또는 null},
## locator

{"kind": "PAGE", "page": 쪽 번호, "paragraph": 문단 번호 또는 null}
## rules

- 문서에 박힌 그림·표 이미지 안의 글자도 읽어 사실로 적고, 읽지 못하면 meta.unreadable에 적으세요.
## checks

- 문서의 표·목록 행 수와 뽑은 행 수가 맞는가?
## input_note

[첨부] 문서 파일(pdf·docx·hwp·txt)을 이 메시지에 첨부했습니다.
