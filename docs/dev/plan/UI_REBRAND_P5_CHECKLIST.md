# P5 근무조 체크리스트 — 설계

2026-10-06 · 상태: **설계 확정(3차) · 백엔드 구현 완료(2026-10-07, 미커밋).** 상위 계획 [UI_REBRAND_MOBILE_PLAN.md](UI_REBRAND_MOBILE_PLAN.md) P5 · 브랜치 `ui/rebrand-mobile`
구현은 이 문서 확정 뒤 별도 구현 계획(`UI_REBRAND_P5_CHECKLIST_PLAN.md`)으로 쪼개 subagent-driven 으로 진행한다(U8).

## 1. 목적

알바가 "지금 내 범위의 할 일"을 체크하고 끝나면 제출한다. 점주는 매장의 오늘 진행을 한눈에 보고, 마이페이지 달력으로 사람별 기록을 본다 (Figma A2·A3·A4·O6·O6-2, 근무조 규칙 `41:284`).
체크 항목은 **승인된 매장 지식**에서 나온다 — 따로 적는 할 일 목록을 만들지 않는다. 등록한 자료가 곧 체크리스트가 된다.

## 2. 사용자 결정 (2026-10-06)

| # | 결정 |
|---|---|
| C1 | 근무조는 **완전히 자유롭다.** 점주가 이름·시간·개수를 만들고 바꾸고 지운다. 0개도 정상이다. 오픈/미들/마감은 정해진 값이 아니다 |
| C2 | 카드와 근무조는 **직접 연결**한다. 카테고리 이름에 기대지 않는다. 한 카드를 여러 근무조에 넣을 수 있다. 연결이 근무조에 없으면 **공통**(모든 근무조가 보는 카드)이다. 편집은 근무조 설정("할 일 담기")과 카드 상세("어느 근무조 할 일인가요?") 양쪽에서 같은 연결을 고치고 **바로 반영**한다 |
| C3 | **직원의 범위 = 공통 카드 + 담당 근무조 카드.** 점주가 직원마다 담당 근무조를 정한다. 매장에 근무조가 없거나 그 직원에게 담당을 정하지 않았으면 범위는 **전체**다. 날짜별 근무표는 만들지 않는다 |
| C4 | 범위의 체크가 다 끝나거나 직원이 **제출("다 했어요")** 하면 그 날 그 사람의 완료를 기록한다. 남아 있어도 확인 후 제출할 수 있고 남은 개수를 함께 남긴다. 근무조 수와 무관하다 |
| C5 | 영업일이 바뀌는 시각은 **점주가 설정**한다. 기본 04:00(매장 시간). 자정을 넘는 근무조는 시작한 영업일에 속한다 |
| C6 | 화면을 켠 채 영업일이 바뀌었는데 **어제 제출하지 않았으면** "어제 체크리스트" 창을 띄운다. 원래 순서·체크 상태 그대로 보여주고 마음껏 고친 뒤 **저장 하나만** 누른다(버리기 버튼 없음). 저장 = 어제 체크 반영 + 어제 제출. 이미 제출했으면 창을 띄우지 않는다 |
| C7 | **개인 기록**: 점주·직원 모두 마이페이지 달력에서 날짜를 누르면 그날 한 일이 나온다. 달력에는 출근한 날(체크 또는 제출이 있는 날)에 완료 %를 표시한다. 점주는 본인 + 직원별 달력, 직원은 자기 것만 |
| C7-1 | **알바생 "내 기록 남기기"**(구성원 각자 켜고 끔, 기본 켜짐): 끈 동안의 체크·제출은 **그 사람 이름으로 남기지 않는다.** 매장 체크 상태는 그대로 바뀐다(운영 영향 없음). 개인 달력에 그 기간은 비어 있다 |
| C7-2 | **점주 "알바생 기록"**(매장 설정, 기본 켜짐): 점주가 알바생 달력을 볼지만 정한다. 꺼 둔 동안에도 알바생 기록은 저장되고, **다시 켜면 그 기간 것까지 보인다** |
| C9 | **공통도 근무조와 같은 하나의 구분 단위다.** 차이는 범위와 상관없이 모두에게 보인다는 것뿐. 한 카드는 "공통" 또는 근무조 하나 이상 중 하나에 속한다(배타) |
| C8 | 체크 항목은 **카드 본문 한 줄** |

설계에서 정한 것:

- **항목 키 = `(card_version_id, line_no)`.** 줄은 공개 버전 본문을 줄바꿈으로 나눈 것(빈 줄 제외). 직원 레시피 화면의 `NumberedContent` 와 같은 규칙
- **공개 버전이 바뀌면 그날 체크는 새 버전 기준으로 다시 시작한다.** 옛 버전 체크는 지우지 않는다 (MVP §12 재확인과 같은 원리)
- **체크 상태는 매장 단위로 하나다.** 같은 근무조 두 사람이 같은 줄을 보면 같은 체크를 공유한다. 누가 바꿨는지는 이벤트로 남겨 개인 기록에 쓴다. 점주 "오늘 매장" 화면에는 사람을 표시하지 않는다(Figma 규칙)
- **승인 카드만.** `review_status = 'APPROVED'` 이고 `published_version_id` 가 있는 카드만 나온다 (불변식 11)
- **점주도 매장 구성원이다.** 점주가 체크·제출하면 점주 본인의 기록이 된다. 점주 범위는 항상 전체
- **알림 없음.** 체크·제출은 Push 를 보내지 않는다. 점주 화면은 폴링(D6)

## 3. 화면

| 화면 | 내용 | Figma |
|---|---|---|
| 직원 `/staff` 오늘 할 일 | 내 범위 묶음(공통 + 담당 근무조) · 지금 근무조 칩(시간 기준, 범위 안에서 바꿀 수 있음) · "N개 남았어요" · 실제 count 진행 막대 · 줄 체크 · "다 했어요" · 아래 질문창 | A2 |
| 제출 | 남은 게 있으면 확인 시트 "N개가 남았어요. 그래도 끝낼까요?" → 완료 화면 | A4 |
| 어제 체크리스트 창 (C6) | 어제 내 범위 전체를 원래 순서로, 체크 상태 그대로. 고치기 가능. 버튼은 "저장" 하나 | 신규 |
| 점주 `/owner` 상단 | 근무조별 진행(`이름 done/total`, 그 근무조를 범위로 가진 사람이 제출하면 ✓), 지금 근무조, 마지막 제출 후 "○○ 끝났어요 · 체크리스트 N개 · 어제 22:41에 끝" | O6, O6-2 |
| 마이페이지 `/owner/me`, `/staff/me` | 월 달력: 출근한 날에 %(제출했으면 제출 때 값, 안 했으면 그날 끝 기준). 날짜 누르면 그날 내가 체크한 줄과 제출 여부. 점주는 위쪽에서 "나 / 알바생 이름" 선택. 아래에 "내 기록 남기기" 켜기/끄기 | 신규 (A3 문구 착안) |
| 점주 설정 › 근무조 | 근무조 추가·이름·시간·순서·삭제, "오픈·미들·마감으로 시작하기"(0개일 때), 영업일 시작 시각 | 신규 |
| 점주 근무조 › 할 일 담기 | 승인 카드를 카테고리별로 보여주고 여러 개 고름 | 신규 |
| 점주 설정 › 직원 담당 | 직원마다 담당 근무조 칩 다중 선택(비우면 전체) | 신규 |
| 점주 설정 › 알바생 기록 | 켜기/끄기 (점주가 알바생 달력을 보는지) | 신규 |
| 점주 카드 상세 | "어느 근무조 할 일인가요?" 칩 다중 선택 + "공통" | O10 확장 |

빈 상태:
- 범위에 승인 카드 연결이 없음: 직원 "아직 오늘 할 일이 없어요. 사장님이 정해 주면 여기에 생겨요", 점주 상단 카드 없음 + 근무조 설정 안내 한 줄
- 근무조 0개: 칩 없이 전체 한 묶음 (Figma 규칙 "나뉘지 않은 매장이면 칩 없이 전체")
- 점주가 알바생 기록을 꺼 둠: 점주 마이페이지의 알바생 선택 자리에 "알바생 기록을 꺼 두었어요" + 켜기 안내
- 내 기록 남기기 꺼짐: 달력 위에 "기록을 남기지 않는 중이에요. 이 기간은 달력에 남지 않아요"

## 4. 데이터 (migration `20261006090000_checklist.sql`)

`20261005110000` 보다 뒤. 머지 직전 `main` 의 최신 번호와 다시 맞춘다. `knowledge_cards (store_id, card_id)` 복합 unique 는 이미 있다(`uq_knowledge_cards_store_card`).

```sql
-- 매장 설정 (C5·C7)
alter table stores
  add column if not exists timezone varchar(40) not null default 'Asia/Seoul',
  add column if not exists business_day_starts_at time not null default '04:00',
  add column if not exists staff_records_visible boolean not null default true;   -- C7-2 점주가 알바생 기록을 보는지

-- 구성원 각자 "내 기록 남기기" (C7-1)
alter table store_members
  add column if not exists personal_records_enabled boolean not null default true;

-- 근무조 (C1). 지우면 보관해 과거 기록을 남긴다
create table if not exists store_shifts (
  shift_id    bigint generated always as identity primary key,
  store_id    bigint not null references stores(store_id) on delete cascade,
  name        varchar(30) not null check (length(btrim(name)) > 0),
  starts_at   time,
  ends_at     time,                 -- ends_at <= starts_at 이면 자정을 넘는다
  sort_order  int not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  archived_at timestamptz,
  unique (store_id, shift_id),
  check ((starts_at is null) = (ends_at is null))
);
create unique index if not exists store_shifts_active_name
  on store_shifts (store_id, lower(name)) where archived_at is null;

-- 카드 ↔ 근무조 (C2·C9). 근무조 행이 있으면 그 근무조 카드, 체크리스트인데 근무조 행이 없으면 "공통" 단위
create table if not exists checklist_cards (
  store_id   bigint not null references stores(store_id) on delete cascade,
  card_id    bigint not null,
  created_at timestamptz not null default now(),
  primary key (store_id, card_id),
  foreign key (store_id, card_id) references knowledge_cards (store_id, card_id) on delete cascade
);
create table if not exists checklist_card_shifts (
  store_id bigint not null,
  card_id  bigint not null,
  shift_id bigint not null,
  primary key (store_id, card_id, shift_id),
  foreign key (store_id, card_id) references checklist_cards (store_id, card_id) on delete cascade,
  foreign key (store_id, shift_id) references store_shifts (store_id, shift_id) on delete cascade
);

-- 직원 담당 근무조 (C3). 행이 없으면 전체
create table if not exists member_shifts (
  store_id  bigint not null,
  member_id bigint not null references store_members(member_id) on delete cascade,
  shift_id  bigint not null,
  primary key (store_id, member_id, shift_id),
  foreign key (store_id, shift_id) references store_shifts (store_id, shift_id) on delete cascade
);

-- 줄 체크 현재 상태 (매장 단위 하나)
create table if not exists checklist_checks (
  store_id        bigint not null references stores(store_id) on delete cascade,
  business_date   date not null,
  card_version_id bigint not null,
  line_no         int not null check (line_no >= 1),
  checked         boolean not null,
  updated_by      bigint references users(user_id) on delete set null,
  updated_at      timestamptz not null default now(),
  primary key (store_id, business_date, card_version_id, line_no)
);

-- 체크 이벤트 (개인 기록의 근거, C7). 지우지 않는다. 그 사람의 "내 기록 남기기"가 꺼져 있으면 만들지 않는다 (C7-1)
create table if not exists checklist_check_events (
  event_id        bigint generated always as identity primary key,
  store_id        bigint not null references stores(store_id) on delete cascade,
  business_date   date not null,
  card_version_id bigint not null,
  line_no         int not null check (line_no >= 1),
  checked         boolean not null,
  user_id         bigint not null references users(user_id) on delete cascade,   -- 이벤트는 사람 기록이라 사람이 지워지면 함께 지운다
  late            boolean not null default false,   -- C6 어제 창에서 저장
  created_at      timestamptz not null default now()
);
create index if not exists checklist_check_events_user_day
  on checklist_check_events (store_id, user_id, business_date);

-- 제출 (C4). 그때 범위·개수를 고정해 남긴다. 사람·날짜당 하나.
-- "내 기록 남기기"가 꺼져 있어도 운영(점주 현황 ✓·어제 창 판정)을 위해 행은 만들되 personal=false 로 두고 개인 기록 조회에서 뺀다 (C7-1)
create table if not exists checklist_submissions (
  store_id      bigint not null references stores(store_id) on delete cascade,
  business_date date not null,
  user_id       bigint not null references users(user_id) on delete cascade,
  scope_shift_ids bigint[],          -- null = 전체 범위
  total_lines   int not null check (total_lines >= 0),
  done_lines    int not null check (done_lines >= 0 and done_lines <= total_lines),
  late          boolean not null default false,       -- C6 어제 창에서 저장
  personal      boolean not null default true,        -- C7-1 제출 때 그 사람의 기록 설정
  submitted_at  timestamptz not null default now(),
  primary key (store_id, business_date, user_id)
);
```

- 앞선 초안의 `shift_completions` 는 없앴다. 점주 화면의 근무조 ✓ 는 제출 범위(`scope_shift_ids`)에 그 근무조가 명시된 제출이 있을 때만이다(§5)
- 알바생이 "내 기록 남기기"를 끄면: 이벤트를 만들지 않고 `checklist_checks.updated_by` 도 비운다. 제출은 `personal=false` 로 남긴다. 다시 켜도 꺼진 기간은 비어 있다 (C7-1)
- 점주가 "알바생 기록"을 끄면: 저장은 그대로, 점주의 알바생 기록 **조회만** 막는다. 다시 켜면 전부 보인다 (C7-2). 알바생 본인 조회는 영향 없음

## 5. 영업일·범위·지금 근무조 계산 (서버)

- `now_local = now() at time zone stores.timezone`, `business_date = (now_local - business_day_starts_at)::date`
- **범위(scope)**: 점주 → 전체. 직원 → `member_shifts` 가 비었거나 활성 근무조가 0개면 전체, 아니면 공통 카드 + 담당 근무조 카드. 전체 = 체크리스트 카드 전부(공통 + 모든 근무조). 한 카드가 범위 안 여러 근무조에 있어도 줄은 한 번만 센다
- **지금 근무조**: 범위 안 근무조 중 시간이 맞는 것(자정 넘김 처리), 여러 개면 `sort_order` 앞, 없으면 오늘 남은 가장 빠른 것(`upcoming`), 그것도 없으면 첫 근무조. 칩은 범위 안 근무조만 보여주고, 근무조 묶음 위에 공통 묶음을 항상 같이 보여준다
- **근무조 ✓(점주 화면)**: 제출 범위(scope_shift_ids)에 그 근무조가 명시된 제출이 있을 때만. 전체 범위 제출은 근무조를 체크하지 않고 마지막 제출로만 보인다
- **자동 제출(C4)**: 범위를 다 체크하면 서버가 제출을 자동 기록한다(PUT /checks)
- **완료 %(달력)**: 제출이 있으면 done_lines / total_lines(제출 때 고정). 제출이 없는 날은 % 없이 "체크 N개"만 보여준다
- **"한 일"**: 그날 그 사람의 이벤트 중 줄별 마지막 이벤트가 `checked=true` 인 줄
- 클라이언트는 영업일을 계산하지 않는다. 체크·제출 요청에 서버가 준 `business_date` 를 그대로 보낸다
  - 오늘 날짜: 정상 처리
  - **바로 전 영업일이고 그 사람이 아직 제출 안 함**: 어제 창(C6) 경로로만 허용(`late=true`)
  - 그 밖: `409 BUSINESS_DATE_CHANGED { current_business_date, previous_unsubmitted: bool }`

## 6. API (`api/app/checklist/`, 모든 조회 `WHERE store_id = $1`, store_id·user_id 는 JWT)

| 메서드·경로 | 권한 | 내용 |
|---|---|---|
| `GET /checklist/today?shift_id=&date=` | 점주·직원 | `{business_date, scope:{all:bool, shift_ids}, current_shift_id, shifts:[{shift_id,name,starts_at,ends_at,upcoming,total,done,submitted:bool}], groups:[{shift_id\|null, name, cards:[{card_id,card_version_id,title,lines:[{line_no,text,checked}]}]}], my_submission:{submitted_at,total_lines,done_lines}\|null, previous_unsubmitted:{business_date}\|null}` · `date` 는 바로 전 영업일만 허용(어제 창) |
| `PUT /checklist/checks` | 점주·직원 | `{business_date, card_version_id, line_no, checked}` 멱등. 범위 밖·공개 버전 아님이면 409 |
| `POST /checklist/submissions` | 점주·직원 | `{business_date, checks:[{card_version_id,line_no,checked}]}` → 체크 반영 후 제출을 **한 트랜잭션**으로. 오늘 "다 했어요"는 `checks:[]`, 어제 창 저장은 전체 줄 상태. 같은 날 다시 보내면 체크만 반영하고 기존 제출 유지(멱등, 200) |
| `GET /checklist/status` | 점주 | O6 상단: 근무조별 total/done/submitted, 오늘·어제 마지막 제출 |
| `GET /checklist/records?month=YYYY-MM&user_id=` | 점주(알바생 user_id 가능)·직원(본인만) | `{visible, recording, days:[{date, percent\|null, total, done, submitted}]}` · 점주가 알바생 기록을 꺼 두었으면 알바생 조회는 `visible:false, days:[]` |
| `GET /checklist/records/{date}?user_id=` | 같음 | 그날 범위 줄 목록 + 내가 체크한 줄 표시 + 제출 정보 |
| `GET/POST /checklist/shifts`, `PATCH/DELETE /checklist/shifts/{id}` | 점주 | 근무조 CRUD. DELETE = 보관. 이름 중복 409 |
| `PUT /checklist/shifts/order` | 점주 | 순서 일괄 |
| `POST /checklist/shifts/preset` | 점주 | 활성 근무조 0개일 때만 오픈·미들·마감 생성, 아니면 409 |
| `PUT /checklist/shifts/{id}/cards` | 점주 | `{card_ids}` 그 근무조 카드 통째 교체(카드는 `checklist_cards` 에 자동 등록) |
| `PUT /checklist/cards/{card_id}` | 점주 | `{checklist:bool, shift_ids:[...]}` 그 카드의 체크리스트 여부·근무조 통째 교체. `shift_ids=[]` = 공통 |
| `GET /checklist/members`, `PUT /checklist/members/{member_id}/shifts` | 점주 | 직원별 담당 근무조 조회·교체(`[]` = 전체) |
| `PATCH /checklist/settings` | 점주 | `{business_day_starts_at?, staff_records_visible?}` |
| `PATCH /checklist/me` | 점주·직원 | `{personal_records_enabled}` 내 기록 남기기 |

- **실제 응답 형태(구현 기준)**
  - `GET /checklist/today`: 위 필드 외에 `previous_business_date`, `previous_submitted`, `view`(지금 화면 줄 수 total/done), `scope_counts`(범위 전체 total/done), `upcoming`(bool)을 준다
  - `GET /checklist/records/{date}`: 그 사람이 체크한 줄만(`lines`)과 제출(`submission`)을 준다. 범위 전체 줄 목록은 주지 않는다
  - `GET /checklist/status`: `last_submission` 에 `user_id` 가 없다(누가 냈는지 식별하지 않음). `shift_names` 는 있다
  - `GET /checklist/shifts`: 항목마다 `card_ids`(승인 여부와 무관하게 그 근무조에 연결된 카드, card_id 순)를 준다
  - `PUT /checklist/checks`: `submitted`(오늘 제출이 있는지)를 돌려준다
  - `checklist_check_events.user_id` 는 `not null on delete cascade` 다
- 점주 전용 경로는 `claims.role != 'OWNER'` 면 403. 직원이 남의 `user_id` 기록을 요청하면 403
- 다른 매장 근무조·카드·직원 id 는 404 (MVP §18-2). 오류는 공통 오류 계약

## 7. 프론트

- `web/lib/checklist-api.ts`, `web/lib/query.ts` 에 `checklistKeys`·`checklistTodayQuery`(화면이 보일 때만 폴링: 직원 15초, 점주 30초)
- 체크 토글: 낙관적 반영 → 실패 시 되돌리고 그 줄에 §28 "이 변경은 저장되지 않았어요". 저장 중 같은 줄 비활성
- **어제 창(C6)**: `409 BUSINESS_DATE_CHANGED` 이고 `previous_unsubmitted` 면, 또는 폴링 응답의 `business_date` 가 화면이 들고 있던 날짜와 다르고 `previous_unsubmitted` 가 있으면 → 어제 목록(`?date=`)을 불러 시트로 띄운다. 막 실패한 체크 하나도 반영해 둔다. 닫기 버튼 없이 "저장"만, 저장 실패 시 시트에 오류·재시도(입력 유지). 저장 성공 → 오늘 목록
- 이미 어제 제출했으면 조용히 오늘 목록으로 바꾸고 "하루가 바뀌었어요" 한 줄만 보여준다
- 제출 확인 시트: 남은 개수 > 0 일 때만
- P5 이후 `/staff` 는 레시피 redirect 대신 오늘 할 일. 설정에 "내 기록"(마이페이지), 점주 설정에 근무조·직원 담당·개인 기록 행 추가

## 8. 검증

- **API 단위 테스트**(`api/tests/test_checklist_*.py`): 다른 매장 404 · STAFF 의 점주 경로 403 · 직원이 남의 기록 403 · 체크 멱등 · 범위 밖 체크 409 · 버전 바뀌면 옛 체크 미반영 · 제외 카드 숨김 · 범위 계산(근무조 0개 / 담당 없음 / 담당 있음, 한 카드 여러 근무조 중복 없이) · 자정 넘는 근무조와 영업일 경계 · 제출 멱등과 개수 고정 · 어제 창: 바로 전날·미제출만 허용, 이미 제출이면 409, 그 이전 날짜 409 · 내 기록 끈 동안 이벤트·updated_by 없음, 제출 personal=false · 점주 알바생 기록 끄면 조회만 막히고 다시 켜면 그 기간 포함 보임 · preset·이름 중복 409
- `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/checklist`
- 합성 API 브라우저 검사(`verify_ui_rebrand.cjs`): 체크·실패 되돌림·제출 시트·어제 창(저장만, 실패 시 입력 유지)·점주 현황·근무조 편집·카드 상세 연결·직원 담당·마이페이지 달력·내 기록 끔·알바생 기록 끔
- 로컬 DB migration 적용(빈 DB 재구성 포함, `verify_r_schema_rebuild.py` 영향 확인)

## 9. 확인이 필요한 것

없음 (2026-10-06 사용자 확인으로 Q1·Q2 닫음 → C7-1·C7-2·C9).

## 10. 후속 작업 — 이 브랜치 밖

- **F4 할 일 목록 추출 (W)**: 지금 추출·평가는 레시피 위주다. 할 일 목록은 한 줄에 한 일, 순서 보존, 여러 일을 한 줄로 합치지 않음이 중요하다. Figma O4 처럼 AI 가 "레시피 / 오늘 할 일"로 나누고 근무조를 제안하는 것도 W 범위다. 그 전까지 체크리스트는 점주가 고른 승인 카드의 줄로 동작한다
- 날짜별 근무표(누가 언제 어느 근무조)는 하지 않는다(C3)

## 11. 문서 반영 (구현과 함께)

- `ASKBUDDY_MVP_CURRENT.md`: §8 화면표(오늘 할 일·마이페이지·근무조/직원 담당/개인 기록 설정), §12 옆 "근무조 체크리스트" 절, §18-1 API, §28 문구
- `DEV_TODO_CURRENT.md`: P5 항목과 완료 기준
- 소유: W/R 어느 파이프라인에도 속하지 않는 제품 운영 기능. `api/app/checklist/` 주 편집자는 이 브랜치 작업자
