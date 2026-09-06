from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from apps.backend import desktop_entry
from apps.backend.app.core.config import configure_runtime_credentials, get_settings


def test_desktop_credentials_are_loaded_from_stdin_only(monkeypatch) -> None:
    monkeypatch.setenv("NEUROASIST_CREDENTIALS_STDIN", "1")
    monkeypatch.setattr(
        desktop_entry.sys,
        "stdin",
        SimpleNamespace(
            buffer=BytesIO(
                b'{"deepseek_api_key":"main-secret","coding_api_key":"coding-secret"}\n'
            )
        ),
    )

    try:
        desktop_entry.load_runtime_credentials()
        settings = get_settings()
        assert settings.llm_api_key == "main-secret"
        assert settings.coding_llm_api_key == "coding-secret"
    finally:
        configure_runtime_credentials(deepseek_api_key=None, coding_api_key=None)


def test_desktop_credentials_reject_non_string_values(monkeypatch) -> None:
    monkeypatch.setenv("NEUROASIST_CREDENTIALS_STDIN", "1")
    monkeypatch.setattr(
        desktop_entry.sys,
        "stdin",
        SimpleNamespace(buffer=BytesIO(b'{"deepseek_api_key":42}\n')),
    )

    with pytest.raises(RuntimeError, match="must be strings"):
        desktop_entry.load_runtime_credentials()
