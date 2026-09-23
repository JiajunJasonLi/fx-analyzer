import logging
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_reference_config, get_session
from app.api.errors import install_error_handlers
from app.api.routers import fx, operations, policy_rates
from app.application.queries.operations import readiness
from app.config.reference import ReferenceConfiguration
from app.config.settings import Settings
from app.observability.logging import configure_logging
from app.observability.metrics import metrics


def create_app() -> FastAPI:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    application = FastAPI(title="FX Analyzer", version="0.1.0")
    install_error_handlers(application)

    @application.middleware("http")
    async def request_id(request: Request, call_next: object) -> JSONResponse:
        request.state.request_id = request.headers.get("X-Request-ID", str(uuid4()))[:128]
        started = time.perf_counter()
        try:
            response = await call_next(request)  # type: ignore[operator]
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            logging.getLogger("fx_analyzer.api").info(
                "request completed",
                extra={"event": "request_completed", "request_id": request.state.request_id,
                       "duration_seconds": round(time.perf_counter() - started, 6),
                       "outcome": "completed"},
            )

    @application.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready", tags=["health"])
    def ready(session: Session = Depends(get_session),
              config: ReferenceConfiguration = Depends(get_reference_config)) -> JSONResponse:
        result = readiness(session, config)
        return JSONResponse(result, status_code=200 if result["status"] == "ready" else 503)

    if settings.metrics_enabled:
        @application.get("/metrics", include_in_schema=False)
        def prometheus_metrics() -> PlainTextResponse:
            return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    application.include_router(fx.router)
    application.include_router(policy_rates.router)
    application.include_router(operations.router)

    return application


app = create_app()
