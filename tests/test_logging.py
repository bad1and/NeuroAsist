import logging
from types import SimpleNamespace

from apps.backend.app.core.logging import MANAGED_HANDLER_ATTR, configure_logging


def test_configure_logging_does_not_duplicate_managed_handlers() -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    try:
        settings = SimpleNamespace(
            log_level="INFO",
            log_to_file=False,
            log_file_path="logs/app.log",
        )

        configure_logging(settings)
        configure_logging(settings)

        managed_handlers = [
            handler
            for handler in root_logger.handlers
            if getattr(handler, MANAGED_HANDLER_ATTR, False)
        ]
        assert len(managed_handlers) == 1
    finally:
        for handler in list(root_logger.handlers):
            if getattr(handler, MANAGED_HANDLER_ATTR, False):
                root_logger.removeHandler(handler)
                handler.close()
        for handler in original_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)
        root_logger.setLevel(original_level)


def test_configure_logging_sets_log_level() -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    try:
        settings = SimpleNamespace(
            log_level="DEBUG",
            log_to_file=False,
            log_file_path="logs/app.log",
        )

        configure_logging(settings)

        assert root_logger.level == logging.DEBUG
    finally:
        for handler in list(root_logger.handlers):
            if getattr(handler, MANAGED_HANDLER_ATTR, False):
                root_logger.removeHandler(handler)
                handler.close()
        for handler in original_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)
        root_logger.setLevel(original_level)


def test_configure_logging_keeps_openai_debug_logs_quiet() -> None:
    openai_logger = logging.getLogger("openai")
    original_level = openai_logger.level
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_root_level = root_logger.level

    try:
        settings = SimpleNamespace(
            log_level="DEBUG",
            log_to_file=False,
            log_file_path="logs/app.log",
        )

        configure_logging(settings)

        assert root_logger.level == logging.DEBUG
        assert openai_logger.level == logging.WARNING
    finally:
        for handler in list(root_logger.handlers):
            if getattr(handler, MANAGED_HANDLER_ATTR, False):
                root_logger.removeHandler(handler)
                handler.close()
        for handler in original_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)
        root_logger.setLevel(original_root_level)
        openai_logger.setLevel(original_level)
