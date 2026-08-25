"""준혁 — Gemini Flash 멀티모달 추출 (M2 이후).

M1 을 통과하기 전에는 쓰지 않는다. INGEST_MODE=real 일 때만 선택된다.
응답은 response_schema 로 강제한다. 자유 텍스트를 파싱하지 않는다.
"""
import logging
import time
from pathlib import Path

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.ingest.schemas import ExtractionResult

logger = logging.getLogger(__name__)

# response_schema 를 쓰면 SDK 가 AFC 경고를 매 호출마다 찍는다. 우리는 함수 호출을 쓰지 않는다
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "extract_cards.ko.txt"


def _render_prompt(*, source_type: str, text: str,
                   category_names: list[str], glossary: list[dict[str, str]]) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    categories = "\n".join(f"- {c}" for c in category_names) or "- (없음)"
    if glossary:
        terms = "\n".join(
            f"- {g['term']}"
            + (f" (={g['variants']})" if g.get("variants") else "")
            + (f": {g['description']}" if g.get("description") else "")
            for g in glossary
        )
    else:
        terms = "- (등록된 용어 없음)"
    return (template
            .replace("{categories}", categories)
            .replace("{glossary}", terms)
            .replace("{source_type}", source_type)
            .replace("{transcript}", text))


_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".pdf": "application/pdf"}


def _parts(prompt: str, media: list[Path]):
    from google.genai import types

    parts = [types.Part.from_text(text=prompt)]
    for m in media:
        mime = _MIME.get(m.suffix.lower())
        if mime is None:
            logger.warning("지원하지 않는 첨부 형식 무시: %s", m.name)
            continue
        parts.append(types.Part.from_bytes(data=m.read_bytes(), mime_type=mime))
    return parts


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _call(prompt: str, media: list[Path]) -> str:
    from google import genai
    from google.genai import types

    s = get_settings()
    client = genai.Client(api_key=s.gemini_api_key)
    res = await client.aio.models.generate_content(
        model=s.gemini_model,
        contents=_parts(prompt, media),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractionResult,
            temperature=0.2,
        ),
    )
    return res.text or ""


async def extract(
    *, source_id: int, source_type: str, text: str,
    category_names: list[str], glossary: list[dict[str, str]],
    media: list[Path] = (),
) -> ExtractionResult:
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY 가 없다. 셸에 export 해둔 값이 .env 를 덮어쓰는 경우가 잦다. "
            "unset GEMINI_API_KEY 후 다시 시도하라"
        )

    prompt = _render_prompt(source_type=source_type, text=text,
                            category_names=category_names, glossary=glossary)

    media = list(media)
    started = time.perf_counter()
    raw = await _call(prompt, media)
    elapsed = time.perf_counter() - started
    logger.info("gemini model=%s elapsed=%.1fs in=%dchars media=%d out=%dchars",
                s.gemini_model, elapsed, len(prompt), len(media), len(raw))

    try:
        result = ExtractionResult.model_validate_json(raw)
    except Exception as e:
        raise RuntimeError(f"추출 결과 JSON 파싱 실패: {e}") from e

    # evidence.source_id 는 모델이 지어낼 수 있다. 항상 실제 값으로 덮어쓴다
    for card in result.cards:
        card.evidence.source_id = source_id
    return result
