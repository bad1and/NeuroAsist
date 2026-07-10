from dataclasses import dataclass


@dataclass
class RuntimeSettings:
    model: str
    personality: str = "default"
    voice_language: str = "ru"
    voice_tts_voice: str | None = None
