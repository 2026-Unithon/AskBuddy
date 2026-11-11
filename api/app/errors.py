"""신규 API가 사용하는 일관된 오류 응답.

기존 엔드포인트의 응답 계약은 건드리지 않고, 새 코드가 ``ApiError``를
명시적으로 던진 경우에만 MVP v1 오류 envelope를 사용한다.
"""
from __future__ import annotations

from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.deps import Db, get_claims, raise_if_closed


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)


async def get_api_claims_open(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """기존 JWT 검증 결과를 신규 API 오류 형식으로 변환한다. 닫힌 매장을 막지 않는다(시작 화면·탈퇴 취소 전용)."""
    try:
        return await get_claims(authorization)
    except HTTPException as exc:
        missing = exc.detail == "missing bearer token"
        code = "AUTH_REQUIRED" if missing else "AUTH_INVALID"
        message = "로그인이 필요합니다." if missing else "로그인 정보가 올바르지 않습니다."
        raise ApiError(401, code, message) from exc


# store-isolation-ok: JWT 의 store_id 가 가리키는 매장이 열려 있는지만 본다(PK 한 줄)
async def check_store_open(claims: dict[str, Any], db: Any) -> None:
    """ApiClaims 를 쓰는 라우트(cards·ingest 등)는 get_store_id 를 거치지 않는다.
    탈퇴로 매장이 닫힌 뒤 남은 access token 으로 쓰지 못하게 여기서도 막는다(계획 8 Review Focus 1)."""
    store_id = claims.get("store_id")
    if store_id is None:
        return
    try:
        store_id = int(store_id)
    except (TypeError, ValueError):
        return  # 모양이 틀린 값은 각 라우트의 검사가 거절한다
    row = await db.fetchrow("select closing_at, deleted_at from stores where store_id = $1", store_id)
    if row is not None:
        raise_if_closed(role=claims.get("role"), closing_at=row["closing_at"], deleted_at=row["deleted_at"])


# store-isolation-ok: store_id 는 JWT 에서 오고, 그 매장이 열려 있는지만 확인하는 인증 경계다
async def get_api_claims(
    db: Db,
    claims: Annotated[dict[str, Any], Depends(get_api_claims_open)],
) -> dict[str, Any]:
    await check_store_open(claims, db)
    return claims


ApiClaims = Annotated[dict[str, Any], Depends(get_api_claims)]
# 닫힌 매장도 통과(시작 화면이 사장님을 탈퇴 취소 화면으로 보내야 한다)
OpenApiClaims = Annotated[dict[str, Any], Depends(get_api_claims_open)]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "request_id": request_id,
                    "details": exc.details,
                }
            },
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        new_api = (
            request.url.path == "/app/bootstrap"
            or request.url.path.startswith(
                (
                    # 계획 8 계정·설정
                    "/app/feedback",
                    "/app/me/leave-store",
                    "/app/me/withdraw",
                    "/auth",
                    "/members",
                    "/categories",
                    "/reclassification-jobs",
                    "/ingest",
                    "/cards",
                    "/notifications",
                    "/team",
                    "/checklist",
                    "/today-tasks",
                    "/report",
                )
            )
            or request.url.path.startswith("/learn/items/")
        )
        if not new_api:
            return await request_validation_exception_handler(request, exc)
        request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "요청 값을 확인해 주세요.",
                    "retryable": False,
                    "request_id": request_id,
                    "details": {"fields": jsonable_encoder(exc.errors())},
                }
            },
            headers={"X-Request-ID": request_id},
        )
