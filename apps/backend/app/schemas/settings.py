from pydantic import BaseModel


class PublicSettingsResponse(BaseModel):
    provider: str
    model: str
    personality: str
    chat_history_limit: int
    log_level: str
    api_key_configured: bool
    available_models: list[str]
    available_personalities: list[str]


class RuntimeSettingsPatch(BaseModel):
    model: str | None = None
    personality: str | None = None
