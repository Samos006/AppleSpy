from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import settings

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("api")

WEBAPP_DIR = Path(os.getenv("WEBAPP_DIR", "/srv/webapp"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("API стартует, мини-апп на %s", settings.webapp_url)
    if not WEBAPP_DIR.exists():
        log.warning(
            "каталог фронтенда %s не найден - соберите его (npm run build)",
            WEBAPP_DIR,
        )
    yield
    from app.db import engine

    await engine.dispose()

app = FastAPI(
    title="AppleSpy",
    description="Отслеживание цен и наличия товаров Золотого Яблока",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://web.telegram.org", settings.webapp_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

if WEBAPP_DIR.exists():
    assets = WEBAPP_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = WEBAPP_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEBAPP_DIR / "index.html")
