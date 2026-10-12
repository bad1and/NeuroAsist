import logging
import re
from logging.handlers import RotatingFileHandler
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


class SecretRedaction(logging.Filter):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.secrets = tuple(value for name in ("llm_api_key", "coding_llm_api_key", "desktop_auth_token", "brave_api_key", "tavily_api_key", "serper_api_key")
                             if (value := getattr(settings, name, None)))

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = self.redact(record.getMessage()), ()
        if record.exc_info:
            record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info))
        return True

    def redact(self, text: str) -> str:
        text = re.sub(r"(?i)([?&](?:token|api_key|apikey)=)[^&\s]+", r"\1[redacted]", text)
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        return text


def configure_logging(settings: Settings) -> None:
    level = _parse_log_level(settings.log_level)
    formatter = logging.Formatter(LOG_FORMAT)
    root_logger = logging.getLogger()

    root_logger.setLevel(level)
    _remove_managed_handlers(root_logger)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SecretRedaction(settings))
    setattr(console_handler, MANAGED_HANDLER_ATTR, True)
    root_logger.addHandler(console_handler)

    if settings.log_to_file:
        log_file_path = _resolve_log_file_path(settings.log_file_path)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_file_path, maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SecretRedaction(settings))
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
