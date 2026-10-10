## name

영상 — mp4·mov·avi
## step_examples

처음부터 끝까지 봄 / 음성 전사 / 프레임 추출 / 화면 속 글자·동작 확인 / 구간 반복 재생 / 재검증
## why_example

"말로는 '적당히'라 했는데 화면에 계량컵 눈금이 보여 프레임을 확대"
## meta_amount

"duration_sec": 전체 길이(초),
## locator

{"kind": "TIME", "start_sec": 시작 초, "end_sec": 끝 초, "source": "SPEECH / SCREEN / BOTH"}
## rules

- 말에만 있는 사실과 화면에만 있는 사실을 locator.source로 구분하세요.
- 동작만 보이고 말이 없는 단계도 화면에서 확인되면 사실로 적으세요.
## checks

- 말과 화면이 서로 다른 곳은? (예: 말은 2번, 화면은 3번)
- 화면에만 나온 수치·순서를 빠뜨리지 않았는가?
## input_note

[첨부] 영상 파일(mp4·mov·avi)을 이 메시지에 첨부했습니다.
