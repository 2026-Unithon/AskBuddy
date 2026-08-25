"""준혁 (feat/input) — 멀티모달 전처리 · 추출 · 임베딩 적재.

계약 (개발가이드 6-1):
  1. 프론트가 Storage 에 직접 업로드
  2. POST /ingest/sources   → sources 행 생성 (UPLOADED)
  3. POST /ingest/process   → 처리 시작 (PROCESSING)
  4. GET  /ingest/status    → 2초 간격 폴링 (D6). DONE | FAILED 에서 멈춘다

파일 바이너리를 받지 않는다. Storage 경로 문자열만 받는다.
store_id 는 JWT 에서만 꺼낸다. 요청 본문의 매장 정보를 신뢰하지 않는다 (D1).
"""
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.deps import CurrentStoreId, CurrentUserId, Db
from app.ingest import pipeline
from app.ingest.preprocess import storage
from app.ingest import repository as repo
from app.ingest.embed import embed_card
from app.ingest.schemas import (
    CreateSourceRequest,
    KakaoMeta,
    ProcessRequest,
    ScanMeta,
    SourceCreated,
    StatusResponse,
    UploadUrlRequest,
    UploadUrlResponse,
    VideoMeta,
    VoiceMeta,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_EXPECTED_META = {
    "VOICE": VoiceMeta,
    "VIDEO": VideoMeta,
    "KAKAO": KakaoMeta,
    "SCAN": ScanMeta,
}


@router.post("/upload-url", response_model=UploadUrlResponse)
async def upload_url(
    req: UploadUrlRequest,
    store_id: CurrentStoreId,
) -> UploadUrlResponse:
    """1) 여기서 서명 URL 을 받고 2) 브라우저가 그 URL 로 파일을 PUT 한 뒤
    3) file_url 을 그대로 POST /ingest/sources 에 넘긴다.

    브라우저에 Supabase 키를 주지 않으면서도 파일 바이너리가 API 를 거치지 않는다.
    경로에 store_id 가 들어가므로 남의 매장 경로로는 발급되지 않는다.
    """
    try:
        object_path = storage.build_object_path(store_id, req.source_type, req.filename)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    try:
        signed = await storage.create_signed_upload_url(object_path)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e

    return UploadUrlResponse(upload_url=signed, file_url=object_path)


@router.post("/sources", response_model=SourceCreated, status_code=201)
async def create_source(
    req: CreateSourceRequest,
    db: Db,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
) -> SourceCreated:
    # 같은 파일 재업로드는 무시한다 (sources 의 (store_id, content_hash) unique)
    if req.content_hash:
        existing = await repo.find_by_hash(db, store_id, req.content_hash)
        if existing:
            logger.info("중복 업로드 무시 store=%s hash=%s -> source=%s",
                        store_id, req.content_hash[:12], existing["source_id"])
            return SourceCreated(source_id=existing["source_id"],
                                 status=existing["status"], duplicate=True)

    expected = _EXPECTED_META[req.source_type]
    if req.meta is not None and not isinstance(req.meta, expected):
        raise HTTPException(
            422, f"{req.source_type} 에는 {expected.__name__} 형태의 meta 가 필요하다"
        )
    if req.meta is None and req.source_type in ("VOICE", "VIDEO", "SCAN"):
        raise HTTPException(422, f"{req.source_type} 는 meta 가 필수다")

    async with db.transaction():
        source_id = await repo.create_source(
            db, store_id,
            uploaded_by=user_id,
            source_type=req.source_type,
            file_url=req.file_url,
            title=req.title,
            file_size=req.file_size,
            content_hash=req.content_hash,
        )
        await _create_sub_row(db, source_id, req)

    return SourceCreated(source_id=source_id, status="UPLOADED")


async def _create_sub_row(db, source_id: int, req: CreateSourceRequest) -> None:
    m = req.meta
    if isinstance(m, VoiceMeta):
        await repo.create_voice(db, source_id, audio_format=m.audio_format,
                                duration_sec=m.duration_sec,
                                record_method=m.record_method,
                                sample_rate=m.sample_rate)
    elif isinstance(m, VideoMeta):
        await repo.create_video(db, source_id, video_format=m.video_format,
                                duration_sec=m.duration_sec,
                                resolution=m.resolution, fps=m.fps)
    elif isinstance(m, KakaoMeta):
        await repo.create_kakao(db, source_id, import_type=m.import_type,
                                room_name=m.room_name)
    elif isinstance(m, ScanMeta):
        await repo.create_scan(db, source_id, doc_type=m.doc_type,
                               doc_category=m.doc_category, page_count=m.page_count)


@router.post("/process", response_model=StatusResponse)
async def process(
    req: ProcessRequest,
    background: BackgroundTasks,
    db: Db,
    store_id: CurrentStoreId,
) -> StatusResponse:
    src = await repo.get_source(db, store_id, req.source_id)
    if src is None:
        raise HTTPException(404, f"source {req.source_id} not found")

    if src["status"] == "PROCESSING":
        # 폴링 중 재호출. 새로 돌리지 않고 현재 상태를 그대로 돌려준다
        return await _status_of(db, store_id, req.source_id)
    if src["status"] == "DONE" and not req.force:
        return await _status_of(db, store_id, req.source_id)

    await repo.set_status(db, store_id, req.source_id, "PROCESSING")
    background.add_task(pipeline.process_source, store_id, req.source_id)

    return StatusResponse(source_id=req.source_id, status="PROCESSING")


@router.get("/status", response_model=StatusResponse)
async def status(
    db: Db,
    store_id: CurrentStoreId,
    source_id: int = Query(...),
) -> StatusResponse:
    """프론트는 2초 간격으로 이걸 친다. FAILED 분기를 반드시 화면에 표시할 것."""
    return await _status_of(db, store_id, source_id)


async def _status_of(db, store_id: int, source_id: int) -> StatusResponse:
    src = await repo.get_source(db, store_id, source_id)
    if src is None:
        raise HTTPException(404, f"source {source_id} not found")
    return StatusResponse(
        source_id=src["source_id"],
        status=src["status"],
        error_message=src["error_message"],
        processed_at=src["processed_at"].isoformat() if src["processed_at"] else None,
        card_count=await repo.count_cards(db, store_id, source_id),
    )


@router.post("/embed")
async def embed(
    db: Db,
    store_id: CurrentStoreId,
    card_id: int = Query(..., description="승인된 카드의 card_id"),
) -> dict:
    """점주 승인 직후 호출한다. 승인 전 카드는 거부한다.

    관호님 승인 플로우(/reg/*)에서 이 엔드포인트를 호출하면 된다.
    """
    try:
        chunks = await embed_card(db, store_id, card_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"card_id": card_id, "chunks": chunks}
