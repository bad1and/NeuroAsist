from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "NeuroAsist"
    deepseek_api_key: str | None = Field(default=None, validation_alias="DEEPSEEK_API_KEY")
    legacy_api_key: str | None = Field(default=None, validation_alias="API_KEY")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    sqlite_path: str = "data/neuroasist.sqlite3"
    chat_history_limit: int = 20

    @property
    def llm_api_key(self) -> str | None:
        return self.deepseek_api_key or self.legacy_api_key

    @property
    def database_path(self) -> Path:
        path = Path(self.sqlite_path)
        if path.is_absolute():
            return path
        return ROOT_DIR / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
