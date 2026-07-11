import logging

from main import ShutdownNoiseFilter


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_shutdown_noise_filter_suppresses_keyboard_interrupt_traceback() -> None:
    log_filter = ShutdownNoiseFilter()

    assert log_filter.filter(_record("Traceback...\nKeyboardInterrupt")) is False


def test_shutdown_noise_filter_suppresses_lifespan_cancelled_error() -> None:
    log_filter = ShutdownNoiseFilter()

    assert (
        log_filter.filter(
            _record("Traceback...\nstarlette.routing.py in lifespan\nasyncio.exceptions.CancelledError")
        )
        is False
    )


def test_shutdown_noise_filter_keeps_regular_errors() -> None:
    log_filter = ShutdownNoiseFilter()

    assert log_filter.filter(_record("Exception in ASGI application")) is True
