from __future__ import annotations

from apps.backend.app.core.config import Settings


def test_only_explicit_llm_key_environment_variables_are_accepted(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY", "obsolete-generic-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("CODING_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.llm_api_key is None
    assert settings.coding_llm_api_key is None


def test_coding_key_remains_explicit_and_can_fall_back_to_deepseek(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "main-key")
    monkeypatch.setenv("CODING_API_KEY", "coding-key")

    settings = Settings(_env_file=None)

    assert settings.llm_api_key == "main-key"
    assert settings.coding_llm_api_key == "coding-key"
