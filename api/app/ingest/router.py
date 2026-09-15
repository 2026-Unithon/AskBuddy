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

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query

from app.categories import repository as category_repo
from app.categories.worker import process_reclassification_job
from app.config import get_settings
from app.deps import Claims, CurrentStoreId, CurrentUserId, Db
from app.ingest import pipeline
from app.ingest import job_repository as job_repo
from app.ingest.capabilities import get_capabilities
from app.ingest.job_worker import process_ingest_job
from app.ingest.preprocess import storage
from app.ingest import repository as repo
from app.ingest.embed import embed_card, prepare_embedding
from app.ingest.embed.service import card_usage_context
from app.ingest.schemas import (
    ApproveResult,
    BulkApproveRequest,
    CardUpdateRequest,
    CategoryOut,
    CreateSourceRequest,
    CreateIngestJobRequest,
    IngestJobAccepted,
    IngestJobCounts,
    IngestJobDetail,
    IngestJobList,
    IngestJobListItem,
    IngestJobSource,
    IngestJobStatus,
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
from app.errors import ApiClaims, ApiError

logger = logging.getLogger(__name__)
router = APIRouter()

_EXPECTED_META = {
    "VOICE": VoiceMeta,
    "VIDEO": VideoMeta,
    "KAKAO": KakaoMeta,
    "SCAN": ScanMeta,
}


def _job_identity(claims: dict, *, owner_only: bool = True) -> tuple[int, int]:
    if owner_only and claims.get("role") != "OWNER":
        raise ApiError(403, "OWNER_ONLY", "자료 작업은 사장님만 시작할 수 있습니다.")
    user_id = claims.get("user_id")
    store_id = claims.get("store_id")
    if user_id is None or store_id is None:
        raise ApiError(403, "STORE_REQUIRED", "먼저 매장에 연결해 주세요.")
    return int(user_id), int(store_id)


@router.get("/capabilities")
async def capabilities(claims: ApiClaims) -> dict:
    _job_identity(claims, owner_only=False)
    return get_capabilities()


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(db: Db, store_id: CurrentStoreId) -> list[CategoryOut]:
    """점주가 켜둔 업무 카테고리. 추출기는 이 목록 안에서만 고른다."""
    rows = await repo.list_categories(db, store_id)
    return [CategoryOut(**dict(r)) for r in rows]


@router.patch("/categories", response_model=list[CategoryOut])
async def update_categories(
    req: UpdateCategoriesRequest,
    background: BackgroundTasks,
    db: Db,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
    claims: Claims,
) -> list[CategoryOut]:
    """구 토글 계약을 새 카테고리 버전·재분류 흐름에 연결한다."""
    if claims.get("role") != "OWNER":
        raise ApiError(403, "OWNER_ONLY", "카테고리는 사장님만 변경할 수 있습니다.")

    job_id: int | None = None
    async with db.transaction():
        store = await category_repo.get_store_for_update(db, store_id)
        if store is None:
            raise ApiError(404, "STORE_NOT_FOUND", "접근할 수 있는 매장이 없습니다.")
        version = int(store["category_version"]) + 1
        changed = False
        for requested in req.categories:
            category = await category_repo.get_category_by_name_for_update(
                db, store_id, requested.category_name
            )
            if category is None:
                continue
            active = category["deleted_at"] is None and category["is_enabled"]
            if requested.is_enabled == active:
                continue
            if category["is_system"] and not requested.is_enabled:
                raise ApiError(
                    409,
                    "SYSTEM_CATEGORY_IMMUTABLE",
                    "기타 카테고리는 비활성화할 수 없습니다.",
                )
            if requested.is_enabled:
                await category_repo.create_category(
                    db,
                    store_id,
                    name=category["category_name"],
                    sort_order=int(category["sort_order"]),
                    version=version,
                )
            else:
                category_id = int(category["category_id"])
                await category_repo.soft_delete_category(
                    db, store_id, category_id, version=version
                )
                await category_repo.move_deleted_manual_cards_to_other(
                    db, store_id, category_id, version
                )
            changed = True

        if changed:
            await category_repo.set_store_version(db, store_id, version)
            job_id = await category_repo.create_job(db, store_id, user_id, version)
        rows = await repo.list_categories(db, store_id)

    if job_id is not None:
        background.add_task(process_reclassification_job, store_id, job_id)
    return [CategoryOut(**dict(r)) for r in rows]


@router.post("/upload-url", response_model=UploadUrlResponse)
async def upload_url(
    req: UploadUrlRequest,
    claims: ApiClaims,
) -> UploadUrlResponse:
    """1) 여기서 서명 URL 을 받고 2) 브라우저가 그 URL 로 파일을 PUT 한 뒤
    3) file_url 을 그대로 POST /ingest/sources 에 넘긴다.

    브라우저에 Supabase 키를 주지 않으면서도 파일 바이너리가 API 를 거치지 않는다.
    경로에 store_id 가 들어가므로 남의 매장 경로로는 발급되지 않는다.
    """
    _, store_id = _job_identity(claims)
    limits = get_capabilities()[req.source_type]
    if (
        req.file_size is not None
        and limits["max_bytes"] is not None
        and req.file_size > limits["max_bytes"]
    ):
        raise ApiError(413, "FILE_TOO_LARGE", "설정된 최대 파일 크기를 초과했습니다.")
    try:
        object_path = storage.build_object_path(store_id, req.source_type, req.filename)
    except ValueError as e:
        raise ApiError(415, "UNSUPPORTED_FILE_TYPE", str(e)) from e

    try:
        signed = await storage.create_signed_upload_url(object_path)
    except RuntimeError as e:
        raise ApiError(502, "UPLOAD_URL_FAILED", str(e), retryable=True) from e

    return UploadUrlResponse(upload_url=signed, file_url=object_path)


@router.post("/sources", response_model=SourceCreated, status_code=201)
async def create_source(
    req: CreateSourceRequest,
    db: Db,
    claims: ApiClaims,
) -> SourceCreated:
    user_id, store_id = _job_identity(claims)
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
        raise ApiError(
            422,
            "INVALID_SOURCE_META",
            f"{req.source_type}에는 {expected.__name__} 형태의 meta가 필요합니다.",
        )
    if req.meta is None and req.source_type in ("VOICE", "VIDEO", "SCAN"):
        raise ApiError(
            422,
            "SOURCE_META_REQUIRED",
            f"{req.source_type}에는 meta가 필요합니다.",
        )
    _validate_source_limits(req)

    async with db.transaction():
        source_id = await repo.create_source(
            db, store_id,
            uploaded_by=user_id,
            source_type=req.source_type,
            file_url=req.file_url,
            title=req.title,
            file_size=req.file_size,
            content_hash=req.content_hash,
            mime_type=req.mime_type,
            original_filename=req.original_filename,
        )
        await _create_sub_row(db, source_id, req)

    return SourceCreated(source_id=source_id, status="UPLOADED")


def _validate_source_limits(req: CreateSourceRequest) -> None:
    limits = get_capabilities()[req.source_type]
    if (
        req.file_size is not None
        and limits["max_bytes"] is not None
        and req.file_size > limits["max_bytes"]
    ):
        raise ApiError(413, "FILE_TOO_LARGE", "설정된 최대 파일 크기를 초과했습니다.")
    if isinstance(req.meta, (VoiceMeta, VideoMeta)):
        max_duration = limits["max_duration_sec"]
        if max_duration is not None and req.meta.duration_sec > max_duration:
            raise ApiError(413, "MEDIA_TOO_LONG", "설정된 최대 재생 시간을 초과했습니다.")
    if isinstance(req.meta, ScanMeta):
        max_pages = limits["max_pages"]
        if max_pages is not None and req.meta.page_count > max_pages:
            raise ApiError(413, "TOO_MANY_PAGES", "설정된 최대 페이지 수를 초과했습니다.")


def _accepted(row) -> IngestJobAccepted:
    return IngestJobAccepted(
        job_id=int(row["job_id"]),
        status=row["status"],
        category_version=int(row["category_version"]),
        source_count=int(row["total_source_count"]),
    )


@router.post("/jobs", response_model=IngestJobAccepted, status_code=202)
async def create_ingest_job(
    req: CreateIngestJobRequest,
    background: BackgroundTasks,
    db: Db,
    claims: ApiClaims,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IngestJobAccepted:
    user_id, store_id = _job_identity(claims)
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 200:
            raise ApiError(422, "INVALID_IDEMPOTENCY_KEY", "멱등 키를 확인해 주세요.")

    async with db.transaction():
        if idempotency_key:
            await db.execute(
                "select pg_advisory_xact_lock(hashtext($1))",
                f"askbuddy:ingest:{store_id}:{idempotency_key}",
            )
            existing = await job_repo.find_by_idempotency(
                db, store_id, idempotency_key
            )
            if existing is not None:
                if existing["status"] == "QUEUED":
                    background.add_task(
                        process_ingest_job, store_id, int(existing["job_id"])
                    )
                return _accepted(existing)

        sources = await job_repo.source_rows(db, store_id, req.source_ids)
        if len(sources) != len(req.source_ids):
            raise ApiError(404, "SOURCE_NOT_FOUND", "접근할 수 없는 자료가 포함되어 있습니다.")
        unavailable = [
            int(row["source_id"])
            for row in sources
            if row["status"] not in ("UPLOADED", "FAILED")
        ]
        if unavailable:
            raise ApiError(
                409,
                "SOURCE_NOT_READY",
                "이미 처리 중이거나 완료된 자료가 포함되어 있습니다.",
                details={"source_ids": unavailable},
            )
        category_version = await db.fetchval(
            "select category_version from stores where store_id = $1", store_id
        )
        if category_version is None:
            raise ApiError(404, "STORE_NOT_FOUND", "접근할 수 있는 매장이 없습니다.")
        row = await job_repo.create_job(
            db,
            store_id,
            user_id,
            title=req.title,
            source_ids=req.source_ids,
            category_version=int(category_version),
            prompt_version="extract-cards-v1",
            settings={"ingest_mode": get_settings().ingest_mode},
            idempotency_key=idempotency_key,
        )

    background.add_task(process_ingest_job, store_id, int(row["job_id"]))
    return _accepted(row)


@router.get("/jobs", response_model=IngestJobList)
async def list_ingest_jobs(
    db: Db,
    claims: ApiClaims,
    status_filter: IngestJobStatus | None = Query(default=None, alias="status"),
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> IngestJobList:
    _, store_id = _job_identity(claims)
    rows = await job_repo.list_jobs(
        db, store_id, job_status=status_filter, cursor=cursor, limit=limit + 1
    )
    total = await job_repo.count_jobs(db, store_id, status_filter)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return IngestJobList(
        items=[
            IngestJobListItem(
                job_id=int(row["job_id"]),
                title=row["title"],
                status=row["status"],
                category_version=int(row["category_version"]),
                source_count=int(row["total_source_count"]),
                card_count=int(row["card_count"]),
                created_at=row["created_at"].isoformat(),
                completed_at=(
                    row["completed_at"].isoformat() if row["completed_at"] else None
                ),
            )
            for row in rows
        ],
        next_cursor=int(rows[-1]["job_id"]) if has_more else None,
        total=total,
    )


async def _job_detail(db, store_id: int, job_id: int) -> IngestJobDetail:
    job = await job_repo.get_job(db, store_id, job_id)
    if job is None:
        raise ApiError(404, "INGEST_JOB_NOT_FOUND", "자료 작업을 찾을 수 없습니다.")
    sources = await job_repo.get_job_sources(db, store_id, job_id)
    return IngestJobDetail(
        job_id=int(job["job_id"]),
        title=job["title"],
        status=job["status"],
        category_version=int(job["category_version"]),
        counts=IngestJobCounts(
            sources=int(job["total_source_count"]),
            succeeded=int(job["success_source_count"]),
            failed=int(job["failed_source_count"]),
            cards=int(job["card_count"]),
        ),
        sources=[
            IngestJobSource(
                source_id=int(row["source_id"]),
                filename=row["filename"],
                status=row["status"],
                card_count=int(row["card_count"]),
                error=(
                    {"code": row["error_code"], "message": row["error_message"] or ""}
                    if row["error_code"]
                    else None
                ),
            )
            for row in sources
        ],
        review_destination=f"/owner/cards/review?job_id={job_id}",
    )


@router.get("/jobs/{job_id}", response_model=IngestJobDetail)
async def get_ingest_job(job_id: int, db: Db, claims: ApiClaims) -> IngestJobDetail:
    _, store_id = _job_identity(claims)
    return await _job_detail(db, store_id, job_id)


@router.post("/jobs/{job_id}/retry", response_model=IngestJobAccepted, status_code=202)
async def retry_ingest_job(
    job_id: int,
    background: BackgroundTasks,
    db: Db,
    claims: ApiClaims,
    include_no_result: bool = Query(default=False),
) -> IngestJobAccepted:
    _, store_id = _job_identity(claims)
    async with db.transaction():
        job = await job_repo.get_job(db, store_id, job_id)
        if job is None:
            raise ApiError(404, "INGEST_JOB_NOT_FOUND", "자료 작업을 찾을 수 없습니다.")
        retry_count = await job_repo.reset_retryable_sources(
            db, store_id, job_id, include_no_result=include_no_result
        )
        if retry_count == 0:
            raise ApiError(409, "NO_RETRYABLE_SOURCES", "재시도할 자료가 없습니다.")
        row = await job_repo.get_job(db, store_id, job_id)

    background.add_task(process_ingest_job, store_id, job_id)
    return IngestJobAccepted(
        job_id=job_id,
        status=row["status"],
        category_version=int(row["category_version"]),
        source_count=retry_count,
    )


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
        card = await repo.get_card(db, store_id, card_id)
        if card is None:
            raise LookupError("card not found")
        if not card["is_verified"]:
            raise ValueError("승인된 카드만 검색 대상이다")
        context = await card_usage_context(db, store_id, card_id)
        prepared = await prepare_embedding(store_id, card["title"], card["content"], cost_phase=context.cost_phase, context=context)
        async with db.transaction():
            current = await db.fetchrow(
                "select card_id, title, content, is_verified, draft_version_id, published_version_id, review_status from knowledge_cards "
                "where store_id=$1 and card_id=$2 for update",store_id,card_id)
            if current is None or dict(current) != dict(card):
                raise ValueError("임베딩 준비 중 카드 버전이 변경됐습니다")
            chunks = await embed_card(db, store_id, card_id, prepared=prepared)
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
    expected = await repo.get_card(db, store_id, card_id)
    if expected is None:
        raise LookupError("card not found")
    context = await card_usage_context(db, store_id, card_id)
    prepared = await prepare_embedding(store_id, expected["title"], expected["content"],
                                       cost_phase=context.cost_phase, context=context)
    async with db.transaction():
        current = await db.fetchrow(
            "select card_id, title, content, is_verified, draft_version_id, published_version_id, review_status from knowledge_cards "
            "where store_id = $1 and card_id = $2 for update", store_id, card_id)
        if current is None or dict(current) != dict(expected):
            raise ValueError("임베딩 준비 중 카드가 변경됐습니다")
        if not await repo.set_card_verified(db, store_id, card_id, True):
            raise LookupError(f"card {card_id} not found in store {store_id}")
        chunks = await embed_card(db, store_id, card_id, prepared=prepared)
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


@router.patch("/cards/{card_id}", response_model=ApproveResult)
async def update_card(
    card_id: int, req: CardUpdateRequest, db: Db, store_id: OwnerStoreId
) -> ApproveResult:
    """점주가 카드 글을 고친다.

    이미 승인된 카드라면 임베딩이 옛 글로 남아 있다. 그대로 두면 고친 내용이
    검색에 반영되지 않으므로 같은 트랜잭션에서 다시 만든다.
    """
    title = req.title.strip()
    content = req.content.strip()
    if not title or not content:
        raise HTTPException(422, "제목과 내용은 비울 수 없다")
    try:
        expected = await repo.get_card(db, store_id, card_id)
        if expected is None:
            raise LookupError("card not found")
        context = await card_usage_context(db, store_id, card_id) if expected["is_verified"] else None
        if context is not None:
            context = context.model_copy(update={"cost_phase": "OPERATING"})
        prepared = await prepare_embedding(store_id, title, content, cost_phase="OPERATING", context=context) if context else None
        async with db.transaction():
            current = await db.fetchrow(
                "select card_id, title, content, is_verified, draft_version_id, published_version_id, review_status from knowledge_cards "
                "where store_id = $1 and card_id = $2 for update", store_id, card_id)
            if current is None or dict(current) != dict(expected):
                raise HTTPException(409, "카드가 변경됐습니다. 다시 확인해 주세요.")
            if not await repo.update_card(db, store_id, card_id, title, content):
                raise LookupError(f"card {card_id} not found in store {store_id}")
            card = await repo.get_card(db, store_id, card_id)
            chunks = 0
            if card and card["is_verified"]:
                chunks = await embed_card(db, store_id, card_id, prepared=prepared)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("카드 수정 실패 card=%s", card_id)
        raise HTTPException(502, f"수정한 내용을 검색에 반영하지 못해 되돌렸다: {e}") from e
    logger.info("카드 수정 card=%s store=%s chunks=%d", card_id, store_id, chunks)
    return ApproveResult(
        card_id=card_id, is_verified=bool(card and card["is_verified"]), chunks=chunks
    )


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
