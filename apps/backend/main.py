import logging

from fastapi import FastAPI

from apps.backend.app.api.routes.chat import router as chat_router
from apps.backend.app.core.config import get_settings
from apps.backend.app.core.logging import configure_logging
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    if not settings.llm_api_key:
        logger.warning("DeepSeek API key is not configured")

    app = FastAPI(title=settings.app_name, version="0.1.0")
    history = SQLiteMessageHistory(settings.database_path)

    @app.on_event("startup")
    def startup() -> None:
        try:
            history.init_db()
        except Exception:
            logger.critical("Storage initialization failed", exc_info=True)
            raise

        logger.info("Backend startup complete")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.state.settings = settings
    app.state.history = history
    app.include_router(chat_router)
    return app


app = create_app()
