"""모델 원래 응답 보존 (W1-1).

추출 결과가 이상할 때 "모델이 실제로 뭐라고 답했나" 를 되짚으려면 응답 원문이 남아야
한다. 지금까지는 파싱에 실패하면 응답이 그대로 사라져, 잘린 출력인지 형식 오류인지
프롬프트 문제인지 가를 수 없었다.

규칙:
  - **파싱 전에 저장한다.** 파싱 실패 응답도 행이 남는다. 파싱 결과는 뒤에 한 번만 표시한다.
  - **모델 호출 동안 DB 연결을 쥐지 않는다.** 호출이 끝난 뒤 풀에서 짧게 빌려 쓴다.
  - **저장이 실패하면 멈춘다.** 기록 없는 추출은 되짚을 수 없다. 그 호출의 결과는 쓰지
    않고 예외를 올린다 (구간 추출이면 그 구간을 잃은 것으로 센다 — PARTIAL 재시도 대상).
    돈은 이미 나갔지만, 되짚을 수 없는 사실을 원장에 넣는 것보다 다시 뽑는 편을 택한다.
  - 파싱 결과 표시(parsed_ok) 실패는 멈추지 않는다. 원문은 이미 남았고, 미판정(null)
    행은 재사용 조회(W1-3)에서 빠질 뿐이다.
  - 매장 문맥(UsageContext)이 없는 호출(미리보기 스크립트·단위 테스트)은 기록하지 않는다.
    귀속할 매장이 없는 행은 만들지 않는다 (D1).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 오류 원문은 길 수 있다. 되짚기에 충분한 앞부분만 남긴다
_ERROR_MAX = 2000


class RawResponseWriteError(RuntimeError):
    """원래 응답을 남기지 못했다. 추출을 멈춘다."""


class TruncatedOutputError(RuntimeError):
    """출력 token 상한에 닿아 응답이 잘렸다 (W1-2). 성공으로 처리하지 않는다.

    호출 예외가 아니므로 `_call` 의 재시도에 걸리지 않는다 — 같은 입력을 되풀이하면
    같은 자리에서 또 잘린다. 입력을 나눠 다시 뽑는 일은 호출부(pipeline)가 한다.
    """


# 공급자가 "출력 상한 때문에 멈췄다" 고 알리는 종료 사유 (google-genai FinishReason 이름)
TRUNCATED_FINISH_REASONS = frozenset({"MAX_TOKENS"})


@dataclass(frozen=True)
class RawResponse:
    """호출 한 번의 공급자 응답 원형."""

    stage: str                      # EXTRACT | ASSEMBLE
    model: str
    mode: str                       # real | mock
    prompt_hash: str | None
    schema_version: str | None
    finish_reason: str | None       # SDK enum 이면 .name 문자열
    response_text: str
    usage: dict[str, Any] = field(default_factory=dict)
    # 같은 입력 재사용 조회 열쇠 (W1-3, app.ingest.reuse). 매장 문맥이 없으면 None
    reuse_key: str | None = None


class RawResponseSink(Protocol):
    async def save(self, context, response: RawResponse) -> int: ...
    async def mark_parsed(self, store_id: int, raw_response_id: int, *,
                          parsed_ok: bool, error: str | None) -> None: ...


def schema_version(schema) -> str | None:
    """어느 응답 스키마로 받은 응답인지. 스키마가 바뀌면 같은 프롬프트라도 재사용할 수 없다."""
    if schema is None:
        return None
    body = json.dumps(schema.model_json_schema(), sort_keys=True, ensure_ascii=False)
    return f"{schema.__name__}/{hashlib.sha256(body.encode('utf-8')).hexdigest()[:12]}"


def _int_or_none(value) -> int | None:
    return int(value) if value is not None else None


async def insert_raw_response(
    pool, store_id: int, *, source_id: int | None, job_id: int | None,
    extraction_run_id: int | None, run_tag: int | None, segment_id: str | None,
    logical_call_id: str | None, response: RawResponse,
) -> int:
    """응답 원문을 남기고 raw_response_id 를 돌려준다. 연결은 이 한 문장만큼만 빌린다."""
    from app.ingest.resilience import setting
    try:
        async with asyncio.timeout(setting("ingest_db_timeout_seconds")), pool.acquire() as conn:
            return int(await conn.fetchval(
                """
                insert into extraction_raw_responses (
                  store_id, source_id, job_id, extraction_run_id, run_tag,
                  segment_id, logical_call_id, stage, model, mode,
                  prompt_hash, schema_version, finish_reason, response_text, usage,
                  reuse_key
                )
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16)
                returning raw_response_id
                """,
                store_id, source_id, job_id, extraction_run_id, run_tag,
                segment_id, logical_call_id, response.stage, response.model,
                response.mode, response.prompt_hash, response.schema_version,
                response.finish_reason, response.response_text,
                json.dumps(response.usage or {}, ensure_ascii=False, default=str),
                response.reuse_key,
            ))
    except Exception as exc:
        raise RawResponseWriteError(f"원래 응답 저장 실패: {type(exc).__name__}: {exc}") from exc


async def mark_parse_result(pool, store_id: int, raw_response_id: int, *,
                            parsed_ok: bool, error: str | None) -> None:
    """파싱 결과를 한 번만 표시한다. 이미 판정된 행은 트리거가 막는다."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            update extraction_raw_responses
               set parsed_ok = $3, error = $4
             where store_id = $1 and raw_response_id = $2 and parsed_ok is null
            """,
            store_id, raw_response_id, parsed_ok,
            (error or None) and error[:_ERROR_MAX],
        )


async def find_reusable_response(pool, store_id: int, reuse_key: str):
    """같은 매장·같은 키로 파싱에 성공한 가장 이른 응답 (W1-3). 없으면 None.

    잘린 응답은 파싱 성공으로 표시되지 않지만, 종료 사유로도 한 번 더 거른다.
    부분 인덱스(idx_raw_responses_reuse: store_id, reuse_key where parsed_ok)를 탄다.
    """
    from app.ingest.reuse import ReusableResponse

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select raw_response_id, response_text, finish_reason
              from extraction_raw_responses
             where store_id = $1 and reuse_key = $2 and parsed_ok
               and coalesce(finish_reason, '') <> all($3::text[])
             order by raw_response_id
             limit 1
            """,
            store_id, reuse_key, sorted(TRUNCATED_FINISH_REASONS),
        )
    if row is None:
        return None
    return ReusableResponse(int(row["raw_response_id"]), row["response_text"],
                            row["finish_reason"])


async def list_raw_responses(conn, store_id: int, *, source_id: int | None = None):
    """매장 안의 원래 응답. 다른 매장 행은 보이지 않는다 (D1)."""
    return await conn.fetch(
        """
        select raw_response_id, store_id, source_id, job_id, extraction_run_id,
               run_tag, segment_id, logical_call_id, stage, model, mode,
               prompt_hash, schema_version, reuse_key, finish_reason,
               response_text, usage, parsed_ok, error, created_at
          from extraction_raw_responses
         where store_id = $1 and ($2::bigint is null or source_id = $2)
         order by raw_response_id
        """,
        store_id, source_id,
    )


class DbRawResponseSink:
    """pipeline 이 만든다. 실행 표지(run_tag)는 UsageContext 에 없어 여기에 묶는다."""

    def __init__(self, pool, *, run_tag: int | None = None) -> None:
        self._pool = pool
        self._run_tag = run_tag

    async def save(self, context, response: RawResponse) -> int:
        return await insert_raw_response(
            self._pool, int(context.store_id),
            source_id=_int_or_none(context.source_id),
            job_id=_int_or_none(context.job_id),
            extraction_run_id=_int_or_none(context.extraction_run_id),
            run_tag=self._run_tag,
            segment_id=context.segment_id,
            logical_call_id=context.logical_call_id,
            response=response,
        )

    async def find_reusable(self, store_id: int, reuse_key: str):
        return await find_reusable_response(self._pool, store_id, reuse_key)

    async def mark_parsed(self, store_id: int, raw_response_id: int, *,
                          parsed_ok: bool, error: str | None) -> None:
        await mark_parse_result(self._pool, store_id, raw_response_id,
                                parsed_ok=parsed_ok, error=error)


async def record(sink: RawResponseSink | None, context, *, model: str, mode: str,
                 prompt_hash: str | None, schema, finish_reason: str | None,
                 response_text: str, usage: dict | None,
                 reuse_key: str | None = None) -> int | None:
    """응답을 파싱 전에 남긴다. 기록할 곳·매장이 없으면 None.

    sink 는 있는데 매장 문맥이 없으면 멈춘다 — 조용히 넘기면 기록이 빠진 줄 모른다.
    """
    if sink is None:
        return None
    if context is None:
        raise RawResponseWriteError("원래 응답을 귀속할 매장 문맥(usage_context)이 없다")
    response = RawResponse(
        stage=context.stage, model=model, mode=mode, prompt_hash=prompt_hash,
        schema_version=schema_version(schema), finish_reason=finish_reason,
        response_text=response_text, usage=dict(usage or {}), reuse_key=reuse_key,
    )
    from app.ingest.resilience import retry_io
    return await retry_io(lambda: sink.save(context, response), stage="raw.save")


async def parse_recorded(sink: RawResponseSink | None, context,
                         raw_response_id: int | None, parse: Callable[[], T]) -> T:
    """파싱하고 결과를 표시한다. 파싱 예외는 그대로 올린다 (행은 이미 남았다)."""
    try:
        value = parse()
    except Exception as exc:
        await _mark(sink, context, raw_response_id, False, f"{type(exc).__name__}: {exc}")
        raise
    await _mark(sink, context, raw_response_id, True, None)
    return value


async def parse_checked(sink: RawResponseSink | None, context, raw_response_id: int | None,
                        finish_reason: str | None, parse: Callable[[], T], *,
                        what: str = "응답") -> T:
    """잘린 응답을 거절한 뒤 파싱한다 (W1-2).

    잘린 응답은 JSON 이 우연히 맞아도 뒷부분을 잃은 것이다. 파싱하지 않고
    원래 응답 행을 parsed_ok=false·사유와 함께 표시한 뒤 `TruncatedOutputError` 를 올린다.
    표시는 `parse_recorded` 의 같은 경로를 쓴다.
    """
    if finish_reason in TRUNCATED_FINISH_REASONS:
        def _reject() -> T:
            raise TruncatedOutputError(
                f"{what} 출력이 잘렸다 (finish_reason={finish_reason}) — 성공으로 처리하지 않는다")
        return await parse_recorded(sink, context, raw_response_id, _reject)
    return await parse_recorded(sink, context, raw_response_id, parse)


async def _mark(sink, context, raw_response_id, ok: bool, error: str | None) -> None:
    if sink is None or context is None or raw_response_id is None:
        return
    try:
        await sink.mark_parsed(int(context.store_id), raw_response_id,
                               parsed_ok=ok, error=error)
    except Exception as exc:
        # 원문은 이미 남았다. 표시만 못 했으므로 추출은 멈추지 않는다 (미판정 = 재사용 제외)
        logger.warning("원래 응답 파싱 결과 표시 실패 raw_response_id=%s type=%s",
                       raw_response_id, type(exc).__name__)
