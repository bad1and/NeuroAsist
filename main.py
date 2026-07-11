import copy
import logging

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from apps.backend.main import app


class ShutdownNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "KeyboardInterrupt" in message:
            return False
        if "asyncio.exceptions.CancelledError" in message and "lifespan" in message:
            return False
        return True


def _install_shutdown_noise_filter() -> None:
    for logger_name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(logger_name)
        if any(isinstance(log_filter, ShutdownNoiseFilter) for log_filter in logger.filters):
            continue
        logger.addFilter(ShutdownNoiseFilter())
        for handler in logger.handlers:
            handler.addFilter(ShutdownNoiseFilter())


def _uvicorn_log_config() -> dict:
    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["shutdown_noise"] = {
        "()": "main.ShutdownNoiseFilter",
    }
    for handler in config.get("handlers", {}).values():
        handler.setdefault("filters", []).append("shutdown_noise")
    return config


_install_shutdown_noise_filter()


if __name__ == "__main__":
    try:
        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=8000,
            reload=True,
            timeout_graceful_shutdown=1,
            log_config=_uvicorn_log_config(),
        )
    except KeyboardInterrupt:
        print("Backend stopped by Ctrl+C.")
