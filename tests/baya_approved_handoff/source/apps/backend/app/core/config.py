from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Iris"
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
    conversation_diagnostics_enabled: bool = False
    context_max_tokens: int = 3000
    context_recent_turns: int = 8
    memory_enabled: bool = True
    memory_mode: str = "balanced"
    memory_sensitive_mode: str = "ask"
    memory_max_candidates_per_turn: int = 3
    memory_context_max_tokens: int = 900
    memory_llm_extraction_enabled: bool = False
    memory_llm_min_confidence: float = 0.70
    memory_async_extraction_enabled: bool = True
    memory_auto_min_confidence: float = 0.85
    memory_auto_min_importance: float = 0.60
    semantic_retrieval_enabled: bool = False
    semantic_retrieval_eval_passed: bool = False
    semantic_vector_backend: str = "sqlite"
    semantic_chroma_path: str | None = None
    semantic_embedding_provider: str = "hash"
    semantic_embedding_model_id: str = "hash-multilingual-v1"
    semantic_embedding_dimension: int = 256
    semantic_e5_model_path: str | None = None
    semantic_e5_revision: str | None = None
    semantic_retrieval_limit: int = 8
    log_level: str = "INFO"
    log_to_file: bool = False
    log_file_path: str = "logs/app.log"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://tauri.localhost,tauri://localhost"
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
    voice_stt_provider: str = "gigaam"
    voice_stt_model: str = "v3_rnnt"
    voice_stt_device: str = "cpu"
    voice_stt_compute_type: str = "int8"
    voice_torch_cpu_threads: int = 4
    voice_torch_interop_threads: int = 1
    voice_default_language: str = "ru"
    voice_preload_stt_model: bool = True
    voice_preload_tts_model: bool = True
    voice_tts_enabled: bool = True
    voice_tts_provider: str = "silero"
    voice_silero_model: str = "v5_5_ru"
    voice_silero_speaker_ru: str = "baya"
    voice_silero_sample_rate: int = 48000
    voice_silero_device: str = "cpu"
    voice_silero_cpu_threads: int = 4
    voice_silero_warmup: bool = True
    voice_silero_timeout_seconds: float = 10.0
    voice_silero_loudness_target_dbfs: float = -18.0
    voice_silero_peak_ceiling_dbfs: float = -1.0
    voice_silero_pronunciation_dictionary_path: str | None = None
    voice_silero_native_english: bool = False
    voice_silero_english_model: str = "v3_en"
    voice_silero_english_speaker: str = "en_0"
    voice_stress_enabled: bool = True
    voice_stress_cpu_threads: int = 1
    voice_tts_postprocessing_enabled: bool = True
    voice_tts_highpass_cutoff_hz: float = 60.0
    voice_tts_lowpass_cutoff_hz: float = 12000.0
    voice_tts_adaptive_prosody: bool = True
    voice_cmudict_enabled: bool = True
    voice_cmudict_cache_dir: str = ".cache/cmudict"
    voice_openvoice_enabled: bool = False
    voice_openvoice_reference_audio: str | None = None
    voice_openvoice_cache_dir: str = ".cache/openvoice-v2"
    voice_openvoice_repo_id: str = "myshell-ai/OpenVoiceV2"
    voice_openvoice_revision: str = "fd981100305a0e4291f93a9ad169c6d9f7bed54a"
    voice_openvoice_tau: float = 0.3
    voice_openvoice_cpu_threads: int = 8
    voice_tts_background_timeout_seconds: int = 120
    voice_tts_max_chars: int = 1200
    voice_audio_dir: str = "data/audio"
    voice_max_upload_mb: int = 25
    voice_max_record_seconds: int = 60
    voice_stt_timeout_seconds: int = 45
    voice_llm_timeout_seconds: int = 45
    voice_tts_timeout_seconds: int = 45
    voice_live_queue_size: int = 3
    voice_live_idle_flush_ms: int = 500
    voice_live_first_idle_flush_ms: int = 180
    voice_live_next_idle_flush_ms: int = 350
    voice_live_first_segment_chars: int = 32
    voice_live_next_segment_chars: int = 75
    voice_live_max_segment_chars: int = 110
    voice_live_max_segment_words: int = 18
    voice_live_safe_segment_words: int = 18
    voice_live_tts_retry_count: int = 0
    voice_live_tts_concurrency_mode: str = "1"
    voice_live_tts_concurrency_min: int = 1
    voice_live_tts_concurrency_max: int = 2
    voice_live_playback_prebuffer_segments: int = 1
    voice_live_playback_prebuffer_ms: int = 0
    voice_live_playback_start_lead_ms: int = 30
    voice_vad_provider: str = "silero"
    voice_silero_vad_model_path: str | None = None
    voice_vad_threshold: float = 0.55  # legacy alias retained for existing .env files
    voice_silero_vad_start_threshold: float = 0.55
    voice_silero_vad_end_threshold: float = 0.35
    voice_energy_vad_start_rms: float = 0.018
    voice_energy_vad_end_rms: float = 0.012
    voice_silero_vad_min_speech_ms: int = 64
    voice_energy_vad_min_speech_ms: int = 120
    voice_vad_pre_roll_ms: int = 900
    voice_vad_post_roll_ms: int = 180
    # These are deliberately more patient than a single word boundary. The
    # live turn detector decides whether a confirmed VAD boundary is semantic;
    # VAD itself must not split a natural thinking pause.
    voice_vad_end_silence_ms: int = 720
    voice_vad_live_end_silence_ms: int = 750
    voice_vad_live_fallback_end_silence_ms: int = 1100
    voice_stt_terms_path: str | None = None
    voice_input_diagnostic_audio: bool = False
    voice_input_diagnostic_dir: str | None = None
    avatar_enabled: bool = False
    avatar_emotion_mapping_path: str = "apps/protocol/avatar-emotion-mapping.json"
    avatar_heartbeat_interval_seconds: float = 15.0
    avatar_client_timeout_seconds: float = 45.0

    @field_validator("voice_tts_provider", mode="before")
    @classmethod
    def migrate_legacy_supertonic_provider(cls, value: object) -> str:
        if str(value or "").lower() == "supertonic":
            return "silero"
        return str(value or "silero").lower()

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
    def semantic_chroma_directory(self) -> Path:
        if self.semantic_chroma_path:
            return Path(self.semantic_chroma_path).expanduser()
        return self.database_path.parent / "chroma"

    @property
    def semantic_e5_model_directory(self) -> Path:
        if self.semantic_e5_model_path:
            return Path(self.semantic_e5_model_path).expanduser()
        return self.app_data_path / "models" / "multilingual-e5-small"

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
    def voice_stt_terms_file(self) -> Path:
        if self.voice_stt_terms_path:
            path = Path(self.voice_stt_terms_path).expanduser()
            return path if path.is_absolute() else ROOT_DIR / path
        return self.app_data_path / "stt-terms.json"

    @property
    def voice_input_diagnostic_path(self) -> Path:
        if self.voice_input_diagnostic_dir:
            path = Path(self.voice_input_diagnostic_dir).expanduser()
            return path if path.is_absolute() else ROOT_DIR / path
        return self.app_data_path / "diagnostics" / "stt-audio"

    @property
    def voice_openvoice_reference_audio_path(self) -> Path | None:
        if not self.voice_openvoice_reference_audio:
            return None
        path = Path(self.voice_openvoice_reference_audio).expanduser()
        return path if path.is_absolute() else ROOT_DIR / path

    @property
    def voice_silero_pronunciation_dictionary(self) -> Path:
        if self.voice_silero_pronunciation_dictionary_path:
            path = Path(self.voice_silero_pronunciation_dictionary_path).expanduser()
            return path if path.is_absolute() else ROOT_DIR / path
        return self.app_data_path / "tts-pronunciations.json"

    @property
    def voice_tts_default_voice(self) -> str:
        return self.voice_silero_speaker_ru

    @property
    def voice_openvoice_cache_path(self) -> Path:
        path = Path(self.voice_openvoice_cache_dir).expanduser()
        return path if path.is_absolute() else ROOT_DIR / path

    @property
    def voice_cmudict_cache_path(self) -> Path:
        path = Path(self.voice_cmudict_cache_dir).expanduser()
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
