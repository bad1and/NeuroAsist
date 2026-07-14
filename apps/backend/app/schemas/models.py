from pydantic import BaseModel


class ManagedModelResponse(BaseModel):
    id: str
    name: str
    version: str
    installed: bool
    size_bytes: int
    location: str | None = None
    sha256: str
    restart_required: bool
    status: str
    downloaded_bytes: int
    total_bytes: int
    error: str | None = None


class ManagedModelsResponse(BaseModel):
    models: list[ManagedModelResponse]
