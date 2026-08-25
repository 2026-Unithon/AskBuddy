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
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.config import get_settings
from app.deps import Claims, CurrentStoreId, CurrentUserId, Db
from app.ingest import pipeline
from app.ingest.preprocess import storage
from app.ingest import repository as repo
from app.ingest.embed import embed_card
from app.ingest.schemas import (
    CategoryOut,


    ApproveResult,
    BulkApproveRequest,
    CreateSourceRequest,
    KakaoMeta,
    ProcessRequest,
    ReviewCard,
    ReviewFact,
    ReviewList,
    ScanMeta,
    SourceCreated,
    StatusResponse,
    UpdateCategoriesRequest,
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


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(db: Db, store_id: CurrentStoreId) -> list[CategoryOut]:
    """점주가 켜둔 업무 카테고리. 추출기는 이 목록 안에서만 고른다."""
    rows = await repo.list_categories(db, store_id)
    return [CategoryOut(**dict(r)) for r in rows]


@router.patch("/categories", response_model=list[CategoryOut])
async def update_categories(
    req: UpdateCategoriesRequest,
    db: Db,
    store_id: CurrentStoreId,
) -> list[CategoryOut]:
    """"베이킹 안 해요" 같은 토글을 저장한다. 카테고리를 새로 만들지 않는다."""
    async with db.transaction():
        await repo.set_categories_enabled(
            db, store_id, {c.category_name: c.is_enabled for c in req.categories}
        )
        rows = await repo.list_categories(db, store_id)
    return [CategoryOut(**dict(r)) for r in rows]


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


# ── 검수 (점주 승인) ───────────────────────────────────────────────────────
#
# 추출된 카드는 항상 is_verified=false 로 쌓인다. 점주가 여기서 확인하고
# 승인해야 검색(match_cards)에 노출된다. 승인 즉시 임베딩까지 끝낸다.

async def require_owner(claims: Claims) -> int:
    """승인은 점주만. 신입(STAFF)은 미승인 카드를 보지도 못한다."""
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "카드 검수·승인은 점주만 할 수 있다")
    store_id = claims.get("store_id")
    if store_id is None:
        raise HTTPException(403, "token has no store_id")
    return int(store_id)


OwnerStoreId = Annotated[int, Depends(require_owner)]

_VERIFIED_FILTER: dict[str, bool | None] = {
    "pending": False,     # 기본값 — 점주가 아직 안 본 카드
    "approved": True,
    "all": None,
}


@router.get("/review", response_model=ReviewList)
async def review(
    db: Db,
    store_id: OwnerStoreId,
    status: Literal["pending", "approved", "all"] = "pending",
    source_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ReviewList:
    """점주 검수 목록. 기본은 미승인 카드만.

    needs_attention=true 는 신뢰도가 D3 임계 미만이라는 뜻이다. 프론트는
    이걸 배지로 띄우고, 점주가 근거(source)를 열어볼 수 있게 한다.
    """
    verified = _VERIFIED_FILTER[status]
    rows = await repo.list_review_cards(
        db, store_id, verified=verified, source_id=source_id,
        limit=limit, offset=offset,
    )
    facts = await repo.facts_for_cards(db, [r["card_id"] for r in rows])
    total = await repo.count_review_cards(
        db, store_id, verified=verified, source_id=source_id
    )

    # DB 는 0~100 으로 저장한다. 임계값도 같은 축으로 올려서 내려준다
    threshold = round(get_settings().confidence_threshold * 100, 2)

    return ReviewList(
        total=total, limit=limit, offset=offset, threshold=threshold,
        cards=[
            ReviewCard(
                card_id=r["card_id"],
                title=r["title"],
                content=r["content"],
                category_id=r["category_id"],
                category_name=r["category_name"],
                source_id=r["source_id"],
                source_type=r["source_type"],
                source_title=r["source_title"],
                confidence=float(r["confidence"]),
                is_verified=r["is_verified"],
                needs_attention=float(r["confidence"]) < threshold,
                created_at=r["created_at"].isoformat(),
                facts=[
                    ReviewFact(
                        fact_id=f["fact_id"],
                        object_name=f["object_name"],
                        attribute=f["attribute"],
                        value=f["value"],
                        confidence=float(f["confidence"]),
                    )
                    for f in facts.get(r["card_id"], [])
                ],
            )
            for r in rows
        ],
    )


async def _approve_one(db, store_id: int, card_id: int) -> ApproveResult:
    """승인과 임베딩을 한 트랜잭션에 묶는다.

    임베딩이 실패했는데 승인만 남으면 검색에 안 잡히는 유령 카드가 된다.
    그래서 실패하면 승인까지 되돌리고 점주에게 다시 누르게 한다.
    """
    async with db.transaction():
        if not await repo.set_card_verified(db, store_id, card_id, True):
            raise LookupError(f"card {card_id} not found in store {store_id}")
        chunks = await embed_card(db, store_id, card_id)
    logger.info("승인 card=%s store=%s chunks=%d", card_id, store_id, chunks)
    return ApproveResult(card_id=card_id, is_verified=True, chunks=chunks)


@router.post("/cards/{card_id}/approve", response_model=ApproveResult)
async def approve_card(card_id: int, db: Db, store_id: OwnerStoreId) -> ApproveResult:
    """점주가 '승인' 을 누른다. 이 순간부터 검색에 노출된다."""
    try:
        return await _approve_one(db, store_id, card_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        logger.exception("승인 실패 card=%s", card_id)
        raise HTTPException(502, f"승인은 됐으나 임베딩에 실패해 되돌렸다: {e}") from e


@router.post("/cards/{card_id}/unapprove", response_model=ApproveResult)
async def unapprove_card(card_id: int, db: Db, store_id: OwnerStoreId) -> ApproveResult:
    """승인 취소. 임베딩은 남기고 검색에서만 뺀다 (match_cards 가 승인분만 본다).

    다시 승인하면 임베딩을 새로 만들지 않고 그대로 살아난다.
    """
    if not await repo.set_card_verified(db, store_id, card_id, False):
        raise HTTPException(404, f"card {card_id} not found in store {store_id}")
    logger.info("승인 취소 card=%s store=%s", card_id, store_id)
    return ApproveResult(card_id=card_id, is_verified=False)


@router.post("/cards/approve", response_model=list[ApproveResult])
async def approve_cards(
    req: BulkApproveRequest, db: Db, store_id: OwnerStoreId
) -> list[ApproveResult]:
    """일괄 승인. 한 건이 실패해도 나머지는 진행하고 실패분만 error 로 돌려준다.

    자료 하나에서 카드가 열 장 넘게 나오므로 '이 자료 전부 승인' 이 필요하다.
    """
    results: list[ApproveResult] = []
    for card_id in req.card_ids:
        try:
            results.append(await _approve_one(db, store_id, card_id))
        except Exception as e:
            logger.warning("일괄 승인 중 실패 card=%s: %s", card_id, e)
            results.append(ApproveResult(
                card_id=card_id, is_verified=False, error=f"{type(e).__name__}: {e}"
            ))
    return results
