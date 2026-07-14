from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "NeuroAsist"
    deepseek_api_key: str | None = Field(default=None, validation_alias="DEEPSEEK_API_KEY")
    legacy_api_key: str | None = Field(default=None, validation_alias="API_KEY")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    sqlite_path: str = "data/neuroasist.sqlite3"
    app_data_dir: str | None = Field(default=None, validation_alias="NEUROASIST_APP_DATA_DIR")
    backup_retention_days: int = 30
    desktop_auth_token: str | None = Field(default=None, validation_alias="NEUROASIST_DESKTOP_TOKEN")
    chat_history_limit: int = 20
    timeline_v2_enabled: bool = True
    episodes_enabled: bool = True
    episode_soft_inactivity_minutes: int = 20
    episode_hard_inactivity_minutes: int = 60
    episode_maximum_messages: int = 120
    episode_maximum_estimated_tokens: int = 16000
    context_manager_enabled: bool = True
    context_max_tokens: int = 3000
    context_recent_turns: int = 8
    memory_enabled: bool = True
    memory_mode: str = "ask"
    memory_sensitive_mode: str = "ask"
    memory_max_candidates_per_turn: int = 3
    memory_context_max_tokens: int = 900
    semantic_retrieval_enabled: bool = False
    semantic_retrieval_eval_passed: bool = False
    semantic_embedding_provider: str = "hash"
    semantic_embedding_model_id: str = "hash-multilingual-v1"
    semantic_embedding_dimension: int = 256
    semantic_retrieval_limit: int = 8
    log_level: str = "INFO"
    log_to_file: bool = False
    log_file_path: str = "logs/app.log"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://tauri.localhost,tauri://localhost"
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
    voice_live_first_segment_chars: int = 32
    voice_live_next_segment_chars: int = 75
    voice_live_max_segment_chars: int = 110
    voice_live_max_segment_words: int = 18
    voice_live_safe_segment_words: int = 10
    voice_live_tts_retry_count: int = 0
    voice_live_tts_concurrency_mode: str = "1"
    voice_live_tts_concurrency_min: int = 1
    voice_live_tts_concurrency_max: int = 2
    voice_live_playback_prebuffer_segments: int = 1
    voice_live_playback_prebuffer_ms: int = 200
    voice_vad_provider: str = "silero"
    voice_silero_vad_model_path: str | None = None
    voice_vad_threshold: float = 0.55
    voice_vad_pre_roll_ms: int = 500
    avatar_enabled: bool = False
    avatar_emotion_mapping_path: str = "apps/protocol/avatar-emotion-mapping.json"
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
    def app_data_path(self) -> Path:
        """Per-user writable location used by the installed desktop application."""
        if self.app_data_dir:
            return Path(self.app_data_dir).expanduser()
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "NeuroAsist"
        return Path.home() / ".local" / "share" / "NeuroAsist"

    @property
    def avatar_emotion_mapping(self) -> Path:
        path = Path(self.avatar_emotion_mapping_path)
        return path if path.is_absolute() else ROOT_DIR / path

    @property
    def voice_silero_vad_model(self) -> Path | None:
        if not self.voice_silero_vad_model_path:
            return None
        path = Path(self.voice_silero_vad_model_path)
        return path if path.is_absolute() else ROOT_DIR / path

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
