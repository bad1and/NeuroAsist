import logging
from pathlib import Path

from apps.backend.app.core.config import ROOT_DIR, Settings

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
MANAGED_HANDLER_ATTR = "_neuroasist_managed_handler"
SAFE_THIRD_PARTY_LOG_LEVELS = {
    "httpcore": logging.WARNING,
    "httpx": logging.WARNING,
    "openai": logging.WARNING,
    "watchfiles": logging.WARNING,
}


def configure_logging(settings: Settings) -> None:
    level = _parse_log_level(settings.log_level)
    formatter = logging.Formatter(LOG_FORMAT)
    root_logger = logging.getLogger()

    root_logger.setLevel(level)
    _remove_managed_handlers(root_logger)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    setattr(console_handler, MANAGED_HANDLER_ATTR, True)
    root_logger.addHandler(console_handler)

    if settings.log_to_file:
        log_file_path = _resolve_log_file_path(settings.log_file_path)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        setattr(file_handler, MANAGED_HANDLER_ATTR, True)
        root_logger.addHandler(file_handler)

    _configure_third_party_loggers()


def _parse_log_level(raw_level: str) -> int:
    level = logging.getLevelName(raw_level.upper())
    if isinstance(level, int):
        return level
    return logging.INFO


def _resolve_log_file_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def _remove_managed_handlers(root_logger: logging.Logger) -> None:
    for handler in list(root_logger.handlers):
        if getattr(handler, MANAGED_HANDLER_ATTR, False):
            root_logger.removeHandler(handler)
            handler.close()


def _configure_third_party_loggers() -> None:
    for logger_name, level in SAFE_THIRD_PARTY_LOG_LEVELS.items():
        logging.getLogger(logger_name).setLevel(level)
