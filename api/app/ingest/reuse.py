"""같은 입력 재사용 (W1-3).

같은 자료를 다시 처리할 때(작업 재시도·재처리) 모델에 같은 입력을 또 보내면 돈만 나가고
결과는 같거나, 온도 0 이어도 조금 흔들려 원장에 비슷한 사실이 겹친다. 모델 입력 전체를
덮는 재사용 키로 지난 성공 응답을 찾아, 있으면 모델을 부르지 않고 그 응답을 파싱해 쓴다.

규칙:
  - **키는 모델 입력 전체를 덮는다.** 매장·자료·단계·모델·모드·완성된 프롬프트(용어집·구간
    본문·카테고리 포함) 전체 hash·첨부 바이트 hash(순서·확장자 포함)·응답 스키마 버전·온도·
    출력 상한·PDF/영상 입력 모드. 하나라도 바뀌면 키가 바뀌어 새 호출로 남는다.
  - **평가 정답은 키 입력이 아니다.** 런타임 입력만 넣는다. 정답이 입력에 섞일 자리가 없다.
  - **파싱에 성공한 같은 매장 행만** 재사용한다. 잘린 응답(MAX_TOKENS)·파싱 실패·미판정은
    제외한다. 매장은 키에도, 조회 WHERE 에도 들어간다 (D1).
  - **평가 실행은 기본으로 재사용하지 않는다.** 평가는 모델 동작의 흔들림을 잰다(D17/D18 반복).
    지난 응답을 되쓰면 반복이 전부 같아져 변동 측정이 무너진다. 별도 플래그로만 켠다.
  - 조회 실패는 재사용을 건너뛸 뿐 추출을 멈추지 않는다 — 재사용은 절약이지 정합성 조건이 아니다.
  - 재사용은 원래 응답 행을 새로 만들지 않는다. 원장(ai_usage_attempts)에 이번 실행의 논리
    호출로 `cache_state='REUSED'`·NOT_BILLABLE(비용 0)·사유 `재사용: raw_response_id=N` 을 남긴다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.ingest.raw_responses import schema_version

logger = logging.getLogger(__name__)

# 키 형식 버전. 키에 넣는 항목을 바꾸면 올린다 — 옛 키와 섞이지 않는다
KEY_PREFIX = "rk1:"

# 원장 cache_state 값 — 지난 성공 응답을 되썼다
CACHE_STATE_REUSED = "REUSED"


@dataclass(frozen=True)
class ReusableResponse:
    """재사용할 지난 성공 응답."""

    raw_response_id: int
    response_text: str
    finish_reason: str | None


def media_digests(media) -> list[list[str]]:
    """첨부를 [확장자, sha256] 순서 목록으로. 파일 이름이 아니라 바이트를 본다.

    확장자는 MIME 을 정하므로 넣는다. 없는 파일은 호출에서도 빠지므로 'missing' 으로 둔다.
    """
    out = []
    for m in media or []:
        path = Path(m)
        digest = (hashlib.sha256(path.read_bytes()).hexdigest()
                  if path.exists() else "missing")
        out.append([path.suffix.lower(), digest])
    return out


def reuse_key(*, store_id, source_id, stage: str, model: str, mode: str,
              prompt: str, media_digests: list, schema_version: str | None,
              temperature, max_output_tokens, pdf_input_mode, video_input_mode,
              thinking_level: str | None = None) -> str:
    """모델 입력 전체의 hash. 같은 입력이면 같은 키, 하나라도 다르면 다른 키."""
    payload = dict(
        store_id=str(store_id), source_id=None if source_id is None else str(source_id),
        stage=stage, model=model, mode=mode,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        media=media_digests, schema_version=schema_version,
        temperature=temperature, max_output_tokens=max_output_tokens,
        pdf_input_mode=pdf_input_mode, video_input_mode=video_input_mode,
    )
    # 사고 수준은 정한 경우에만 넣는다 — 넣지 않은 기존 호출의 키는 바뀌지 않는다
    if thinking_level is not None:
        payload["thinking_level"] = thinking_level
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return KEY_PREFIX + hashlib.sha256(body.encode("utf-8")).hexdigest()


async def key_for(context, settings, *, model: str, mode: str, prompt: str, media,
                  schema, max_output_tokens, thinking_level: str | None = None) -> str | None:
    """호출 문맥에서 키를 만든다. 매장 문맥이 없으면(미리보기) 키도 없다.

    큰 첨부(영상)의 hash 는 이벤트 루프를 막지 않게 스레드에서 계산한다.
    키를 만들지 못하면(첨부 읽기 실패·스키마 버전 계산 실패 등) 경고만 남기고 None 이다 —
    재사용은 절약이지 정합성 조건이 아니므로 추출을 멈추지 않는다(키 없는 원래 응답 행이 된다).
    """
    if context is None:
        return None
    try:
        digests = await asyncio.to_thread(media_digests, list(media or []))
        # 테스트 대역(SimpleNamespace)에 없는 설정은 기본값으로 본다
        return reuse_key(
            store_id=context.store_id, source_id=context.source_id, stage=context.stage,
            model=model, mode=mode, prompt=prompt, media_digests=digests,
            schema_version=schema_version(schema),
            temperature=getattr(settings, "extract_temperature", None),
            max_output_tokens=max_output_tokens,
            pdf_input_mode=getattr(settings, "pdf_input_mode", None),
            video_input_mode=getattr(settings, "video_input_mode", None),
            thinking_level=thinking_level,
        )
    except Exception as exc:
        logger.warning("재사용 키 계산 실패 — 키 없이 추출을 계속한다 type=%s: %s",
                       type(exc).__name__, exc)
        return None


def is_evaluation(context) -> bool:
    return context.cost_purpose == "EVALUATION" or context.extraction_run_id is not None


def lookup_allowed(context, settings) -> bool:
    """재사용 조회를 할지. 기본 꺼짐, 평가 실행은 별도 플래그가 있어야 한다."""
    if context is None or not getattr(settings, "extract_reuse_enabled", False):
        return False
    if is_evaluation(context):
        return bool(getattr(settings, "extract_reuse_for_evaluation", False))
    return True


async def find(raw_sink, context, key: str | None, schema) -> ReusableResponse | None:
    """같은 매장의 같은 키 성공 응답. 없거나, 조회가 실패하거나, 지금 스키마로 안 읽히면 None."""
    finder = getattr(raw_sink, "find_reusable", None)
    if finder is None or context is None or key is None:
        return None
    try:
        hit = await finder(int(context.store_id), key)
    except Exception as exc:
        logger.warning("재사용 조회 실패 — 모델을 부른다 type=%s", type(exc).__name__)
        return None
    if hit is None:
        return None
    try:
        # 스키마 버전이 키에 들어가지만, 검증 코드만 바뀐 경우를 막는다. 안 읽히면 새로 부른다
        schema.model_validate_json(hit.response_text)
    except Exception:
        logger.warning("재사용 후보가 지금 스키마로 읽히지 않는다 raw_response_id=%s — 모델을 부른다",
                       hit.raw_response_id)
        return None
    return hit
