"""준혁 (feat/input) — /ingest/* 요청·응답 계약과 추출 결과 스키마.

추출 결과는 개발가이드 6-2 의 JSON 과 1:1 이다.
이 클래스가 곧 Gemini 의 response_schema 이므로, 필드를 바꾸면 프롬프트도 같이 바꾼다.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SourceType = Literal["VOICE", "VIDEO", "KAKAO", "SCAN"]
SourceStatus = Literal["UPLOADED", "PROCESSING", "DONE", "FAILED"]


# ── 추출 결과 (Gemini response_schema) ─────────────────────────────────────

class ExtractedFact(BaseModel):
    object_name: str
    attribute: str
    value: str
    confidence: float = Field(ge=0, le=1)
    # 원장에 적힌 사실의 이름표. 조립이 어느 사실을 골랐는지 잇는다 (W1).
    # 빈 값이면 잇지 못한 것이고, 그것도 세어서 드러낸다
    ref: str = ""


class Evidence(BaseModel):
    source_id: int = 0
    timestamp_sec: int = 0


class ExtractedCard(BaseModel):
    category_name: str
    title: str
    content: str
    confidence: float = Field(ge=0, le=1)
    facts: list[ExtractedFact] = []
    evidence: Evidence = Evidence()


class ExtractionResult(BaseModel):
    cards: list[ExtractedCard] = []
    unresolved: list[str] = []


# ── 사실 추출 (W1) ─────────────────────────────────────────────────────────
# 카드가 아니라 **사실**을 뽑는다. 카드 스키마로 뽑으면 "한 카드에 한 대상" 규칙
# 때문에 카드 한 장이 사실 한 개가 되고, 조립이 합칠 것이 없어진다.
#
# 선택 필드에 None 대신 빈 값을 쓴다 — Gemini response_schema 가 nullable 을
# 일관되게 다루지 못해, 빈 문자열/0 으로 받고 코드에서 None 으로 바꾼다.

class ExtractedAssertion(BaseModel):
    """자료에서 확인된 사실 하나. 한 주장 = 한 건이다."""

    local_ref: str                      # 이 출력 안에서만 쓰는 이름표 (f1, f2…)
    original_assertion: str             # 원문 그대로. 값은 이것의 해석이다
    subject: str
    attribute: str
    value: str
    variant: str = ""                   # HOT / ICE / 사이즈. 모르면 빈 값
    unit: str = ""
    polarity: Literal["AFFIRM", "NEGATE"] = "AFFIRM"
    conditions: list[str] = []          # "포장 주문일 때만"
    exceptions: list[str] = []          # "재고 없으면 대체"
    order: int = 0                      # 절차의 자리. 없으면 0
    requires: list[str] = []            # 먼저 지켜야 하는 사실의 local_ref
    category_name: str = ""
    evidence: Evidence = Evidence()
    confidence: float = Field(ge=0, le=1)
    # 서버가 채운다. 모델이 보내는 값이 아니다 — 어느 구간에서 나왔는지 표시용
    segment_id: str | None = None

    def as_variant(self) -> str | None:
        return self.variant.strip().upper() or None

    def as_order(self) -> int | None:
        return self.order if self.order and self.order >= 1 else None


class FactExtractionResult(BaseModel):
    assertions: list[ExtractedAssertion] = []
    unresolved: list[str] = []


# ── 요청 ───────────────────────────────────────────────────────────────────

class VoiceMeta(BaseModel):
    audio_format: Literal["mp3", "m4a", "wav"]
    record_method: Literal["UPLOAD", "DIRECT_RECORD"] = "UPLOAD"
    duration_sec: int = 0          # 모르면 0. 전처리에서 ffprobe 로 채운다
    sample_rate: int | None = None


class VideoMeta(BaseModel):
    video_format: Literal["mp4", "mov"]
    duration_sec: int = 0
    resolution: str | None = None
    fps: int | None = None


class KakaoMeta(BaseModel):
    import_type: Literal["TXT_EXPORT", "SCREENSHOT"] = "TXT_EXPORT"
    room_name: str | None = None


class ScanMeta(BaseModel):
    doc_type: Literal["PDF", "JPG", "PNG"]
    doc_category: Literal["MENU_BOARD", "MANUAL", "RECIPE", "ETC"] | None = None
    page_count: int = 1


class UploadUrlRequest(BaseModel):
    """브라우저가 Storage 에 직접 올리기 위한 1회용 서명 URL 요청."""
    source_type: SourceType
    filename: str = Field(max_length=200)      # 확장자 판별에만 쓴다
    file_size: int | None = Field(default=None, ge=0)


class UploadUrlResponse(BaseModel):
    upload_url: str      # 브라우저가 이 주소로 PUT 한다
    file_url: str        # 업로드 후 /ingest/sources 에 그대로 넘길 값


class CreateSourceRequest(BaseModel):
    """프론트가 Storage 에 올린 뒤 호출한다. 파일 바이너리를 보내지 않는다."""
    source_type: SourceType
    file_url: str = Field(max_length=500)   # Storage 경로 또는 서명 URL
    title: str | None = Field(default=None, max_length=200)
    file_size: int | None = Field(default=None, ge=0)
    content_hash: str | None = Field(default=None, max_length=64)
    mime_type: str | None = Field(default=None, max_length=100)
    original_filename: str | None = Field(default=None, max_length=200)
    meta: VoiceMeta | VideoMeta | KakaoMeta | ScanMeta | None = None

    @field_validator("content_hash")
    @classmethod
    def valid_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError("content_hash는 SHA-256 64자리여야 합니다.")
        return normalized


class CategoryToggle(BaseModel):
    category_name: str = Field(max_length=50)
    is_enabled: bool


class UpdateCategoriesRequest(BaseModel):
    """켜짐 여부만 바꾼다. 새 카테고리를 만들지 않는다."""
    categories: list[CategoryToggle]


class CategoryOut(BaseModel):
    category_id: int
    category_name: str
    is_enabled: bool
    sort_order: int


class ProcessRequest(BaseModel):
    source_id: int
    force: bool = False     # DONE 인 자료를 다시 돌린다


# ── 응답 ───────────────────────────────────────────────────────────────────

class SourceCreated(BaseModel):
    source_id: int
    status: SourceStatus
    duplicate: bool = False     # content_hash 가 같은 자료가 이미 있었다


class StatusResponse(BaseModel):
    source_id: int
    status: SourceStatus
    error_message: str | None = None
    processed_at: str | None = None
    card_count: int = 0


# ── 정식 다중 자료 작업 ───────────────────────────────────────────────────

IngestJobStatus = Literal[
    "QUEUED", "EXTRACTING", "CLASSIFYING",
    "SUCCEEDED", "PARTIAL", "NO_RESULT", "FAILED",
]
IngestJobSourceStatus = Literal[
    "QUEUED", "EXTRACTING", "CLASSIFYING", "SUCCEEDED", "PARTIAL", "NO_RESULT", "FAILED",
]


class CreateIngestJobRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    source_ids: list[int] = Field(min_length=1, max_length=20)

    @field_validator("source_ids")
    @classmethod
    def unique_source_ids(cls, value: list[int]) -> list[int]:
        if any(source_id <= 0 for source_id in value):
            raise ValueError("source_id는 양수여야 합니다.")
        if len(value) != len(set(value)):
            raise ValueError("source_id를 중복해서 보낼 수 없습니다.")
        return value


class IngestJobAccepted(BaseModel):
    job_id: int
    status: IngestJobStatus
    category_version: int
    source_count: int


class IngestJobListItem(BaseModel):
    job_id: int
    title: str | None
    status: IngestJobStatus
    category_version: int
    source_count: int
    card_count: int
    created_at: str
    completed_at: str | None = None


class IngestJobList(BaseModel):
    items: list[IngestJobListItem]
    next_cursor: int | None = None
    total: int


class IngestJobCounts(BaseModel):
    sources: int
    succeeded: int
    failed: int
    # 자료는 끝났지만 구간 일부를 잃은 건수. DB 컬럼이 아니라 자료 목록에서 센다
    partial: int = 0
    cards: int


class IngestJobSource(BaseModel):
    source_id: int
    filename: str | None
    status: IngestJobSourceStatus
    card_count: int
    error: dict[str, str] | None = None


class IngestJobDetail(BaseModel):
    job_id: int
    title: str | None
    status: IngestJobStatus
    category_version: int
    counts: IngestJobCounts
    sources: list[IngestJobSource]
    review_destination: str


# ── 검수 (점주 승인) ───────────────────────────────────────────────────────

class ReviewFact(BaseModel):
    fact_id: int
    object_name: str
    attribute: str
    value: str
    confidence: float          # 0~100 (DB 저장값 그대로)


class ReviewCard(BaseModel):
    """점주 검수 화면 1행. confidence 는 DB 와 같은 0~100 이다."""
    card_id: int
    title: str
    content: str
    category_id: int | None = None
    category_name: str = ""
    source_id: int | None = None
    source_type: SourceType | None = None
    source_title: str | None = None
    confidence: float
    is_verified: bool
    needs_attention: bool      # 신뢰도가 D3 임계 미만 — 점주가 특히 봐야 할 카드
    created_at: str
    facts: list[ReviewFact] = []


class ReviewList(BaseModel):
    total: int                 # 필터에 걸린 전체 건수 (limit 이전)
    limit: int
    offset: int
    threshold: float           # D3 임계값을 0~100 으로 환산한 값
    cards: list[ReviewCard] = []


class ApproveResult(BaseModel):
    card_id: int
    is_verified: bool
    chunks: int = 0            # 임베딩된 청크 수. 승인 취소면 0
    error: str | None = None   # 일괄 승인에서 이 카드만 실패한 경우


class CardUpdateRequest(BaseModel):
    """점주가 고친 카드 글."""
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)


class BulkApproveRequest(BaseModel):
    card_ids: list[int] = Field(min_length=1, max_length=200)
