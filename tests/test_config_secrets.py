from __future__ import annotations

from pathlib import Path

from apps.backend.app.core.config import Settings


def test_api_keys_are_never_loaded_from_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY", "obsolete-generic-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-main-key")
    monkeypatch.setenv("CODING_API_KEY", "environment-coding-key")

    settings = Settings(_env_file=None)

    assert settings.llm_api_key is None
    assert settings.coding_llm_api_key is None


def test_api_keys_are_never_loaded_from_dotenv(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "DEEPSEEK_API_KEY=dotenv-main-key\nCODING_API_KEY=dotenv-coding-key\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=dotenv)

    assert settings.llm_api_key is None
    assert settings.coding_llm_api_key is None


def test_api_keys_are_never_loaded_from_pydantic_secret_files(tmp_path: Path) -> None:
    (tmp_path / "deepseek_api_key").write_text("file-main-key", encoding="utf-8")
    (tmp_path / "coding_api_key").write_text("file-coding-key", encoding="utf-8")

    settings = Settings(_env_file=None, _secrets_dir=tmp_path)

    assert settings.llm_api_key is None
    assert settings.coding_llm_api_key is None


def test_api_keys_must_be_supplied_explicitly_and_remain_separate() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key="main-key",
        coding_api_key="coding-key",
    )

    assert settings.llm_api_key == "main-key"
    assert settings.coding_llm_api_key == "coding-key"

    main_only = Settings(_env_file=None, deepseek_api_key="main-key")
    assert main_only.coding_llm_api_key is None
