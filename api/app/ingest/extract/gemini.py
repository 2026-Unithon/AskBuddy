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
from typing import NamedTuple

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.ingest import raw_responses
from app.ingest.schemas import (ExtractionResult, FactExtractionResult,
                                LocatedFactExtractionResult)

logger = logging.getLogger(__name__)

# response_schema 를 쓰면 SDK 가 AFC 경고를 매 호출마다 찍는다. 우리는 함수 호출을 쓰지 않는다
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

ASSEMBLE_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "assemble_cards.ko.txt")
FACTS_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "extract_facts.ko.txt")
# W1-4 위치 표지 판. extract_locator_hints 를 켰을 때만 쓴다
FACTS_LOCATOR_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "extract_facts_locator.ko.txt")


def locator_hints(settings) -> bool:
    """근거 위치 표지(W1-4)를 켰는가. 설정 대역에 칸이 없으면 꺼짐이다."""
    return bool(getattr(settings, "extract_locator_hints", False))


def facts_schema(settings):
    """사실 추출 응답 스키마. 꺼져 있으면 이전과 같은 스키마(요청 동일)."""
    return LocatedFactExtractionResult if locator_hints(settings) else FactExtractionResult


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


_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".pdf": "application/pdf"}
# 영상은 인라인 바이트로 못 넣는다. Files API 로 올린 뒤 URI 로 참조한다
_VIDEO_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime"}
# 업로드한 파일이 ACTIVE 가 될 때까지의 한도·폴링 간격은 config 가 정한다
# (gemini_file_active_timeout_sec · gemini_file_poll_sec). 넘으면 실패로 보고 폴백한다


async def _upload_native(client, path: Path, mime: str):
    """Files API 업로드 후 ACTIVE 가 될 때까지 폴링한다.

    PROCESSING 중인 파일을 참조하면 모델이 조용히 빈 응답을 낸다.
    상태를 확인하지 않고 넘어가면 '추출 0건' 을 프롬프트 문제로 오진하게 된다.
    """
    s = get_settings()
    timeout_sec, poll_sec = s.gemini_file_active_timeout_sec, s.gemini_file_poll_sec
    uploaded = await client.aio.files.upload(
        file=path, config={"mime_type": mime, "display_name": path.name}
    )
    started = time.perf_counter()
    while getattr(uploaded.state, "name", str(uploaded.state)) == "PROCESSING":
        if time.perf_counter() - started > timeout_sec:
            raise TimeoutError(
                f"Files API 가 {timeout_sec}초 안에 ACTIVE 가 되지 않았다: {path.name}"
            )
        await asyncio.sleep(poll_sec)
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


class CallResult(NamedTuple):
    """모델 호출 한 번의 결과.

    finish_reason — 공급자가 응답을 멈춘 이유(STOP·MAX_TOKENS 등, 문자열). 못 받으면 None.
    raw_response_id — 원래 응답 행(extraction_raw_responses). 기록하지 않았으면 None.
    reused — 모델을 부르지 않고 같은 입력의 지난 성공 응답을 되썼다 (W1-3).
             그때 raw_response_id 는 그 지난 행이다.
    """

    text: str
    usage: dict
    finish_reason: str | None
    raw_response_id: int | None = None
    reused: bool = False


def _finish_reason_of(res: object) -> str | None:
    """첫 후보의 종료 사유. SDK enum 이면 이름만 남긴다 (W1-2 가 MAX_TOKENS 를 본다)."""
    candidates = getattr(res, "candidates", None) or []
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    if reason is None:
        return None
    return getattr(reason, "name", None) or str(reason)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _call(prompt: str, media: list[Path], schema=None,
                max_output_tokens: int | None = None) -> CallResult:
    """(응답 텍스트, 공급자 usage, 종료 사유). usage 는 못 받으면 빈 dict 다 — 0 으로 채우지 않는다.

    잘린 응답(MAX_TOKENS)은 예외가 아니다 — 여기서는 그대로 돌려주고 재시도하지 않는다.
    같은 입력으로 다시 부르면 같은 자리에서 또 잘린다. 판정은 파싱 전에 호출부가 한다.
    `max_output_tokens` 가 None 이면 공급자 기본값을 쓴다.
    """
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
            max_output_tokens=max_output_tokens,
        ),
    )
    return CallResult(res.text or "", _usage_of(res), _finish_reason_of(res))


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




async def extract_facts(
    *, source_id: int, source_type: str, text: str,
    glossary: list[dict[str, str]], media: list[Path] = (),
    usage_sink=None, usage_context=None, raw_sink=None,
) -> FactExtractionResult:
    """map — 자료에서 **사실만** 뽑는다 (W1).

    카드를 만들지 않는다. 카드 스키마로 뽑으면 "한 카드에 한 대상" 규칙 때문에
    구간마다 카드 한 장 = 사실 한 개가 되고, 그러면 조립이 합칠 것이 없다.
    store-a 실측에서 map 이 39장을 만들고 조립이 36장으로 줄이는 데 그쳤다.
    """
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY 가 없다")

    prompt = render_facts_prompt(source_type=source_type, text=text, glossary=glossary,
                                 locator_hints=locator_hints(s))
    schema = facts_schema(s)

    media = list(media)
    started = time.perf_counter()
    reply = await _measured_call(prompt, media, usage_sink, usage_context,
                                 prompt_hash=_hash(prompt),
                                 schema=schema, raw_sink=raw_sink,
                                 max_output_tokens=getattr(s, "extract_max_output_tokens", None))
    usage = reply.usage
    elapsed = time.perf_counter() - started
    # 원래 응답은 _measured_call 이 이미 남겼다. 파싱 실패·잘림이어도 그 행은 남는다
    try:
        result = await raw_responses.parse_checked(
            _mark_sink(raw_sink, reply), usage_context, reply.raw_response_id, reply.finish_reason,
            lambda: schema.model_validate_json(reply.text), what="사실 추출")
    except raw_responses.TruncatedOutputError:
        # 잘림은 파싱 실패와 다르게 다룬다 — 호출부가 입력을 나눠 다시 뽑는다
        raise
    except Exception as e:
        raise RuntimeError(f"사실 추출 JSON 파싱 실패: {e}") from e
    result._raw_response_id = reply.raw_response_id

    logger.info("extract_facts source=%s %.1fs 사실 %d건 미해결 %d건 usage=%s",
                source_id, elapsed, len(result.assertions),
                len(result.unresolved), usage or "미보고")
    return result


async def assemble(
    *, source_id: int, facts: list[dict], category_names: list[str],
    glossary: list[dict], usage_sink=None, usage_context=None, raw_sink=None,
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

    prompt = render_assemble_prompt(facts=facts, category_names=category_names,
                                    glossary=glossary)

    started = time.perf_counter()
    reply = await _measured_call(prompt, [], usage_sink, usage_context,
                                 prompt_hash=_hash(prompt), raw_sink=raw_sink,
                                 max_output_tokens=getattr(s, "assemble_max_output_tokens", None))
    usage = reply.usage
    # 조립 출력이 잘리면 카드 일부를 잃는다. 나누지 않고 명확히 실패시킨다 —
    # 등록 경로는 저장한 추출 결과로 조립만 다시 시도한다 (strict)
    result = await raw_responses.parse_checked(
        _mark_sink(raw_sink, reply), usage_context, reply.raw_response_id, reply.finish_reason,
        lambda: ExtractionResult.model_validate_json(reply.text), what="카드 조립")
    result._raw_response_id = reply.raw_response_id
    logger.info("assemble source=%s 사실 %d건 → 카드 %d장 (%.1fs) usage=%s",
                source_id, len(facts), len(result.cards),
                time.perf_counter() - started, usage or "미보고")
    return result


def render_facts_prompt(*, source_type: str, text: str, glossary,
                        locator_hints: bool = False) -> str:
    """사실 추출 프롬프트 완성본. 재사용 키(W1-3)는 이 완성본 전체를 hash 한다.

    `locator_hints` 는 W1-4 위치 표지 판을 고른다. 파일이 달라 키도 따로 갈린다.
    """
    path = FACTS_LOCATOR_PROMPT_PATH if locator_hints else FACTS_PROMPT_PATH
    return (path.read_text(encoding="utf-8")
            .replace("{glossary}", _glossary_block(list(glossary or [])))
            .replace("{source_type}", source_type)
            .replace("{transcript}", text))


def render_assemble_prompt(*, facts: list[dict], category_names: list[str], glossary) -> str:
    """카드 조립 프롬프트 완성본."""
    return (ASSEMBLE_PROMPT_PATH.read_text(encoding="utf-8")
            .replace("{categories}", _category_block(category_names))
            .replace("{glossary}", _glossary_block(list(glossary or [])))
            .replace("{facts_json}",
                     json.dumps(facts, ensure_ascii=False, indent=1)))


def _mark_sink(raw_sink, reply: "CallResult"):
    """되쓴 응답의 행은 이미 성공으로 표시돼 있다. 다시 표시하지 않는다."""
    return None if reply.reused else raw_sink


def _hash(text: str) -> str:
    """어느 프롬프트로 부른 호출인지. 프롬프트를 바꾼 뒤 원가가 왜 변했는지 되짚는다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _measured_call(prompt: str, media: list[Path], sink, context,
                         *, prompt_hash: str | None = None,
                         schema=None, raw_sink=None,
                         max_output_tokens: int | None = None) -> CallResult:
    """계측을 감싼 호출. context 가 없으면 계측·원래 응답 기록 없이 그대로 부른다.

    원래 응답은 **호출이 끝나고 파싱하기 전에** 남긴다 (W1-1). 저장은 짧은 연결로 하고
    모델 호출 동안에는 연결을 쥐지 않는다. 저장이 실패하면 멈춘다 — 기록 없는 추출은
    되짚을 수 없다 (`RawResponseWriteError` 가 그대로 올라간다).
    """
    from app.ingest import reuse
    from app.usage import recorder

    s = get_settings()
    schema = schema or ExtractionResult
    # 재사용 키 (W1-3) — 기록할 곳이 있으면 언제나 계산해 남긴다. 조회는 플래그가 켜졌을 때만
    key = None
    if raw_sink is not None and context is not None:
        key = await reuse.key_for(context, s, model=s.gemini_model, mode=s.ingest_mode,
                                  prompt=prompt, media=media, schema=schema,
                                  max_output_tokens=max_output_tokens)
        if reuse.lookup_allowed(context, s):
            hit = await reuse.find(raw_sink, context, key, schema)
            if hit is not None:
                await _ledger_reuse(sink, context, s, prompt_hash, hit)
                return CallResult(hit.response_text, {}, hit.finish_reason,
                                  hit.raw_response_id, reused=True)
    if context is None:
        reply = await _call(prompt, media, schema, max_output_tokens=max_output_tokens)
    else:
        async with recorder.attempt(sink, context, model=s.gemini_model,
                                    mode=s.ingest_mode, prompt_hash=prompt_hash) as rec:
            rec.measure_input(
                input_bytes=len(prompt.encode("utf-8")) + sum(
                    m.stat().st_size for m in media if m.exists()),
                frame_count=len(media) or None,
            )
            reply = await _call(prompt, media, schema, max_output_tokens=max_output_tokens)
            rec.reported_model = s.gemini_model
            if reply.usage:
                rec.observe(**reply.usage)
            else:
                rec.partial("공급자가 usage 를 보고하지 않았다")

    # 원가 receipt 를 확정한 뒤에 남긴다. 여기서 실패해도 호출 자체는 SUCCEEDED 다
    raw_id = await raw_responses.record(
        raw_sink, context, model=s.gemini_model, mode=s.ingest_mode,
        prompt_hash=prompt_hash, schema=schema, finish_reason=reply.finish_reason,
        response_text=reply.text, usage=reply.usage, reuse_key=key)
    return reply._replace(raw_response_id=raw_id)


async def _ledger_reuse(sink, context, s, prompt_hash, hit) -> None:
    """재사용을 원장에 남긴다 — 이번 실행의 논리 호출로, 비용 0(NOT_BILLABLE).

    원래 응답 행은 새로 만들지 않는다. 사유에 되쓴 행 ID 를 적어 어느 응답을 썼는지 잇는다.
    """
    from app.ingest.reuse import CACHE_STATE_REUSED
    from app.usage import recorder

    async with recorder.attempt(sink, context, model=s.gemini_model,
                                mode=s.ingest_mode, prompt_hash=prompt_hash) as rec:
        rec.not_billable(f"재사용: raw_response_id={hit.raw_response_id}")
        rec.cache_state = CACHE_STATE_REUSED
    logger.info("재사용 call=%s raw_response_id=%s — 모델을 부르지 않았다",
                context.logical_call_id, hit.raw_response_id)
