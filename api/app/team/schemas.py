"""평가 하네스 요청·응답 모델."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ExpectedKind = Literal["HIT", "MISS", "REFUSE", "SAFE_ROUTE"]
QuestionStyle = Literal[
    "CANONICAL", "SYNONYM", "SLANG", "ABBREVIATION", "TYPO", "STT_VARIANT", "FOLLOW_UP"
]
QaRelation = Literal["IDENTICAL", "NEW", "SUPPLEMENT", "CONFLICT"]


class CaseUpsertRequest(BaseModel):
    case_key: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=2, max_length=500)
    expected_kind: ExpectedKind
    expected_card_ids: list[int] = Field(default_factory=list, max_length=20)
    expected_facts: list[str] = Field(default_factory=list, max_length=20)
    expected_category: str | None = Field(default=None, max_length=100)
    expected_miss_reason: str | None = Field(default=None, max_length=40)
    question_style: QuestionStyle = "CANONICAL"
    qa_relation: QaRelation | None = None
    notes: str | None = None
    is_active: bool = True


class CaseBulkUpsertRequest(BaseModel):
    cases: list[CaseUpsertRequest] = Field(min_length=1, max_length=200)


class EvaluationCase(BaseModel):
    case_id: int
    case_key: str
    question: str
    expected_kind: ExpectedKind
    expected_card_ids: list[int]
    expected_facts: list[str]
    expected_category: str | None
    expected_miss_reason: str | None
    question_style: str
    qa_relation: str | None
    notes: str | None
    is_active: bool
    updated_at: datetime


class CaseList(BaseModel):
    cases: list[EvaluationCase]


class RunCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    case_keys: list[str] | None = Field(default=None, max_length=200)
    top_k: int = Field(default=5, ge=1, le=20)
    feature_flags: dict[str, Any] = Field(default_factory=dict)
    # 모델 단가는 시점마다 달라서 코드에 박지 않는다. 준 실행만 비용이 계산된다
    cost_per_1k: dict[str, float] | None = None
    notes: str | None = None


class EvaluationRun(BaseModel):
    run_id: int
    store_id: int
    label: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    code_version: str
    prompt_version: str
    answer_model: str
    embedding_model: str
    answer_mode: str
    retrieval_threshold: float
    retrieval_strong_score: float
    feature_flags: dict[str, Any]
    settings: dict[str, Any]
    metrics: dict[str, Any]
    case_count: int
    notes: str | None


class RunList(BaseModel):
    runs: list[EvaluationRun]
    next_before_id: int | None = None


class EvaluationResult(BaseModel):
    case_key: str
    question: str
    expected_kind: str
    actual_kind: str
    kind_correct: bool
    miss_reason: str | None
    expected_card_ids: list[int]
    retrieved_card_ids: list[int]
    citation_card_ids: list[int]
    expected_hit_rank: int | None
    reciprocal_rank: float | None
    ndcg: float | None
    ndcg_k: int | None
    top_card_id: int | None
    wrong_card: bool
    answer_source: str | None
    grounding_status: str | None
    answer_text: str | None
    citation_count: int
    citation_precision: float | None
    fact_coverage: float | None
    ungrounded: bool
    retrieve_latency_ms: int | None
    answer_latency_ms: int | None
    total_latency_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    passed: bool
    failure_kind: str | None
    error: str | None


class RunDetail(BaseModel):
    run: EvaluationRun
    results: list[EvaluationResult]
