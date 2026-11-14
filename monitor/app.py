from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from monitor.api.routes import build_router
from monitor.cache import build_cache
from monitor.collector.scheduler import MonitorCollector
from monitor.collector.sources import MonitorSources
from monitor.config import load_settings
from monitor.ui.tier_presentation import build_tier_display


class RateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self.requests_per_minute = requests_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        async with self._lock:
            now = time.time()
            bucket = self._requests[key]
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
            if len(bucket) >= self.requests_per_minute:
                return False
            bucket.append(now)
            return True


settings = load_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("monitor")

_UI_DIR = Path(__file__).resolve().parent / "ui"


def _asset_revision() -> str:
    """Content-address static assets so browser caching cannot retain outdated Monitor JS."""
    digest = hashlib.sha256()
    for name in ("monitor.js", "monitor-tuning.js", "monitor-light.js", "monitor.css", "monitor-tuning.css"):
        path = _UI_DIR / "static" / name
        if path.exists():
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


asset_version = _asset_revision()
templates = Jinja2Templates(directory=str(_UI_DIR / "templates"))
cache = build_cache(settings, logger)
sources = MonitorSources(settings)
collector = MonitorCollector(settings, cache, sources, logger)
rate_limiter = RateLimiter(settings.rate_limit_rpm)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await collector.start()
    try:
        yield
    finally:
        await collector.stop()


app = FastAPI(
    title=settings.title,
    root_path=settings.root_path,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "ui" / "static")), name="static")
app.include_router(build_router(collector))


@app.middleware("http")
async def apply_rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        client_host = request.client.host if request.client else "unknown"
        if not await rate_limiter.allow(client_host):
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded"},
            )
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    template = templates.get_template("dashboard.html")
    # Render last verified tier counts into HTML before browser JS starts.
    # Uses only the collector's cached snapshot; never triggers a Core RPC.
    tier_display = build_tier_display(collector.get_public_summary_payload())
    html = template.render(
        request=request,
        title=settings.title,
        root_path=settings.root_path.rstrip("/"),
        asset_version=asset_version,
        tier_display=tier_display,
    )
    light_script = f'<script src="{settings.root_path.rstrip("/")}/static/monitor-light.js?v={asset_version}" defer></script>'
    html = html.replace("</body>", f"  {light_script}\n  </body>")
    return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})
