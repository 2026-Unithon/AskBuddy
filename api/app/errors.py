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

from app.deps import get_claims


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


async def get_api_claims(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """기존 JWT 검증 결과를 신규 API 오류 형식으로 변환한다."""
    try:
        return await get_claims(authorization)
    except HTTPException as exc:
        missing = exc.detail == "missing bearer token"
        code = "AUTH_REQUIRED" if missing else "AUTH_INVALID"
        message = "로그인이 필요합니다." if missing else "로그인 정보가 올바르지 않습니다."
        raise ApiError(401, code, message) from exc


ApiClaims = Annotated[dict[str, Any], Depends(get_api_claims)]


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
                    "/categories",
                    "/reclassification-jobs",
                    "/ingest",
                    "/cards",
                    "/notifications",
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
