"""FastAPI application entry point."""
from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import AsyncGenerator

import orjson
import redis.asyncio as aioredis
import sentry_sdk
import structlog
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.fastapi import FastApiIntegration
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings
from app.database import dispose_engine, init_db

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (shared across routers)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# Path to the built React SPA — populated by the Render build command:
#   cd frontend && npm install && npm run build
#   cp -r dist ../backend/frontend_dist
FRONTEND_DIST = Path(__file__).parent.parent / "frontend_dist"


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    # Structured logging setup
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}.get(
                settings.log_level, 20
            )
        ),
    )

    # Sentry
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[FastApiIntegration()],
            environment=settings.environment,
            traces_sample_rate=0.1,
        )
        log.info("sentry_initialised", dsn_set=True)

    # Database — create_all ensures ORM-defined tables exist
    await init_db()
    log.info("database_ready")

    # Seed / resync admin user on every startup.
    # ADMIN_PASSWORD (plain text) takes priority over ADMIN_PASSWORD_HASH.
    # Changing either env var + redeploy is enough to reset the password.
    _plain_pw = settings.admin_password
    _hash_pw = settings.admin_password_hash
    if _plain_pw or _hash_pw:
        import bcrypt as _bcrypt
        from sqlalchemy import select as sa_select

        from app.database import _get_session_factory
        from app.db_models import User

        if _plain_pw:
            target_hash = _bcrypt.hashpw(_plain_pw.encode(), _bcrypt.gensalt()).decode()
        else:
            target_hash = _hash_pw

        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                sa_select(User).where(User.username == settings.admin_username)
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                session.add(
                    User(
                        username=settings.admin_username,
                        hashed_password=target_hash,
                        is_active=True,
                        is_superuser=True,
                    )
                )
                await session.commit()
                log.info("admin_user_seeded", username=settings.admin_username)
            else:
                existing.hashed_password = target_hash
                existing.is_active = True
                existing.is_superuser = True
                await session.commit()
                log.info("admin_user_password_reset", username=settings.admin_username)

    # Redis
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = redis_client
    log.info("redis_ready", url=settings.redis_url)

    yield

    # Cleanup
    await redis_client.aclose()
    await dispose_engine()
    log.info("shutdown_complete")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Crypto ML Trading Platform",
        version="0.1.0",
        description="ML-driven crypto trading platform with risk governance",
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # Rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS — `allow_credentials=True` is incompatible with `allow_origins=["*"]`
    # per the CORS spec, so we disable credentials when the wildcard is used.
    origins = settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response

    # Routers
    from app.api.auth import router as auth_router
    from app.api.backtest import router as backtest_router
    from app.api.data import router as data_router
    from app.api.live import router as live_router
    from app.api.models_api import router as models_router
    from app.api.risk import router as risk_router
    from app.api.strategies import router as strategies_router

    app.include_router(auth_router,       prefix="/api/auth",       tags=["auth"])
    app.include_router(data_router,       prefix="/api/data",       tags=["data"])
    app.include_router(strategies_router, prefix="/api/strategies", tags=["strategies"])
    app.include_router(models_router,     prefix="/api/models",     tags=["models"])
    app.include_router(backtest_router,   prefix="/api/backtest",   tags=["backtest"])
    app.include_router(live_router,       prefix="/api/live",       tags=["live"])
    app.include_router(risk_router,       prefix="/api/risk",       tags=["risk"])

    # Health endpoints
    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "timestamp": time.time(), "environment": settings.environment}

    @app.get("/health/trader", tags=["health"])
    async def health_trader(request: Request):
        redis: aioredis.Redis = request.app.state.redis
        raw = await redis.get("trader:heartbeat")
        if raw is None:
            return JSONResponse(
                status_code=503,
                content={"status": "no_heartbeat", "message": "Trader has not started"},
            )
        data = orjson.loads(raw)
        age_s = time.time() - data.get("ts", 0)
        if age_s > 30:
            return JSONResponse(
                status_code=503,
                content={"status": "stale", "age_seconds": age_s, "data": data},
            )
        return {"status": "ok", "age_seconds": age_s, **data}

    # WebSocket fan-out: browser subscribes to a Redis pub/sub channel
    @app.websocket("/ws/{channel}")
    async def websocket_fanout(websocket: WebSocket, channel: str):
        allowed = {
            "trader:ticks", "trader:fills", "trader:logs",
            "trader:signals", "ui:events",
        }
        if channel not in allowed and not channel.startswith("jobs:"):
            await websocket.close(code=4003)
            return

        await websocket.accept()
        redis: aioredis.Redis = websocket.app.state.redis
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        log.info("ws_client_connected", channel=channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await websocket.send_text(message["data"])
        except WebSocketDisconnect:
            log.info("ws_client_disconnected", channel=channel)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    # ── Serve the React SPA (must come AFTER all API routes) ─────────────────
    if FRONTEND_DIST.exists():
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            # Vite outputs hashed JS/CSS bundles under assets/
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        # Catch-all: serve index.html for every path that isn't an API route,
        # letting React Router handle client-side navigation.
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):  # noqa: ARG001
            return FileResponse(str(FRONTEND_DIST / "index.html"))

    return app


app = create_app()
