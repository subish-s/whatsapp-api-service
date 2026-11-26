from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.api.router import api_router
from app.api.websocket import ws_router
from app.config import settings
from app.core.rate_limiter import rate_limiter
from app.core.session_manager import session_manager
from app.database.connection import close_database_connection, connect_to_database

from app.utils.logger import logger

PUBLIC_ENDPOINTS = {"/health", "/ping"}


@asynccontextmanager
async def application_lifecycle(app: FastAPI):
    logger.info("Starting WhatsApp REST API Service", port=settings.server_port)
    await connect_to_database()
    await session_manager.bootstrap_sessions()
    yield
    logger.info("Stopping WhatsApp REST API Service")
    await session_manager.stop_all_sessions()
    await close_database_connection()


app = FastAPI(
    title="WhatsApp REST API",
    lifespan=application_lifecycle,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def verify_request_security(request: Request, call_next):
    if request.url.path in PUBLIC_ENDPOINTS:
        return await call_next(request)

    provided_key = request.headers.get("x-api-key") or request.query_params.get("x-api-key")
    if provided_key != settings.api_key:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized: Invalid API Key"})

    # Rate limiting by client key (API key + client IP)
    client_ip = request.client.host if request.client else "unknown"
    rate_limit_key = f"{provided_key}:{client_ip}"
    allowed, retry_after = await rate_limiter.is_allowed(rate_limit_key)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "detail": f"Too many requests. Rate limit exceeded ({settings.rate_limit_rpm} req/min).",
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    return await call_next(request)


@app.exception_handler(Exception)
async def handle_unexpected_errors(request: Request, exception: Exception):
    logger.error("Internal server error", path=request.url.path, error=str(exception))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(api_router, prefix="/api")
app.include_router(ws_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/ping")
async def ping_check():
    return "pong"


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        log_level="info",
    )
