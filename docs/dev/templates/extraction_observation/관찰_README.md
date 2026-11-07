# Phase 0 — 외부 모델 관찰 실행 안내 (이 문서만 보고 시작)

> 이 파일은 `추출결과/관찰/README.md` 로 복사돼 쓰인다(원본: `docs/dev/templates/extraction_observation/관찰_README.md`, `--scaffold` 가 복사).
> **Claude Code·Codex 어느 세션이든 "추출결과/관찰/README.md 보고 시작해줘" 라고 하면 아래 '세션이 하는 일' 을 그대로 따른다.**
> 이 폴더(`추출결과/`)는 Git 에 올라가지 않는다. 원본·결과를 그대로 넣어도 된다. 저장소 문서·커밋에는 익명 id 만 쓴다.

## 목적
강한 모델이 카페 업무 자료에서 사실을 **스스로 어떻게** 뽑는지(작업 기록)를 같은 조건으로 여러 번 받아, 공통 처리 순서를 보고 우리 로직별 추출기를 설계한다(로드맵 `docs/dev/plan/W_FACT_ONLY_ROADMAP_20261010.md` Phase 0 → Phase D).
실행은 칸마다 4개: **Claude Opus 5.5 · Claude Sonnet 5.5 · GPT Sol 6.1 · GPT Luna 6.0** 각 1회. Sonnet·Luna 는 "Opus·Sol 이 아니어도 되는 작업인가" 를 보려는 것이다.

## 요금 — 구독으로 돈다
- **Claude Code**: 구독 로그인(Claude Pro/Max)으로 돈다. API 키를 쓰지 않는다(실행 기록 `apiKeySource: none`, 2026-10-10 확인). 실행기는 `ANTHROPIC_API_KEY` 를 일부러 넘기지 않는다.
- **Codex**: ChatGPT 로그인(`~/.codex/auth.json` 의 `auth_mode: chatgpt`)으로 돈다. API 키 없음.
- 둘 다 **구독의 사용 한도**를 쓴다(돈이 따로 나가지 않음). 예외: `--stt` 전사는 OpenAI API(whisper-1, 유료).
- 기록되는 "API 환산" 금액은 같은 일을 API 로 했을 때의 비교용 추정이다. 실제 청구가 아니다.

## 시간·토큰은 "순수" 값으로 잰다
CLI 자체의 기본 지시(시스템 프롬프트·도구 정의, 호출마다 수만 토큰)와 CLI 기동 시간은 빼고, **자료 입력 + 지시문 + 모델 작업**만 기록한다.
- **기준 측정**: 실행 전에 같은 도구·모델·격리 설정으로 "OK 만 출력" 을 한 번 보내, 호출 1회의 기본 지시 토큰을 잰다 → `_baseline.json`(모델마다 한 번, 구독 사용량 아주 조금). 모델·CLI 를 바꾸면 그 줄을 지워 다시 잰다.
- **순수 입력 토큰** = 호출마다 (그 호출의 입력 토큰 − 기본 지시 토큰) 의 합. Claude 는 호출별 기록으로 정확히, Codex 는 턴 합계를 호출 수(도구 실행 수 + 1)로 나눈 **추정**(`calls_estimated`).
- **출력 토큰** = 모델이 낸 토큰 전부(생각 포함).
- **순수 시간** = CLI 기동이 끝난 시점(Claude `system init` / Codex `thread.started`) → 마지막 이벤트. 기동 포함 벽시계 시간은 `meta.json` 의 `wall_sec_including_startup`.
- **API 환산(상한)** = 순수 입력 × 입력 단가 + 출력 × 출력 단가, 캐시 할인 무시(Claude 만: Opus 5.5 $4/$20, Sonnet 5.5 $2/$10 per 100만). GPT 단가는 모름 → 토큰만.
- 모두 `<실행>/meta.json` 의 `measure` 와 `RUN_SHEET.md` 에 남는다.

## 사람이 하는 일
1. 자료를 넣는다: `<번호_로직>/<번호_형식>/자료1/원본/` 에 파일(여러 개면 모두). 같은 칸에 자료가 더 있으면 `자료1` 을 통째로 복사해 `자료2` 로(안의 결과 파일은 비우기).
   - 로직: `01_RECIPE_레시피` `02_PROCEDURE_업무절차` `03_POLICY_운영규칙` `04_REFERENCE_매장정보` `05_NOTICE_공지일정`
   - 형식: `01_DOC_TEXT_문서글자`(pdf 글자·docx·hwp·txt) `02_DOC_IMAGE_문서이미지`(스캔 pdf·사진) `03_AUDIO_음성` `04_VIDEO_영상` `05_CHAT_카톡` `06_OWNER_TEXT_점주답변`
   - 30칸을 다 채울 필요 없다. 로직마다 실제로 많이 올라올 자료 1~2개. `01_RECIPE_레시피/02_DOC_IMAGE_문서이미지` 는 예전에 관찰했다.
2. **점주답변 칸만:** 그 칸의 `지시문.md` 안 `직원 질문: (여기에 …)`·`점주 답변: (여기에 …)` 를 실제 글로 바꾼다. 바꾸지 않으면 실행기가 그 칸을 건너뛴다.
3. 세션에 "`추출결과/관찰/README.md` 보고 시작해줘" 라고 한다.

## 세션이 하는 일 (Claude Code 든 Codex 든 같다)

빠른 길(사용자가 직접 터미널에서 돌려도 된다, 저장소 루트):
```bash
api/.venv/bin/python api/scripts/run_observation.py --list          # 할 일 확인
api/.venv/bin/python api/scripts/run_observation.py --max 4         # 첫 칸 4실행(기준 측정 자동)
api/.venv/bin/python api/scripts/run_observation.py --stt --max 4   # 음성·영상 칸이면 전사 먼저(유료)
api/.venv/bin/python api/scripts/run_observation.py                 # 남은 것 전부
```

저장소 루트에서 실행한다. 실행기는 `api/scripts/run_observation.py` 하나다. **세션이 직접 자료를 읽거나 추출하지 않는다** — 그건 실행기가 띄우는 별도 실행의 몫이다(생성과 분석을 섞지 않음).

1. **할 일 확인:** `api/.venv/bin/python api/scripts/run_observation.py --list` → 칸·실행 목록과 개수를 사용자에게 보여 준다.
2. **음성·영상 칸이 있으면 전사 여부를 사용자에게 한 번 묻는다**(유료: whisper-1 약 0.006 USD/분, 10분 영상 약 0.06 USD). 승인되면 `--stt` 를 붙여 실행하면 각 자료의 말이 `원본_전사/` 에 한 번 만들어지고, 네 실행 모두 같은 전사본을 `./input/_전사/` 로 받는다. 거절하면 전사 없이 돈다(영상은 화면만 보고 뽑게 됨). 금액은 실행기가 출력한 값으로 사용자에게 보고한다.
3. **명령 미리보기:** `--dry-run` 으로 명령이 아래 '격리 규칙' 대로인지 확인한다.
4. **실행:** `api/.venv/bin/python api/scripts/run_observation.py [--stt] [--max N] [--only PROCEDURE] [--runs claude-opus-5.5,...]`
   - 구독 한도를 쓴다(API 요금 아님, 단 전사는 유료). Opus·Sol 실행 하나가 5시간 한도의 상당 부분을 쓸 수 있다 — 처음엔 `--max 4` 로 한 칸만 돌리고 사용자에게 한도 사용량을 확인받은 뒤 이어간다.
   - 실행은 차례로(동시 아님). 실행 하나 상한 3시간.
   - 실행기는 **긴 작업**이다. Claude Code 세션이면 Bash 를 백그라운드로 돌리고 끝나면 이어서 보고한다.
5. **결과 확인·보고:** 실행마다 칸 폴더의 `<실행>/meta.json` 을 읽어 사용자에게 표로 보고한다 — 걸린 시간, 결과 건수, 종료 코드, `audit.suspect`(격리 위반 의심), 토큰·비용 상당액. `suspect` 가 참이면 `outside_paths`·`network` 를 보여 주고 그 실행을 분석에서 뺄지 묻는다(결과 파일을 비우면 다음에 다시 돈다).
6. 실패(`RUN_SHEET` 메모에 "종료 코드", "result.json 없음/깨짐", "작업 기록 미완")는 `stderr.txt`·`transcript.jsonl` 끝부분을 보고 원인을 보고한다. 같은 실행을 다시 돌리려면 그 실행 폴더의 `result.json` 을 비운다.
7. 한 칸에 실행이 3개 이상 모이면 사용자에게 "분석할까요?" 를 묻는다. 분석은 **새 세션**에서 `docs/dev/templates/extraction_observation/README.md` 의 "Claude Code 세션이 하는 순서" 대로 한다.

## 격리 규칙 (기존 지식이 새지 않게 — 실행기가 강제)
모든 실행은 **같은 환경에서 원본만 보고 같은 지시문으로** 추출한다.
- 실행마다 **저장소 밖 새 폴더** `/tmp/askbuddy-observe/<시각>-<실행>/` 를 만들고 `input/`(원본 복사, 전사본은 `input/_전사/`)·`out/` 만 둔다. 저장소·예전 결과·다른 실행 결과는 그 폴더에 없다.
- 프롬프트 = 칸의 `지시문.md` 그대로 + 모든 실행 공통 '실행 환경 안내'(입력 위치, 출력 파일, 폴더 밖·인터넷 사용 금지).
- **Claude Code:** `claude -p --setting-sources local --strict-mcp-config --no-session-persistence` — 사용자 설정·플러그인·MCP·CLAUDE.md 를 읽지 않고, 자동 기억은 새 폴더라 비어 있다(2026-10-10 확인). 웹 검색·웹 가져오기·하위 에이전트·아티팩트 도구는 끈다.
- **Codex:** 실행마다 새 `CODEX_HOME`(로그인 파일만 복사) + `--ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check --sandbox workspace-write` — 기억·AGENTS.md·설정 없음, 네트워크 없음(2026-10-10 확인).
- API 키 환경 변수(`OPENAI_*`·`ANTHROPIC_*`·`GEMINI_*`)는 실행에 넘기지 않는다.
- 실행 뒤 **감사:** 모델이 실행한 명령·도구 입력에서 작업 폴더 밖 경로나 인터넷 사용(curl·wget·http)이 보이면 `meta.json` 의 `audit.suspect=true`, `RUN_SHEET.md` 메모에 "격리 위반 의심".
- 모델 id: `claude-opus-5-5`·`claude-sonnet-5-5`(Claude Code), `gpt-6.1-sol`·`gpt-6-luna`(Codex, `~/.codex/models_cache.json` 에서 확인). 추론 수준은 모두 `high`. 바꾸면 `run_observation.py` 의 `RUN_MATRIX` 와 이 문서를 함께 고친다(이미 돈 칸과 섞이지 않게 기록).
- Codex 실행 파일: PATH 의 `codex`, 없으면 VS Code 확장(`~/.vscode/extensions/openai.chatgpt-*/bin/*/codex`) 의 최신 것, 또는 환경 변수 `CODEX_BIN`.
- 알려진 표시: Claude CLI 는 결과가 성공이어도 종료 코드 1 을 낼 때가 있다 — 실행기는 최종 결과 이벤트(`result_ok`)로 판정한다. 긴 파일 쓰기가 잘린 적이 있어(작업 기록이 중간에 끊김) 안내 문구에 "나눠 쓰고 끝까지 확인" 을 넣었고, `worklog.md` 에 "3부" 가 없으면 "작업 기록 미완" 으로 표시한다.
- 알려진 표시: Claude Code 가 `stderr.txt` 에 `unrecognized_model claude-sonnet-5-5` 를 남길 수 있다 — CLI 모델 목록 표시 문제이고 실제 응답 모델은 transcript 의 `"model"` 로 확인된다(2026-10-10 확인). Claude Code 가 내부 요약용으로 Haiku 를 아주 조금 쓴다.

## 폴더 모양 (칸 하나)
```
<번호_로직>/<번호_형식>/자료1/
  지시문.md            모든 실행이 받는 지시문(점주답변 칸은 질문·답변을 채움)
  원본/                사용자가 넣는 자료
  원본_전사/           --stt 로 만든 전사본(음성·영상만)
  RUN_SHEET.md         실행기가 실행마다 한 줄 채움
  claude-opus-5.5/  claude-sonnet-5.5/  gpt-sol-6.1/  gpt-luna-6.0/
      result.json      2부 JSON(비어 있으면 아직 안 돈 실행)
      worklog.md       1부 작업 기록 + 3부 자기 점검
      meta.json        시간·건수·토큰·비용 상당액·격리 감사
      transcript.jsonl 실행 전체 기록(도구 호출 포함)
      stderr.txt       있으면 오류 출력
      captures/        (손으로 데스크톱에서 돌렸을 때 화면 캡처용)
```

## 손으로 돌리고 싶을 때(데스크톱 앱)
`지시문.md` 를 전부 복사 → 앱 새 대화에 붙여넣고 원본 첨부 → 답의 2부 JSON 은 `result.json`, 1부·3부는 `worklog.md` 에 붙여넣기 → `RUN_SHEET.md` 그 줄을 손으로 채우고 메모에 "데스크톱 앱" 이라고 적는다(자동 실행과 조건이 다르다).

## 다시 만들기
폴더가 지워졌으면 `api/.venv/bin/python api/scripts/build_observation_instruction.py --scaffold`(있는 파일은 덮지 않음).
