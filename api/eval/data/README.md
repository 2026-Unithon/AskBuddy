# 평가 자료 — 넣는 법

> 이 폴더는 **Git 제외**다 (`SPLIT.md` 만 예외).
> 브랜드명·상호·로고를 파일명·JSON·DB 어디에도 쓰지 않는다. 익명 slug 만 쓴다.

## 1. 파일을 넣는다

```
store-a/
  sources/
    video/   *.mp4        제조 영상, 매장 둘러보기
    voice/   *.m4a *.mp3  구두 인수인계 녹음
    scan/    *.pdf *.jpg  레시피북, 공지·규칙
    kakao/   *.txt        점주–알바 대화 내보내기
  truth/
    facts.json            사실 정답지 (아래 3번)
  manifest.json           자료 목록 (아래 2번)
```

**4개 유형을 전부 넣는다.** 하나라도 빠지면 그 유형의 추출 손실을 모른다.
`VOICE`·`KAKAO` 가 없으면 직접 만들어도 된다 — 점주 역할로 녹음하고 대화를 작성한다.
브랜드 자료가 아니어도 되는 유형이다.

## 2. `manifest.json`

자료 하나당 한 항목.

| 필드 | 값 |
|---|---|
| `source_key` | 사실 정답지가 참조할 식별자. 매장 안에서 유일 |
| `type` | `VIDEO` `VOICE` `SCAN` `KAKAO` |
| `file` | `manifest.json` 기준 상대 경로 |
| `authority` | `OWNER_ANSWER` > `RECIPE_BOOK` = `NOTICE` > `OTHER` |

`authority` 는 값이 충돌했을 때 **기본 제안**을 고르는 참고값이다.
자동 확정 근거가 아니다 — 레시피북이 오래됐을 수도 있다.

## 3. `truth/facts.json` — 사실 정답지

**원본을 사람이 읽고, 거기 담긴 업무 사실을 하나씩 적는다.**
이게 `E-O0` 추출 손실의 채점 기준이다. 카드를 보고 적으면 안 된다 —
그러면 추출이 놓친 것을 영원히 못 찾는다. **원본만 보고 적는다.**

| 필드 | 뜻 |
|---|---|
| `fact_id` | `a-0001` 형식. 안 바뀐다 |
| `subject` | 대상. 예: `카페라떼` |
| `variant` | 규격. 예: `HOT` `ICE` `L`. **없으면 빈 문자열이 아니라 생략** |
| `attribute` | 속성. 예: `스팀우유량` |
| `value` | 값. 예: `275ml` |
| `must_have` | 이게 빠지면 치명적인가 |
| `source_key` | 어느 자료에서 나왔나 |
| `locator` | 어디서 나왔나. `PAGE`+`page` / `TIMESTAMP`+`timestamp_sec` |

머리에 넣을 것 셋:

- **같은 이름 다른 규격은 반드시 `variant` 로 가른다.**
  HOT 275ml 와 ICE 225ml 는 **다른 사실**이다. 합쳐지면 안 된다.
- **여러 자료에 걸친 것을 일부러 남긴다.**
  영상엔 제조 순서만, 레시피북엔 수량 — 이게 병합 검증의 재료다.
- **매장 사실 관계는 점주 확인이 필수다.** 우리는 무엇이 맞는지 모른다.
  확인 후 `owner_confirmed: true`, `judged_by`, `judged_at` 을 채운다.

## 4. 검증한다

```bash
cd api && python scripts/check_eval_data.py --store store-a
```

라벨링 도중에도 자주 돌린다. 다 쓰고 나서 형식이 틀린 걸 알면 다시 해야 한다.

## 5. 매장을 만든다

```bash
cd api && python scripts/seed_eval_stores.py
```

`eval-a` ~ `eval-e` 가 생긴다. 분할은 `SPLIT.md` 가 정본이다.
