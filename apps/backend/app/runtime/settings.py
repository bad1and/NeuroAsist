from dataclasses import dataclass


@dataclass
class RuntimeSettings:
    personality: str = "default"
    voice_language: str = "ru"
    voice_tts_voice: str | None = None
    voice_playback_rate: float = 1.0
    voice_live_playback_prebuffer_segments: int = 2
    voice_live_playback_prebuffer_ms: int = 1000
