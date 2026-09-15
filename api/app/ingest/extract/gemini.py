"""준혁 — Gemini Flash 멀티모달 추출 (M2 이후).

M1 을 통과하기 전에는 쓰지 않는다. INGEST_MODE=real 일 때만 선택된다.
응답은 response_schema 로 강제한다. 자유 텍스트를 파싱하지 않는다.
"""
import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.ingest.schemas import ExtractionResult, FactExtractionResult

logger = logging.getLogger(__name__)

# response_schema 를 쓰면 SDK 가 AFC 경고를 매 호출마다 찍는다. 우리는 함수 호출을 쓰지 않는다
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "extract_cards.ko.txt"
ASSEMBLE_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "assemble_cards.ko.txt")
FACTS_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "extract_facts.ko.txt")


def _category_block(category_names: list[str]) -> str:
    return "\n".join(f"- {c}" for c in category_names) or "- (없음)"


def _glossary_block(glossary: list[dict[str, str]]) -> str:
    if not glossary:
        return "- (등록된 용어 없음)"
    return "\n".join(
        f"- {g['term']}"
        + (f" (={g['variants']})" if g.get("variants") else "")
        + (f": {g['description']}" if g.get("description") else "")
        for g in glossary
    )


def _render_prompt(*, source_type: str, text: str,
                   category_names: list[str], glossary: list[dict[str, str]]) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    categories = _category_block(category_names)
    terms = _glossary_block(glossary)
    return (template
            .replace("{categories}", categories)
            .replace("{glossary}", terms)
            .replace("{source_type}", source_type)
            .replace("{transcript}", text))


_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".pdf": "application/pdf"}
# 영상은 인라인 바이트로 못 넣는다. Files API 로 올린 뒤 URI 로 참조한다
_VIDEO_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime"}
# 업로드한 파일이 ACTIVE 가 될 때까지의 한도. 넘으면 실패로 보고 폴백한다
_FILE_ACTIVE_TIMEOUT_SEC = 600
_FILE_POLL_SEC = 5


async def _upload_native(client, path: Path, mime: str):
    """Files API 업로드 후 ACTIVE 가 될 때까지 폴링한다.

    PROCESSING 중인 파일을 참조하면 모델이 조용히 빈 응답을 낸다.
    상태를 확인하지 않고 넘어가면 '추출 0건' 을 프롬프트 문제로 오진하게 된다.
    """
    uploaded = await client.aio.files.upload(
        file=path, config={"mime_type": mime, "display_name": path.name}
    )
    started = time.perf_counter()
    while getattr(uploaded.state, "name", str(uploaded.state)) == "PROCESSING":
        if time.perf_counter() - started > _FILE_ACTIVE_TIMEOUT_SEC:
            raise TimeoutError(
                f"Files API 가 {_FILE_ACTIVE_TIMEOUT_SEC}초 안에 ACTIVE 가 되지 않았다: {path.name}"
            )
        await asyncio.sleep(_FILE_POLL_SEC)
        uploaded = await client.aio.files.get(name=uploaded.name)

    state = getattr(uploaded.state, "name", str(uploaded.state))
    if state != "ACTIVE":
        raise RuntimeError(f"Files API 업로드 실패 state={state}: {path.name}")
    logger.info("native video 업로드 완료 %s (%.1fs, %.1fMB)",
                path.name, time.perf_counter() - started, path.stat().st_size / 1e6)
    return uploaded


async def _parts(prompt: str, media: list[Path], client=None):
    from google.genai import types

    parts = [types.Part.from_text(text=prompt)]
    for m in media:
        suffix = m.suffix.lower()
        video_mime = _VIDEO_MIME.get(suffix)
        if video_mime is not None:
            if client is None:
                logger.warning("영상 첨부에 client 가 없다. 건너뛴다: %s", m.name)
                continue
            uploaded = await _upload_native(client, m, video_mime)
            parts.append(types.Part.from_uri(
                file_uri=uploaded.uri, mime_type=video_mime))
            continue
        mime = _MIME.get(suffix)
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
async def _call(prompt: str, media: list[Path], schema=None) -> tuple[str, dict]:
    """(응답 텍스트, 공급자 usage). usage 는 못 받으면 빈 dict 다 — 0 으로 채우지 않는다."""
    from google import genai
    from google.genai import types

    s = get_settings()
    client = genai.Client(api_key=s.gemini_api_key)
    res = await client.aio.models.generate_content(
        model=s.gemini_model,
        contents=await _parts(prompt, media, client),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema or ExtractionResult,
            temperature=s.extract_temperature,
        ),
    )
    return res.text or "", _usage_of(res)


def _usage_of(res: object) -> dict:
    """공급자가 보고한 과금 단위. **없는 값은 담지 않는다.**

    SDK 버전마다 필드가 달라 실패해도 조용히 넘긴다 — 계측 때문에 추출을 죽이지 않는다.
    원형(raw)을 함께 남겨 나중에 새 과금 항목이 생겨도 다시 해석할 수 있다.
    """
    meta = getattr(res, "usage_metadata", None)
    if meta is None:
        return {}
    out: dict = {}
    for key, attr in (("prompt_tokens", "prompt_token_count"),
                      ("completion_tokens", "candidates_token_count"),
                      ("cached_tokens", "cached_content_token_count"),
                      ("thought_tokens", "thoughts_token_count")):
        value = getattr(meta, attr, None)
        if value is not None:
            out[key] = int(value)
    if out:
        try:
            out["raw"] = {k: v for k, v in vars(meta).items()
                          if isinstance(v, (int, float, str, type(None)))}
        except TypeError:
            pass
    return out


async def extract(
    *, source_id: int, source_type: str, text: str,
    category_names: list[str], glossary: list[dict[str, str]],
    media: list[Path] = (), usage_sink=None, usage_context=None,
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
    raw, usage = await _measured_call(prompt, media, usage_sink, usage_context,
                                      prompt_hash=_hash(prompt))
    elapsed = time.perf_counter() - started
    logger.info("gemini model=%s elapsed=%.1fs in=%dchars media=%d out=%dchars usage=%s",
                s.gemini_model, elapsed, len(prompt), len(media), len(raw),
                usage or "미보고")

    try:
        result = ExtractionResult.model_validate_json(raw)
    except Exception as e:
        raise RuntimeError(f"추출 결과 JSON 파싱 실패: {e}") from e

    # evidence.source_id 는 모델이 지어낼 수 있다. 항상 실제 값으로 덮어쓴다
    for card in result.cards:
        card.evidence.source_id = source_id
    return result


async def extract_facts(
    *, source_id: int, source_type: str, text: str,
    glossary: list[dict[str, str]], media: list[Path] = (),
    usage_sink=None, usage_context=None,
) -> FactExtractionResult:
    """map — 자료에서 **사실만** 뽑는다 (W1).

    카드를 만들지 않는다. 카드 스키마로 뽑으면 "한 카드에 한 대상" 규칙 때문에
    구간마다 카드 한 장 = 사실 한 개가 되고, 그러면 조립이 합칠 것이 없다.
    store-a 실측에서 map 이 39장을 만들고 조립이 36장으로 줄이는 데 그쳤다.
    """
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY 가 없다")

    prompt = (FACTS_PROMPT_PATH.read_text(encoding="utf-8")
              .replace("{glossary}", _glossary_block(glossary))
              .replace("{source_type}", source_type)
              .replace("{transcript}", text))

    media = list(media)
    started = time.perf_counter()
    raw, usage = await _measured_call(prompt, media, usage_sink, usage_context,
                                      prompt_hash=_hash(prompt),
                                      schema=FactExtractionResult)
    elapsed = time.perf_counter() - started
    try:
        result = FactExtractionResult.model_validate_json(raw)
    except Exception as e:
        raise RuntimeError(f"사실 추출 JSON 파싱 실패: {e}") from e

    logger.info("extract_facts source=%s %.1fs 사실 %d건 미해결 %d건 usage=%s",
                source_id, elapsed, len(result.assertions),
                len(result.unresolved), usage or "미보고")
    return result


async def assemble(
    *, source_id: int, facts: list[dict], category_names: list[str],
    glossary: list[dict], usage_sink=None, usage_context=None,
) -> ExtractionResult:
    """reduce — 뽑아둔 사실을 모아 카드로 조립한다 (13.4 2패스).

    새 사실을 만들지 않는다. 구간별 map 이 만든 사실을 대상 단위로 묶는 일만 한다.
    구간 분할만 켜면 같은 대상이 여러 카드로 쪼개져 신입이 카드 하나로는 답을
    못 얻는다 — 그 손실(ASSEMBLY)을 여기서 되돌린다.
    """
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY 가 없다")
    if not facts:
        return ExtractionResult(cards=[], unresolved=[])

    prompt = (ASSEMBLE_PROMPT_PATH.read_text(encoding="utf-8")
              .replace("{categories}", _category_block(category_names))
              .replace("{glossary}", _glossary_block(glossary))
              .replace("{facts_json}",
                       json.dumps(facts, ensure_ascii=False, indent=1)))

    started = time.perf_counter()
    raw, usage = await _measured_call(prompt, [], usage_sink, usage_context,
                                      prompt_hash=_hash(prompt))
    result = ExtractionResult.model_validate_json(raw)
    logger.info("assemble source=%s 사실 %d건 → 카드 %d장 (%.1fs) usage=%s",
                source_id, len(facts), len(result.cards),
                time.perf_counter() - started, usage or "미보고")
    return result


def _hash(text: str) -> str:
    """어느 프롬프트로 부른 호출인지. 프롬프트를 바꾼 뒤 원가가 왜 변했는지 되짚는다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _measured_call(prompt: str, media: list[Path], sink, context,
                         *, prompt_hash: str | None = None,
                         schema=None) -> tuple[str, dict]:
    """계측을 감싼 호출. sink 가 없으면 계측 없이 그대로 부른다."""
    from app.usage import recorder

    s = get_settings()
    if context is None:
        return await _call(prompt, media, schema)

    async with recorder.attempt(sink, context, model=s.gemini_model,
                                mode=s.ingest_mode, prompt_hash=prompt_hash) as rec:
        rec.measure_input(
            input_bytes=len(prompt.encode("utf-8")) + sum(
                m.stat().st_size for m in media if m.exists()),
            frame_count=len(media) or None,
        )
        text, usage = await _call(prompt, media, schema)
        rec.reported_model = s.gemini_model
        if usage:
            rec.observe(**usage)
        else:
            rec.partial("공급자가 usage 를 보고하지 않았다")
        return text, usage
