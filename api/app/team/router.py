"""인증된 내부 전용 평가 하네스 API.

게이트: JWT 에 scope="team" 이 있어야 한다. /auth 로그인 토큰에는 이 값이 없으므로
점주·직원 계정으로는 절대 들어올 수 없다. 발급은 scripts/dev_token.py --team 뿐이다.
인증을 우회하는 엔드포인트는 만들지 않는다.
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.deps import Db
from app.errors import ApiClaims, ApiError
from app.team import repository as repo
from app.team.metrics import aggregate
from app.team.runner import run_case
from app.team.schemas import (
    CaseBulkUpsertRequest,
    CaseList,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    RunCreateRequest,
    RunDetail,
    RunList,
)
from app.team.snapshot import code_version, prompt_version, settings_snapshot

logger = logging.getLogger(__name__)
router = APIRouter()


async def require_team(claims: ApiClaims) -> dict[str, Any]:
    if str(claims.get("scope", "")) != "team":
        raise ApiError(403, "TEAM_ONLY", "내부 평가 도구 권한이 필요합니다.")
    if claims.get("store_id") is None:
        raise ApiError(403, "STORE_REQUIRED", "평가 대상 매장이 지정되지 않았습니다.")
    return claims


TeamClaims = Annotated[dict[str, Any], Depends(require_team)]


def _store_id(claims: dict[str, Any]) -> int:
    """요청 본문이 아니라 JWT 에서 꺼낸다 (불변식 4)."""
    return int(claims["store_id"])


def _json(value: Any) -> dict[str, Any]:
    """asyncpg 가 jsonb 를 문자열로 돌려주는 경우를 흡수한다."""
    if isinstance(value, str):
        return json.loads(value)
    return dict(value or {})


def _case(row) -> EvaluationCase:
    return EvaluationCase(
        case_id=int(row["case_id"]),
        case_key=row["case_key"],
        question=row["question"],
        expected_kind=row["expected_kind"],
        expected_card_ids=[int(c) for c in row["expected_card_ids"]],
        expected_facts=list(row["expected_facts"]),
        expected_category=row["expected_category"],
        expected_miss_reason=row["expected_miss_reason"],
        question_style=row["question_style"],
        qa_relation=row["qa_relation"],
        notes=row["notes"],
        is_active=bool(row["is_active"]),
        updated_at=row["updated_at"],
    )


def _run(row) -> EvaluationRun:
    return EvaluationRun(
        run_id=int(row["run_id"]),
        store_id=int(row["store_id"]),
        label=row["label"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        code_version=row["code_version"],
        prompt_version=row["prompt_version"],
        answer_model=row["answer_model"],
        embedding_model=row["embedding_model"],
        answer_mode=row["answer_mode"],
        retrieval_threshold=float(row["retrieval_threshold"]),
        retrieval_strong_score=float(row["retrieval_strong_score"]),
        feature_flags=_json(row["feature_flags"]),
        settings=_json(row["settings"]),
        metrics=_json(row["metrics"]),
        case_count=int(row["case_count"]),
        notes=row["notes"],
    )


def _result(row) -> EvaluationResult:
    return EvaluationResult(
        case_key=row["case_key"],
        question=row["question"],
        expected_kind=row["expected_kind"],
        actual_kind=row["actual_kind"],
        kind_correct=bool(row["kind_correct"]),
        miss_reason=row["miss_reason"],
        expected_card_ids=[int(c) for c in row["expected_card_ids"]],
        retrieved_card_ids=[int(c) for c in row["retrieved_card_ids"]],
        citation_card_ids=[int(c) for c in row["citation_card_ids"]],
        expected_hit_rank=row["expected_hit_rank"],
        reciprocal_rank=(
            float(row["reciprocal_rank"]) if row["reciprocal_rank"] is not None else None
        ),
        ndcg=float(row["ndcg"]) if row["ndcg"] is not None else None,
        ndcg_k=row["ndcg_k"],
        top_card_id=row["top_card_id"],
        wrong_card=bool(row["wrong_card"]),
        answer_source=row["answer_source"],
        grounding_status=row["grounding_status"],
        answer_text=row["answer_text"],
        citation_count=int(row["citation_count"]),
        citation_precision=(
            float(row["citation_precision"]) if row["citation_precision"] is not None else None
        ),
        fact_coverage=(
            float(row["fact_coverage"]) if row["fact_coverage"] is not None else None
        ),
        ungrounded=bool(row["ungrounded"]),
        retrieve_latency_ms=row["retrieve_latency_ms"],
        answer_latency_ms=row["answer_latency_ms"],
        total_latency_ms=row["total_latency_ms"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        passed=bool(row["passed"]),
        failure_kind=row["failure_kind"],
        error=row["error"],
    )


# ── 골든셋 문항 ────────────────────────────────────────────────────────────

@router.put("/evaluation-cases", response_model=CaseList)
async def upsert_cases(req: CaseBulkUpsertRequest, db: Db, claims: TeamClaims):
    """골든셋 등록·갱신. case_key 가 같으면 덮어쓴다 (정답지는 갱신 대상이다)."""
    store_id = _store_id(claims)
    rows = []
    async with db.transaction():
        for case in req.cases:
            rows.append(await repo.upsert_case(db, store_id, case.model_dump()))
    return CaseList(cases=[_case(r) for r in rows])


@router.get("/evaluation-cases", response_model=CaseList)
async def get_cases(
    db: Db,
    claims: TeamClaims,
    include_inactive: bool = Query(default=False),
):
    store_id = _store_id(claims)
    rows = await repo.list_cases(db, store_id, active_only=not include_inactive)
    return CaseList(cases=[_case(r) for r in rows])


# ── 실행 ──────────────────────────────────────────────────────────────────

@router.post("/evaluations", response_model=RunDetail, status_code=201)
async def create_evaluation(req: RunCreateRequest, db: Db, claims: TeamClaims):
    """골든셋을 실행하고 결과를 남긴다. 이전 실행은 건드리지 않는다."""
    store_id = _store_id(claims)
    cases = await repo.list_cases(db, store_id, active_only=True, case_keys=req.case_keys)
    if req.case_keys:
        # 지정한 문항이 하나라도 없으면 조용히 줄여서 돌리지 않는다.
        # 문항 수가 달라진 실행끼리는 비교가 성립하지 않는다
        missing = sorted(set(req.case_keys) - {c["case_key"] for c in cases})
        if missing:
            raise ApiError(
                422,
                "UNKNOWN_EVALUATION_CASES",
                "등록되지 않았거나 비활성인 문항이 있습니다.",
                details={"case_keys": missing},
            )
    if not cases:
        raise ApiError(
            422,
            "NO_EVALUATION_CASES",
            "실행할 골든셋 문항이 없습니다. 먼저 문항을 등록해 주세요.",
        )

    snapshot = settings_snapshot(req.feature_flags)
    run = await repo.create_run(
        db,
        store_id,
        {
            "label": req.label,
            "code_version": code_version(),
            "prompt_version": prompt_version(),
            "answer_model": snapshot["answer_model"],
            "embedding_model": snapshot["embedding_model"],
            "answer_mode": snapshot["answer_mode"],
            "retrieval_threshold": snapshot["retrieval_threshold"],
            "retrieval_strong_score": snapshot["retrieval_strong_score"],
            "feature_flags": req.feature_flags,
            "settings": snapshot,
            "case_count": len(cases),
            "notes": req.notes,
            "created_by": claims.get("user_id"),
        },
    )
    run_id = int(run["run_id"])
    logger.info(
        "evaluation run started: run_id=%s store_id=%s label=%s cases=%s code=%s prompt=%s",
        run_id, store_id, req.label, len(cases), run["code_version"], run["prompt_version"],
    )

    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(
            await run_case(
                db,
                store_id,
                dict(case),
                top_k=req.top_k,
                cost_per_1k=req.cost_per_1k,
            )
        )

    metrics = aggregate(rows)
    status = "FAILED" if metrics.get("error_count", 0) == len(rows) else "SUCCEEDED"
    async with db.transaction():
        await repo.insert_results(db, run_id, store_id, rows)
        finished = await repo.finish_run(
            db, run_id, store_id, status=status, metrics=metrics, case_count=len(rows)
        )

    logger.info(
        "evaluation run finished: run_id=%s status=%s pass_rate=%s ungrounded=%s p95=%sms",
        run_id, status, metrics.get("pass_rate"),
        metrics.get("ungrounded_count"), metrics.get("latency_p95_ms"),
    )
    results = await repo.list_results(db, store_id, run_id)
    return RunDetail(run=_run(finished), results=[_result(r) for r in results])


@router.get("/evaluations", response_model=RunList)
async def list_evaluations(
    db: Db,
    claims: TeamClaims,
    label: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
    before_id: int | None = Query(default=None, ge=1),
):
    store_id = _store_id(claims)
    rows = await repo.list_runs(db, store_id, label=label, limit=limit, before_id=before_id)
    next_before = int(rows[-1]["run_id"]) if len(rows) == limit else None
    return RunList(runs=[_run(r) for r in rows], next_before_id=next_before)


@router.get("/evaluations/{run_id}", response_model=RunDetail)
async def get_evaluation(
    run_id: int,
    db: Db,
    claims: TeamClaims,
    failed_only: bool = Query(default=False),
):
    store_id = _store_id(claims)
    run = await repo.get_run(db, store_id, run_id)
    if run is None:
        raise ApiError(404, "EVALUATION_NOT_FOUND", "평가 실행을 찾을 수 없습니다.")
    results = await repo.list_results(db, store_id, run_id, failed_only=failed_only)
    return RunDetail(run=_run(run), results=[_result(r) for r in results])
