from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.ingestion.scope_coordinator import ScopeConflictError
from app.application.queries.observations import QueryValidationError
from app.application.queries.operations import ResourceNotFoundError, ServiceUnavailableError


def error_response(request: Request, status: int, code: str, message: str,
                   details: dict[str, object] | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": message, "request_id": request_id, "details": details or {},
    }})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(QueryValidationError)
    async def query_validation(request: Request, exc: QueryValidationError) -> JSONResponse:
        return error_response(request, 422, exc.code, str(exc), {"field": exc.field} if exc.field else {})

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(request, 422, "REQUEST_VALIDATION_ERROR", "request validation failed", {"errors": exc.errors()})

    @app.exception_handler(ResourceNotFoundError)
    async def not_found(request: Request, exc: ResourceNotFoundError) -> JSONResponse:
        return error_response(request, 404, "NOT_FOUND", str(exc))

    @app.exception_handler(ScopeConflictError)
    async def conflict(request: Request, exc: ScopeConflictError) -> JSONResponse:
        return error_response(request, 409, "OVERLAPPING_INGESTION_SCOPE", str(exc))

    @app.exception_handler(ServiceUnavailableError)
    async def unavailable(request: Request, exc: ServiceUnavailableError) -> JSONResponse:
        return error_response(request, 503, "SERVICE_UNAVAILABLE", str(exc))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(request, 500, "INTERNAL_ERROR", "an unexpected error occurred")
