from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[4]
APP_VERSION = (ROOT_DIR / "VERSION").read_text(encoding="utf-8").strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Iris"
    deepseek_api_key: str | None = Field(default=None, validation_alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    # Explicit output budgets for each LLM purpose. DeepSeek V4 supports very
    # large completions, so relying on the provider default makes a malformed
    # or runaway response unnecessarily expensive. Non-coding thinking is
    # disabled in the provider independently of these caps.
    llm_chat_json_max_tokens: int = Field(default=900, ge=64, le=16_384)
    llm_chat_live_max_tokens: int = Field(default=500, ge=64, le=16_384)
    llm_memory_max_tokens: int = Field(default=1_000, ge=64, le=16_384)
    llm_reflection_max_tokens: int = Field(default=300, ge=64, le=8_192)
    llm_adjudication_max_tokens: int = Field(default=350, ge=64, le=8_192)
    # Coding uses a separate profile and may opt into model reasoning. It still
    # needs a finite ceiling when the dedicated key falls back to the main key.
    llm_coding_max_tokens: int = Field(default=8_192, ge=256, le=65_536)
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
    # Optional second local model. It is lazy-loaded and called only for an
    # empty/low-confidence/low-SNR primary result.
    voice_stt_fallback_provider: str = ""
    voice_stt_fallback_model: str = ""
    voice_stt_fallback_confidence_threshold: float = 0.60
    voice_stt_fallback_min_rms: float = 0.008
    voice_stt_device: str = "cpu"
    voice_stt_compute_type: str = "int8"
    voice_torch_cpu_threads: int = 4
    voice_torch_interop_threads: int = 1
    voice_default_language: str = "ru"
    voice_preload_stt_model: bool = True
    voice_preload_tts_model: bool = True
    voice_tts_enabled: bool = True
    voice_tts_provider: str = "teratts"
    voice_teratts_model: str = "TeraSpace/TeraTTSv2"
    voice_teratts_revision: str = "f05ea799094571a3553904a555df3834fb0b963b"
    voice_teratts_model_path: str | None = None
    voice_teratts_cache_dir: str | None = None
    voice_teratts_voice: str = "ru_f1"
    voice_teratts_device: str = "cpu"
    voice_teratts_threads: int = 8
    voice_teratts_diffusion_model: str = "distilled"
    voice_teratts_ruaccent_mode: str = "full"
    voice_teratts_russian_stress: bool = True
    voice_teratts_chunk_frames: int = 16
    voice_teratts_seed: int = 1234
    voice_teratts_warmup: bool = True
    voice_teratts_timeout_seconds: float = 45.0
    voice_tts_pronunciation_dictionary_path: str | None = None
    voice_tts_postprocessing_enabled: bool = True
    voice_tts_loudness_target_dbfs: float = -18.0
    voice_tts_peak_ceiling_dbfs: float = -1.0
    voice_tts_highpass_cutoff_hz: float = 60.0
    voice_tts_adaptive_prosody: bool = True
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
    # Safe chunk boundaries still require whitespace/punctuation; these only
    # bound a stalled LLM delta gap before the first/next TTS job is released.
    voice_live_first_idle_flush_ms: int = 120
    voice_live_next_idle_flush_ms: int = 250
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
    # V1.0 Coding Agent. Runtime preferences (enabled/model/workspace profile)
    # live in RuntimeSettings; these values define the non-negotiable host-side
    # security boundary and are intentionally not editable from the WebView.
    # Feature availability can be disabled by an administrator; individual
    # desktop users still start with the agent switched off in RuntimeSettings.
    coding_agent_enabled: bool = True
    coding_api_key: str | None = Field(default=None, validation_alias="CODING_API_KEY")
    coding_base_url: str | None = None
    # A stable image name lets every project release use the same local coding
    # runtime. Operators may still override it when they maintain their own.
    coding_docker_image: str = "neuroasist-coding"
    # Optional operator-selected parent directory for task-private workspaces.
    # The portable default is a sibling of this checkout, never below it.
    coding_workspace_root: str | None = None
    coding_allowed_project_roots: str = ""
    coding_max_concurrent_tasks: int = 1
    coding_max_iterations: int = 48
    # A source checkout with documentation, protocol artefacts and frontend
    # code easily exceeds the original prototype cap (2,500 files / 40 MB).
    # These limits still exclude environments, dependencies, secrets and
    # generated directories through PathPolicy, while allowing NeuroAsist's
    # own approved source tree to be snapshotted in one task.
    coding_max_files: int = 10_000
    coding_max_total_bytes: int = 128_000_000
    coding_max_file_bytes: int = 500_000
    coding_max_output_bytes: int = 200_000
    coding_max_patch_bytes: int = 600_000
    coding_command_timeout_seconds: float = 180.0
    coding_llm_timeout_seconds: float = 180.0
    coding_memory_mb: int = 2048
    coding_cpus: float = 2.0
    coding_pids_limit: int = 128
    coding_workspace_retention_days: int = 14
    coding_allowed_extensions: str = (
        ".py,.pyi,.ts,.tsx,.js,.jsx,.json,.toml,.yaml,.yml,.md,.txt,.css,.html,.rs,.cs,.ini,.cfg"
    )

    @field_validator("voice_tts_provider", mode="before")
    @classmethod
    def migrate_legacy_tts_provider(cls, value: object) -> str:
        legacy = str(value or "").lower()
        if legacy in {"silero", "supertonic", "terattsv2", "tera"}:
            return "teratts"
        return legacy or "teratts"

    @property
    def llm_api_key(self) -> str | None:
        return self.deepseek_api_key

    @property
    def coding_llm_api_key(self) -> str | None:
        """Dedicated key when configured, otherwise the existing DeepSeek key."""
        return self.coding_api_key or self.llm_api_key

    @property
    def coding_llm_base_url(self) -> str:
        return self.coding_base_url or self.deepseek_base_url

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
    def coding_workspace_path(self) -> Path:
        """Task workspace parent, normally a sibling of the repository tree."""
        if self.coding_workspace_root:
            path = Path(self.coding_workspace_root).expanduser()
            return path if path.is_absolute() else (ROOT_DIR / path).resolve()
        return (ROOT_DIR.parent / "CodingAgentWorkspace").resolve()

    @property
    def coding_allowed_project_paths(self) -> tuple[Path, ...]:
        """Canonical source roots that may be snapshotted or receive a reviewed patch."""
        configured = [item.strip() for item in self.coding_allowed_project_roots.split(",") if item.strip()]
        roots = configured or [str(ROOT_DIR)]
        resolved: list[Path] = []
        for value in roots:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = ROOT_DIR / path
            try:
                candidate = path.resolve()
            except OSError:
                continue
            if candidate not in resolved:
                resolved.append(candidate)
        return tuple(resolved)

    @property
    def coding_allowed_extension_set(self) -> frozenset[str]:
        return frozenset(
            suffix.strip().casefold()
            for suffix in self.coding_allowed_extensions.split(",")
            if suffix.strip().startswith(".")
        )

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
    def voice_teratts_model_directory(self) -> Path | None:
        if not self.voice_teratts_model_path:
            return None
        path = Path(self.voice_teratts_model_path).expanduser()
        return path if path.is_absolute() else (ROOT_DIR / path).resolve()

    @property
    def voice_teratts_cache_path(self) -> Path:
        if self.voice_teratts_cache_dir:
            path = Path(self.voice_teratts_cache_dir).expanduser()
            return path if path.is_absolute() else (ROOT_DIR / path).resolve()
        return self.app_data_path / "models" / "huggingface"

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
    def voice_tts_default_voice(self) -> str:
        return self.voice_teratts_voice

    @property
    def voice_tts_pronunciation_dictionary(self) -> Path:
        if self.voice_tts_pronunciation_dictionary_path:
            path = Path(self.voice_tts_pronunciation_dictionary_path).expanduser()
            return path if path.is_absolute() else (ROOT_DIR / path).resolve()
        return self.app_data_path / "tts-pronunciations.json"

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
