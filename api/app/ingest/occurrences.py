"""W1-4 — 근거 위치(occurrence) 보존과 추정 채우기 거절.

같은 사실이 한 자료의 여러 자리에 나오면 원장(`source_facts`)에는 내용 hash 로 한 행만
남는다. 두 번째 자리는 예전에는 버려졌다. 이제 자리마다 `source_fact_occurrences` 에
한 행씩 남긴다. `source_facts.locator` 는 처음 적힌 위치 그대로다.
W2 가 이 표를 `fact_occurrences`(fact revision 기준)로 옮긴다 — 지금은 거기에 쓰지 않는다.

위치 표지 (플래그 `extract_locator_hints` 를 켰을 때만 모델이 쪽·번호를 준다):
  - PDF 텍스트  `[N쪽]`       → LocatedEvidence.page → PAGE {"page": N}
  - 카톡 메시지 `[#N]`        → LocatedEvidence.line → LINE {"line": N}
  - 음성·영상   `[mm:ss]`     → Evidence.timestamp_sec → TIMESTAMP (플래그와 무관, 이전과 같다)
플래그가 꺼져 있으면 쪽·번호는 보지 않는다 — 위치는 이전처럼 시각 또는 자료 전체다.
근거 위치 표 기록과 아래 단위·규격·참조 검사는 플래그와 무관하게 늘 돈다.

서버 검사 (원장에 적기 전, 구간마다, 그 구간 입력 글을 보고 한다):
  - (켰을 때) 입력에 없는 쪽·줄 → 번호를 지우고(자료 전체로 떨어진다) 사유를 unresolved 에 남긴다
  - 원문과 입력 글 어디에도 없는 단위·규격 — **기본은 기록만 한다**(값을 남긴다)
      · 입력이 글뿐이면 → 판정 UNGROUNDED_TEXT. 플래그 `extract_clear_ungrounded_values` 를
        켰을 때만 값을 비우고 판정 CLEARED 로 남긴다. 사실은 늘 남긴다
      · 첨부(그림·문서·영상 프레임)가 있으면 → 첨부에서 읽었을 수 있으므로 값을 **남기고**
        판정 NEEDS_IMAGE_CHECK('텍스트 근거 없음(이미지 확인 필요)')
    기본을 기록만으로 둔 까닭: 말로 된 입력(음성 전사·카톡)은 '두 샷'·'따뜻하게 드실 경우'처럼
    숫자·규격 낱말 없이 말한다. 판정 오탐으로 값을 비우면 content_hash 가 바뀌고 HOT/ICE 가
    한 사실로 합쳐질 수 있다(D19). 측정 기준선(D16) 앞에서 원장 값을 바꾸지 않는다.
  - 같은 출력에 없는 requires 참조 → 늘 뺀다(가리킬 곳이 없다). 판정 REMOVED 로 남긴다
  - 시각(timestamp)은 검사하지 않는다 — 자료 길이를 구간 입력만으로 알 수 없다
판정은 사실마다 `check_flags`(서버가 채우는 비공개 속성)에 쌓이고 근거 위치 행의 check_flags
열로 영속한다. 사유 문장은 이전처럼 unresolved 에도 남긴다.

단위·규격의 '근거' 판정은 느슨한 부분 일치가 아니다. 한국어 단위는 흔한 낱말 안에 숨어 있다
('온도'의 도, '충분히'의 분, '초콜릿'의 초, '미리 준비'의 미리, '프로모션'의 프로). 그래서 단위는
**숫자(또는 그 사실의 값) 바로 뒤**에 올 때만 근거로 센다(띄어쓰기 허용).
규격 ICE/HOT 의 한국어 표현도 규격의 뜻일 때만 센다:
  - ICE: '아이스'(아이스크림 제외), 또는 얼음을 음료에 넣는 절차(얼음을 넣다·채우다·담다·갈다·투입)
    — 프롬프트 규칙 3 과 같은 기준. 얼음 보관·청소, '얼음 투입 금지'·'얼음을 넣지 않는다' 는 아니다
  - HOT: '핫', 또는 '뜨거운/따뜻한' 바로 뒤에 음료·메뉴·버전·건/것, 또는 '따뜻하게/뜨겁게' 뒤에
    드시다·마시다·제공·주문 같은 제공 동사
  - ICE 도 같은 모양으로 '차가운/시원한 + 음료·건', '차갑게/시원하게 + 제공 동사' 를 센다
  - 단위 앞의 수는 아라비아 숫자·그 사실의 값·한국어 수 낱말(한/두/세…/열두, 일/이/삼…/십오, 반)
  - 사이즈는 일반 사이즈 낱말만 별칭으로 둔다(라지·레귤러·스몰·톨·그란데 등). 상표명은 넣지 않는다
"""
import hashlib
import json
import logging
import re
from pathlib import Path

import asyncpg

from app.ingest.preprocess.document import pdf_page_count

logger = logging.getLogger(__name__)

WHOLE_SOURCE = "WHOLE_SOURCE"

_PAGE_MARK = re.compile(r"^\[(\d+)쪽\]", re.M)
_LINE_MARK = re.compile(r"^\[#(\d+)\]", re.M)
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}

# 같은 단위의 다른 표기. 모델이 `ml` 로 적고 자료에 `10 밀리리터` 로 나와도 근거로 본다.
# 어느 표기든 숫자(또는 값) 바로 뒤에 올 때만 센다
_UNIT_ALIASES = [
    {"ml", "㎖", "밀리리터", "미리", "cc"},
    {"l", "ℓ", "리터"},
    {"g", "그램", "그람", "gram"},
    {"kg", "㎏", "킬로그램", "킬로"},
    {"분", "min", "minute", "minutes"},
    {"초", "sec", "second", "seconds"},
    {"시간", "h", "hr", "hour", "hours"},
    {"°c", "℃", "도"},
    {"%", "퍼센트", "프로"},
    {"oz", "온스"},
]
_ICE_WORDS = {"ice", "iced", "아이스", "얼음"}
_HOT_WORDS = {"hot", "핫", "뜨거운", "따뜻한"}
_ICE_PATTERNS = [
    re.compile(r"(?<![a-z])iced?(?![a-z])"),
    re.compile(r"아이스(?!크림)"),
]
# 얼음을 음료에 넣는 절차. 동사 뒤 몇 글자 안에 부정이 오면 세지 않는다
_ICE_PROCEDURE = re.compile(
    r"얼음(?:을|과|이|\s)*(?:[가-힣]{0,4}\s*)?(넣|채우|채워|담|갈아|갈고|투입)")
_NEGATION = re.compile(r"금지|않|말|안\s")
# 규격을 가리키는 뒤말 — '따뜻한 건', '차가운 음료', '시원한 걸로'
_SPEC_NOUN = r"\s*(?:음료|메뉴|버전|건|것|거|걸)"
# 제공 동사 — '따뜻하게 드실 경우', '차갑게 만들어', '뜨겁게 해 달라'
_SERVE_VERB = r"\s*(?:드|마시|제공|주문|나가|나간|만들|준비|해\s*(?:달|드|주))"
_HOT_PATTERNS = [
    re.compile(r"(?<![a-z])hot(?![a-z])"),
    re.compile(r"핫"),
    re.compile(r"(?:뜨거운|따뜻한)" + _SPEC_NOUN),
    re.compile(r"(?:뜨겁게|따뜻하게)" + _SERVE_VERB),
]
_ICE_PATTERNS.extend([
    re.compile(r"(?:차가운|시원한)" + _SPEC_NOUN),
    re.compile(r"(?:차갑게|시원하게)" + _SERVE_VERB),
])
_ICE_WORDS |= {"차가운", "시원한"}
_HOT_WORDS |= {"따뜻하게", "뜨겁게"}

# 일반 사이즈 낱말. 같은 사이즈의 다른 표기다. 상표명은 넣지 않는다
_SIZE_ALIASES = [
    {"s", "small", "스몰"},
    {"m", "medium", "미디엄"},
    {"r", "regular", "레귤러"},
    {"l", "large", "라지"},
    {"tall", "톨"},
    {"grande", "그란데"},
]

# 단위 앞의 한국어 수 낱말. 낱말 중간에서 시작하지 않는다(앞에 한글이 붙으면 세지 않는다)
_NATIVE_NUM = (r"(?:(?:열|스물|서른|마흔|쉰)?(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)"
               r"|열|스물|스무|서른|마흔|쉰)")
_SINO_NUM = r"[일이삼사오육칠팔구십백천]+"
_NUM_WORD = rf"(?<![가-힣])(?:{_NATIVE_NUM}|{_SINO_NUM}|반)"

# check_flags 판정 값
UNGROUNDED_TEXT = "UNGROUNDED_TEXT"
NEEDS_IMAGE_CHECK_FLAG = "NEEDS_IMAGE_CHECK"
CLEARED = "CLEARED"
REMOVED = "REMOVED"

NEEDS_IMAGE_CHECK = "텍스트 근거 없음(이미지 확인 필요)"


# ── 위치 ───────────────────────────────────────────────────────────────

def locator_for(source_type: str, evidence, *, locator_hints: bool = False) -> tuple[str, dict]:
    """자료 유형과 근거에서 원장 위치를 만든다. 쓸 수 있는 번호가 없으면 자료 전체다.

    쪽·메시지 번호는 `locator_hints`(W1-4 플래그)를 켰을 때만 본다.
    """
    page = getattr(evidence, "page", 0) if locator_hints else 0
    line = getattr(evidence, "line", 0) if locator_hints else 0
    if source_type == "SCAN" and page > 0:
        return "PAGE", {"page": int(page)}
    if source_type == "KAKAO" and line > 0:
        return "LINE", {"line": int(line)}
    if source_type in ("VOICE", "VIDEO") and evidence.timestamp_sec > 0:
        return "TIMESTAMP", {"timestamp_sec": int(evidence.timestamp_sec)}
    return WHOLE_SOURCE, {}


def occurrence_hash(*, segment_id: str | None, locator_type: str, locator: dict) -> str:
    """같은 사실의 같은 자리를 한 번만 남기는 열쇠.

    이름표(local_ref)·원래 응답 ID 는 넣지 않는다 — 같은 작업을 다시 돌리면 둘 다 바뀌지만
    자리는 같다. 구간은 부모 구간(seg3)만 넣는다. 잘림 분할의 하위 경로는 실행마다 다르다.
    """
    payload = json.dumps([segment_id or "", locator_type, locator],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── 서버 검사 ───────────────────────────────────────────────────────────

def has_text_evidence(text: str | None) -> bool:
    """입력 글이 자료 내용인가. 전처리의 안내문 한 줄(`(… 판단할 것)`)은 근거가 아니다."""
    body = (text or "").strip()
    if not body:
        return False
    return not (body.startswith("(") and body.endswith(")") and "\n" not in body)


def _allowed_pages(text: str, media: list[Path]) -> set[int]:
    pages = {int(n) for n in _PAGE_MARK.findall(text or "")}
    for path in media or []:
        suffix = Path(path).suffix.lower()
        if suffix == ".pdf":
            pages.update(range(1, pdf_page_count(Path(path)) + 1))
        elif suffix in _IMAGE_SUFFIXES:
            pages.add(1)
    return pages


def _allowed_lines(text: str) -> set[int]:
    return {int(n) for n in _LINE_MARK.findall(text or "")}


def _form(word: str) -> str:
    """표기 하나를 정규식으로. 영문 표기는 뒤에 다른 영문 글자가 붙으면 세지 않는다."""
    body = r"\s*".join(re.escape(part) for part in word.split())
    return body + (r"(?![a-z])" if re.search(r"[a-z]", word) else "")


def unit_grounded(unit: str, value: str, haystack: str) -> bool:
    """단위가 숫자 또는 그 사실의 값 바로 뒤에 나오는가 (띄어쓰기 허용)."""
    key = unit.strip().lower()
    if not key:
        return True
    group = next((g for g in _UNIT_ALIASES if key in g), set()) | {key}
    before = rf"(?:\d|{_NUM_WORD})"
    if value.strip():
        before = rf"(?:\d|{_NUM_WORD}|{re.escape(value.strip().lower())})"
    hay = haystack.lower()
    return any(re.search(rf"{before}\s*{_form(alias)}", hay) for alias in group)


def _ice_procedure(hay: str) -> bool:
    for m in _ICE_PROCEDURE.finditer(hay):
        if not _NEGATION.search(hay[m.end():m.end() + 8]):
            return True
    return False


def variant_grounded(variant: str, haystack: str) -> bool:
    """규격이 입력에 규격의 뜻으로 나오는가."""
    key = variant.strip().lower()
    if not key:
        return True
    hay = haystack.lower()
    if key in _ICE_WORDS:
        return any(p.search(hay) for p in _ICE_PATTERNS) or _ice_procedure(hay)
    if key in _HOT_WORDS:
        return any(p.search(hay) for p in _HOT_PATTERNS)
    group = next((g for g in _SIZE_ALIASES if key in g), set()) | {key}
    return any(_word_in(word, hay) for word in group)


def _word_in(word: str, hay: str) -> bool:
    """영문 표기는 영문 경계로, 한국어 표기는 띄어쓰기를 무시한 부분 일치로."""
    if re.search(r"[a-z]", word):
        return re.search(rf"(?<![a-z]){_form(word)}", hay) is not None
    return re.sub(r"\s+", "", word) in re.sub(r"\s+", "", hay)


def _flag(a, field: str, verdict: str, value) -> None:
    """사실에 서버 검사 판정을 하나 붙인다. 근거 위치 행의 check_flags 로 영속한다."""
    flags = getattr(a, "_check_flags", None)
    if flags is None:
        return
    flags.append({"field": field, "verdict": verdict, "value": value})


def validate_assertions(assertions: list, *, source_type: str, text: str,
                        media: list[Path], locator_hints: bool = False,
                        clear_ungrounded: bool = False) -> list[str]:
    """구간 하나의 사실을 입력과 대조한다. 판정은 사실의 check_flags 에 붙이고 사유 목록을 돌려준다.

    사실 자체는 버리지 않는다. 근거 없는 단위·규격은 기본으로 **값을 남기고 기록만** 한다.
    `clear_ungrounded`(플래그 extract_clear_ungrounded_values)를 켜면 글만 있는 입력의 값을 비운다.
    없는 requires 참조는 늘 뺀다. 사유는 unresolved 로 간다.
    """
    reasons: list[str] = []
    text = text or ""
    media = list(media or [])
    pages = lines = None
    textual = has_text_evidence(text)
    refs = {a.local_ref for a in assertions}

    for a in assertions:
        ref = a.local_ref
        ev = a.evidence

        if locator_hints:
            page = getattr(ev, "page", 0)
            line = getattr(ev, "line", 0)
            # 쪽 번호
            if page:
                if source_type != "SCAN":
                    reasons.append(f"[근거 위치 거절] {ref}: {source_type} 자료에는 쪽 번호가 없다 "
                                   f"({page}쪽) — 자료 전체로 둔다")
                    ev.page = 0
                else:
                    if pages is None:
                        pages = _allowed_pages(text, media)
                    if page not in pages:
                        reasons.append(f"[근거 위치 거절] {ref}: {page}쪽은 입력에 없다 "
                                       f"— 자료 전체로 둔다")
                        ev.page = 0
            # 카톡 메시지 번호
            if line:
                if source_type != "KAKAO":
                    reasons.append(f"[근거 위치 거절] {ref}: {source_type} 자료에는 메시지 번호가 없다 "
                                   f"(#{line}) — 자료 전체로 둔다")
                    ev.line = 0
                else:
                    if lines is None:
                        lines = _allowed_lines(text)
                    if line not in lines:
                        reasons.append(f"[근거 위치 거절] {ref}: 메시지 #{line} 은 입력에 없다 "
                                       f"— 자료 전체로 둔다")
                        ev.line = 0

        # 지어낸 단위·규격. 근거는 원문 + (자료 내용이면) 구간 입력 글
        basis = a.original_assertion + ("\n" + text if textual else "")
        for field, label, grounded in (
                ("unit", "단위", lambda: unit_grounded(a.unit, a.value, basis)),
                ("variant", "규격", lambda: variant_grounded(a.variant, basis))):
            value = getattr(a, field)
            if not value.strip() or grounded():
                continue
            if media:
                reasons.append(f"[이미지 확인 필요] {ref}: {label} '{value}' — {NEEDS_IMAGE_CHECK}. "
                               f"첨부에서 읽었을 수 있어 값을 남긴다")
                _flag(a, field, NEEDS_IMAGE_CHECK_FLAG, value)
            elif clear_ungrounded:
                reasons.append(f"[추정 채우기 거절] {ref}: {label} '{value}' 가 원문·입력에 없어 "
                               f"비웠다 (사실은 남긴다)")
                _flag(a, field, CLEARED, value)
                setattr(a, field, "")
            else:
                reasons.append(f"[근거 확인 필요] {ref}: {label} '{value}' 가 원문·입력 글에서 "
                               f"확인되지 않는다 — 값은 남긴다(기록만)")
                _flag(a, field, UNGROUNDED_TEXT, value)

        # 없는 선행 참조 — 가리킬 곳이 없으므로 늘 뺀다
        missing = [r for r in a.requires if r not in refs]
        if missing:
            for r in missing:
                reasons.append(f"[참조 거절] {ref}: 선행 사실 '{r}' 가 이 출력에 없어 뺐다")
                _flag(a, "requires", REMOVED, r)
            a.requires = [r for r in a.requires if r in refs]

    return reasons


# ── 저장·조회 ───────────────────────────────────────────────────────────

async def insert_occurrences(conn: asyncpg.Connection, store_id: int, rows: list[dict]) -> None:
    """사실의 근거 위치를 남긴다. 같은 사실·같은 자리는 한 번만 (unique(fact_id, occurrence_hash)).

    D1 — store_id 는 필수 인자다. 사실이 이 매장 것이 아니면 아무것도 넣지 않는다.
    원래 응답 ID 도 같은 매장 행일 때만 싣는다. 자료 ID 는 사실 행에서 가져온다.
    check_flags(서버 검사 판정)는 싣지만 occurrence_hash 에는 넣지 않는다 — 재시도의 판정이
    달라도 같은 자리는 한 행이다(처음 적힌 판정이 남는다).
    """
    for row in rows:
        digest = occurrence_hash(segment_id=row.get("segment_id"),
                                 locator_type=row["locator_type"], locator=row["locator"])
        await conn.execute(
            """
            insert into source_fact_occurrences (
              store_id, fact_id, source_id, segment_id, local_ref,
              locator_type, locator, raw_response_id, occurrence_hash, check_flags
            )
            select f.store_id, f.fact_id, f.source_id, $3, $4, $5, $6::jsonb,
                   (select r.raw_response_id from extraction_raw_responses r
                    where r.store_id = $1 and r.raw_response_id = $7),
                   $8, $9::jsonb
            from source_facts f
            where f.store_id = $1 and f.fact_id = $2
            on conflict (fact_id, occurrence_hash) do nothing
            """,
            store_id, int(row["fact_id"]), row.get("segment_id"),
            (row.get("local_ref") or None) and row["local_ref"][:80],
            row["locator_type"], json.dumps(row["locator"], ensure_ascii=False),
            row.get("raw_response_id"), digest,
            json.dumps(list(row.get("check_flags") or []), ensure_ascii=False),
        )


async def list_occurrences(conn: asyncpg.Connection, store_id: int, *,
                           source_id: int | None = None,
                           fact_id: int | None = None) -> list[asyncpg.Record]:
    """매장의 근거 위치. D1 — 다른 매장 행은 보이지 않는다."""
    return await conn.fetch(
        """
        select occurrence_id, store_id, fact_id, source_id, segment_id, local_ref,
               locator_type, locator, raw_response_id, occurrence_hash, check_flags,
               created_at
        from source_fact_occurrences
        where store_id = $1
          and ($2::bigint is null or source_id = $2)
          and ($3::bigint is null or fact_id = $3)
        order by occurrence_id
        """,
        store_id, source_id, fact_id,
    )
