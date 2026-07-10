from pydantic import BaseModel


class StatusResponse(BaseModel):
    app_name: str
    version: str
    backend: str
    llm_provider: str
    llm_model: str
    api_key_configured: bool
    database: str
