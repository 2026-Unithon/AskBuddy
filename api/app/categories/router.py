from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status

from app.categories import repository as repo
from app.categories.schemas import (
    CategoryItem,
    CategoryList,
    CategoryMutationResult,
    CreateCategoryRequest,
    DeleteCategoryResult,
    ReclassificationJob,
    ReclassificationSummary,
)
from app.categories.worker import process_reclassification_job
from app.deps import Db
from app.errors import ApiClaims, ApiError

router = APIRouter()
reclassification_router = APIRouter()


async def require_owner(claims: ApiClaims) -> dict[str, Any]:
    if claims.get("role") != "OWNER":
        raise ApiError(403, "OWNER_ONLY", "카테고리는 사장님만 변경할 수 있습니다.")
    return claims


OwnerClaims = Annotated[dict[str, Any], Depends(require_owner)]


def _identity(claims: dict[str, Any]) -> tuple[int, int]:
    user_id = claims.get("user_id")
    store_id = claims.get("store_id")
    if user_id is None or store_id is None:
        raise ApiError(403, "STORE_REQUIRED", "먼저 매장에 연결해 주세요.")
    return int(user_id), int(store_id)


def _category(row) -> CategoryItem:
    return CategoryItem(
        category_id=int(row["category_id"]),
        name=row["category_name"],
        is_system=bool(row["is_system"]),
        sort_order=int(row["sort_order"]),
    )


def _job(row) -> ReclassificationJob:
    error = None
    if row["error_code"]:
        error = {"code": row["error_code"], "message": row["error_message"] or ""}
    return ReclassificationJob(
        job_id=int(row["reclass_job_id"]),
        target_category_version=int(row["target_category_version"]),
        status=row["status"],
        total_count=int(row["total_count"]),
        applied_count=int(row["applied_count"]),
        skipped_count=int(row["skipped_count"]),
        failed_count=int(row["failed_count"]),
        error=error,
        started_at=row["started_at"].isoformat() if row["started_at"] else None,
        completed_at=row["completed_at"].isoformat() if row["completed_at"] else None,
    )


@router.get("", response_model=CategoryList)
async def list_categories(db: Db, claims: ApiClaims) -> CategoryList:
    _, store_id = _identity(claims)
    store = await db.fetchrow(
        "select category_version from stores where store_id = $1", store_id
    )
    if store is None:
        raise ApiError(404, "STORE_NOT_FOUND", "접근할 수 있는 매장이 없습니다.")
    rows = await repo.list_current(db, store_id)
    latest = await repo.latest_job(db, store_id)
    reclassification = (
        ReclassificationSummary(
            status=latest["status"], job_id=int(latest["reclass_job_id"])
        )
        if latest
        else None
    )
    return CategoryList(
        version=int(store["category_version"]),
        items=[_category(row) for row in rows],
        reclassification=reclassification,
    )


@router.post("", response_model=CategoryMutationResult, status_code=status.HTTP_201_CREATED)
async def add_category(
    req: CreateCategoryRequest,
    background: BackgroundTasks,
    db: Db,
    claims: OwnerClaims,
) -> CategoryMutationResult:
    user_id, store_id = _identity(claims)
    name = req.name
    if name == "기타":
        raise ApiError(409, "CATEGORY_ALREADY_EXISTS", "이미 존재하는 카테고리입니다.")

    async with db.transaction():
        store = await repo.get_store_for_update(db, store_id)
        if store is None:
            raise ApiError(404, "STORE_NOT_FOUND", "접근할 수 있는 매장이 없습니다.")
        version = int(store["category_version"]) + 1
        row = await repo.create_category(
            db, store_id, name=name, sort_order=req.sort_order, version=version
        )
        if row is None:
            raise ApiError(409, "CATEGORY_ALREADY_EXISTS", "이미 존재하는 카테고리입니다.")
        await repo.set_store_version(db, store_id, version)
        job_id = await repo.create_job(db, store_id, user_id, version)

    if job_id is not None:
        background.add_task(process_reclassification_job, store_id, job_id)
    return CategoryMutationResult(
        category=_category(row), version=version, reclass_job_id=job_id
    )


@router.delete("/{category_id}", response_model=DeleteCategoryResult)
async def delete_category(
    category_id: int,
    response: Response,
    background: BackgroundTasks,
    db: Db,
    claims: OwnerClaims,
) -> DeleteCategoryResult:
    user_id, store_id = _identity(claims)
    async with db.transaction():
        store = await repo.get_store_for_update(db, store_id)
        if store is None:
            raise ApiError(404, "STORE_NOT_FOUND", "접근할 수 있는 매장이 없습니다.")
        category = await repo.get_category_for_update(db, store_id, category_id)
        if category is None:
            raise ApiError(404, "CATEGORY_NOT_FOUND", "카테고리를 찾을 수 없습니다.")
        if category["is_system"]:
            raise ApiError(409, "SYSTEM_CATEGORY_IMMUTABLE", "기타 카테고리는 삭제할 수 없습니다.")

        version = int(store["category_version"]) + 1
        await repo.soft_delete_category(db, store_id, category_id, version=version)
        await repo.move_deleted_manual_cards_to_other(db, store_id, category_id, version)
        await repo.set_store_version(db, store_id, version)
        job_id = await repo.create_job(db, store_id, user_id, version)

    if job_id is not None:
        response.status_code = status.HTTP_202_ACCEPTED
        background.add_task(process_reclassification_job, store_id, job_id)
    return DeleteCategoryResult(
        category_id=category_id, version=version, reclass_job_id=job_id
    )


@reclassification_router.get("/{job_id}", response_model=ReclassificationJob)
async def get_reclassification_job(
    job_id: int,
    db: Db,
    claims: OwnerClaims,
) -> ReclassificationJob:
    _, store_id = _identity(claims)
    row = await repo.get_job(db, store_id, job_id)
    if row is None:
        raise ApiError(404, "RECLASSIFICATION_JOB_NOT_FOUND", "재분류 작업을 찾을 수 없습니다.")
    return _job(row)


@reclassification_router.post("/{job_id}/retry", response_model=ReclassificationJob)
async def retry_reclassification_job(
    job_id: int,
    background: BackgroundTasks,
    db: Db,
    claims: OwnerClaims,
) -> ReclassificationJob:
    user_id, store_id = _identity(claims)
    async with db.transaction():
        old = await repo.get_job(db, store_id, job_id)
        if old is None:
            raise ApiError(404, "RECLASSIFICATION_JOB_NOT_FOUND", "재분류 작업을 찾을 수 없습니다.")
        if old["status"] != "FAILED":
            raise ApiError(409, "RECLASSIFICATION_NOT_FAILED", "실패한 작업만 재시도할 수 있습니다.")
        store = await repo.get_store_for_update(db, store_id)
        version = int(store["category_version"])
        new_job_id = await repo.create_job(
            db, store_id, user_id, version, retry=True
        )
        if new_job_id is None:
            raise ApiError(409, "NO_CARDS_TO_RECLASSIFY", "재분류할 카드가 없습니다.")
        row = await repo.get_job(db, store_id, new_job_id)

    background.add_task(process_reclassification_job, store_id, new_job_id)
    return _job(row)
