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


@router.get("/stats")
def llm_stats(request: Request, timeframe: str = "all") -> dict[str, object]:
    """Return rich token analytics, cost estimation and timeseries for dashboards."""
    collector: LLMTelemetryCollector = getattr(
        request.app.state,
        "llm_telemetry",
        llm_telemetry,
    )
    return collector.get_stats(timeframe=timeframe)


@router.get("/records")
def llm_records(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    purpose: str | None = None,
) -> dict[str, object]:
    """Return paginated raw request records for detailed inspection table."""
    collector: LLMTelemetryCollector = getattr(
        request.app.state,
        "llm_telemetry",
        llm_telemetry,
    )
    return collector.get_records(limit=limit, offset=offset, purpose=purpose)


@router.post("/reset")
def llm_reset(request: Request) -> dict[str, object]:
    """Reset all token telemetry statistics."""
    collector: LLMTelemetryCollector = getattr(
        request.app.state,
        "llm_telemetry",
        llm_telemetry,
    )
    collector.reset()
    return {"status": "ok", "message": "Telemetry records cleared"}
