"""준혁 (feat/input) — /ingest/* 요청·응답 계약과 추출 결과 스키마.

추출 결과는 개발가이드 6-2 의 JSON 과 1:1 이다.
이 클래스가 곧 Gemini 의 response_schema 이므로, 필드를 바꾸면 프롬프트도 같이 바꾼다.
"""
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["VOICE", "VIDEO", "KAKAO", "SCAN"]
SourceStatus = Literal["UPLOADED", "PROCESSING", "DONE", "FAILED"]


# ── 추출 결과 (Gemini response_schema) ─────────────────────────────────────

class ExtractedFact(BaseModel):
    object_name: str
    attribute: str
    value: str
    confidence: float = Field(ge=0, le=1)


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


class UploadUrlResponse(BaseModel):
    upload_url: str      # 브라우저가 이 주소로 PUT 한다
    file_url: str        # 업로드 후 /ingest/sources 에 그대로 넘길 값


class CreateSourceRequest(BaseModel):
    """프론트가 Storage 에 올린 뒤 호출한다. 파일 바이너리를 보내지 않는다."""
    source_type: SourceType
    file_url: str = Field(max_length=500)   # Storage 경로 또는 서명 URL
    title: str | None = Field(default=None, max_length=200)
    file_size: int | None = None
    content_hash: str | None = Field(default=None, max_length=64)
    meta: VoiceMeta | VideoMeta | KakaoMeta | ScanMeta | None = None


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
