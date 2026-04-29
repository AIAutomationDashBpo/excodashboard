from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager

from app.db import init_pool
from app.config import settings
from app.routers import metrics, billing, insights, uptime, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield


app = FastAPI(
    title="Brainbase Operations Dashboard",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.environment == "development" else None,
    redoc_url=None,
)

app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# Routers
app.include_router(metrics.router)
app.include_router(billing.router)
app.include_router(insights.router)
app.include_router(uptime.router)
app.include_router(system.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/metrics")


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(
        "base.html",
        {"request": request, "error": "Page not found", "workers": [], "active_tab": ""},
        status_code=404,
    )
