"""
FastAPI application — serveur web du dashboard.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.core.events import EventBus
from src.portfolio.tracker import PortfolioTracker

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app(tracker: PortfolioTracker, event_bus: EventBus, pairs_ref: list) -> FastAPI:
    app = FastAPI(title="Polymarket Arb Bot", docs_url=None, redoc_url=None)

    # Mount static files
    STATIC_DIR.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Templates
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    # Store references in app state
    app.state.tracker = tracker
    app.state.event_bus = event_bus
    app.state.templates = templates
    app.state.pairs_ref = pairs_ref

    # Import and include routes
    from src.web.routes import router
    from src.web.sse import sse_router
    app.include_router(router)
    app.include_router(sse_router)

    return app
