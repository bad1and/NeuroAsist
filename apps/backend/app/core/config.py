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
    log_level: str = "INFO"
    log_to_file: bool = False
    log_file_path: str = "logs/app.log"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
    voice_stt_provider: str = "faster_whisper"
    voice_stt_model: str = "small"
    voice_stt_device: str = "auto"
    voice_stt_compute_type: str = "int8"
    voice_default_language: str = "ru"
    voice_preload_stt_model: bool = True
    voice_preload_tts_model: bool = True
    voice_tts_enabled: bool = True
    voice_tts_provider: str = "silero"
    voice_silero_model: str = "v5_5_ru"
    voice_silero_speaker_ru: str = "xenia"
    voice_silero_sample_rate: int = 24000
    voice_silero_device: str = "cpu"
    voice_silero_cpu_threads: int = 4
    voice_silero_warmup: bool = True
    voice_silero_timeout_seconds: float = 10.0
    voice_tts_background_timeout_seconds: int = 20
    voice_tts_max_chars: int = 1200
    voice_audio_dir: str = "data/audio"
    voice_max_upload_mb: int = 25
    voice_max_record_seconds: int = 60
    voice_stt_timeout_seconds: int = 45
    voice_llm_timeout_seconds: int = 45
    voice_tts_timeout_seconds: int = 45
    voice_live_queue_size: int = 3
    voice_live_idle_flush_ms: int = 500
    voice_live_first_segment_chars: int = 40
    voice_live_next_segment_chars: int = 75
    voice_live_max_segment_chars: int = 110
    voice_live_max_segment_words: int = 18
    voice_live_safe_segment_words: int = 10
    voice_live_tts_retry_count: int = 0
    voice_live_tts_concurrency_mode: str = "1"
    voice_live_tts_concurrency_min: int = 1
    voice_live_tts_concurrency_max: int = 2
    voice_live_playback_prebuffer_segments: int = 2
    voice_live_playback_prebuffer_ms: int = 1000
    avatar_enabled: bool = False
    avatar_heartbeat_interval_seconds: float = 15.0
    avatar_client_timeout_seconds: float = 45.0

    @property
    def llm_api_key(self) -> str | None:
        return self.deepseek_api_key or self.legacy_api_key

    @property
    def database_path(self) -> Path:
        path = Path(self.sqlite_path)
        if path.is_absolute():
            return path
        return ROOT_DIR / path

    @property
    def voice_audio_path(self) -> Path:
        path = Path(self.voice_audio_dir)
        if path.is_absolute():
            return path
        return ROOT_DIR / path

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
