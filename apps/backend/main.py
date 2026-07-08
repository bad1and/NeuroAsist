import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.backend.app.api.routes.chat import router as chat_router
from apps.backend.app.api.routes.events import router as events_router
from apps.backend.app.api.routes.settings import router as settings_router
from apps.backend.app.api.routes.status import router as status_router
from apps.backend.app.api.websocket import router as websocket_router
from apps.backend.app.core.config import get_settings
from apps.backend.app.core.logging import configure_logging
from apps.backend.app.events.bus import EventBus
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    if not settings.llm_api_key:
        logger.warning("DeepSeek API key is not configured")

    app = FastAPI(title=settings.app_name, version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    history = SQLiteMessageHistory(settings.database_path)
    event_bus = EventBus(max_events=300)
    runtime_settings = RuntimeSettings(model=settings.deepseek_model)

    @app.on_event("startup")
    def startup() -> None:
        try:
            history.init_db()
        except Exception:
            logger.critical("Storage initialization failed", exc_info=True)
            event_bus.publish(
                "backend.status",
                "critical",
                "Storage initialization failed",
                {},
            )
            raise

        event_bus.publish(
            "backend.status",
            "info",
            "Backend startup complete",
            {"version": app.version},
        )
        logger.info("Backend startup complete")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.state.settings = settings
    app.state.history = history
    app.state.event_bus = event_bus
    app.state.runtime_settings = runtime_settings
    app.include_router(chat_router)
    app.include_router(events_router)
    app.include_router(settings_router)
    app.include_router(status_router)
    app.include_router(websocket_router)
    return app


app = create_app()
