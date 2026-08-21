from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.backend.app.api.routes.llm_diagnostics import router
from apps.backend.app.llm.telemetry import LLMTelemetryCollector


def test_llm_usage_endpoint_exposes_content_free_rolling_aggregates() -> None:
    collector = LLMTelemetryCollector(clock=lambda: 1_000.0)
    collector.record(
        timestamp=990.0,
        request_id="request-1",
        purpose="memory",
        model="deepseek-v4-flash",
        streaming=False,
        thinking=False,
        max_tokens=1_000,
        message_count=2,
        input_chars=2_000,
        usage_available=True,
        prompt=500,
        completion=40,
        total=540,
        reasoning=0,
        cache_hit=300,
        cache_miss=200,
        latency=1.25,
        finish_reason="stop",
    )
    app = FastAPI()
    app.state.llm_telemetry = collector
    app.include_router(router)

    body = TestClient(app).get("/debug/llm/usage").json()

    assert body["5m"]["overall"]["request_count"] == 1
    assert body["5m"]["overall"]["total"] == 540
    assert body["5m"]["per_purpose"]["memory"]["cache_hit"] == 300
    rendered = str(body).casefold()
    assert "content" not in rendered
    assert "messages" not in rendered
