from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.schemas.models import ManagedModelResponse, ManagedModelsResponse

router = APIRouter(prefix="/models", tags=["models"])


def _state(request: Request, model_id: str) -> ManagedModelResponse:
    try:
        return ManagedModelResponse(**request.app.state.model_manager.model_state(model_id))
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown model") from error


@router.get("", response_model=ManagedModelsResponse)
def get_models(request: Request) -> ManagedModelsResponse:
    return ManagedModelsResponse(directory=str(request.app.state.model_manager.root), models=[ManagedModelResponse(**item) for item in request.app.state.model_manager.states()])


@router.post("/{model_id}/install", response_model=ManagedModelResponse)
def install_model(model_id: str, request: Request) -> ManagedModelResponse:
    try:
        request.app.state.model_manager.install_async(model_id)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown model") from error
    return _state(request, model_id)


@router.delete("/{model_id}", response_model=ManagedModelResponse)
def remove_model(model_id: str, request: Request) -> ManagedModelResponse:
    if request.app.state.settings.desktop_auth_token:
        raise HTTPException(status_code=409, detail="Удаление модели выполняется Iris после остановки ядра.")
    try:
        return ManagedModelResponse(**request.app.state.model_manager.remove(model_id))
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown model") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{model_id}/cancel", response_model=ManagedModelResponse)
def cancel_model(model_id: str, request: Request) -> ManagedModelResponse:
    try:
        return ManagedModelResponse(**request.app.state.model_manager.cancel(model_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Unknown model") from error
