from fastapi import APIRouter, Request

from apps.backend.app.llm.telemetry import LLMTelemetryCollector, llm_telemetry


router = APIRouter(prefix="/debug/llm", tags=["debug"])


@router.get("/usage")
def llm_usage(request: Request) -> dict[str, object]:
    """Return content-free rolling LLM usage aggregates.

    The collector never receives prompt or response text. This endpoint is
    therefore safe for the local diagnostics UI while still exposing the
    request amplification, reasoning and cache metrics needed for cost work.
    """

    collector: LLMTelemetryCollector = getattr(
        request.app.state,
        "llm_telemetry",
        llm_telemetry,
    )
    return {
        window: {
            "overall": report.overall.to_dict(),
            "per_purpose": {
                purpose: aggregate.to_dict()
                for purpose, aggregate in report.per_purpose.items()
            },
        }
        for window, report in collector.report().items()
    }
