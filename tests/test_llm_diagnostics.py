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
        model="deepseek-flash",
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


def test_llm_stats_and_records_endpoints(tmp_path) -> None:
    db_path = tmp_path / "test_telemetry.db"
    collector = LLMTelemetryCollector(clock=lambda: 1_000.0, db_path=db_path)
    collector.record(
        timestamp=990.0,
        request_id="request-1",
        purpose="chat_json",
        model="deepseek-flash",
        streaming=False,
        thinking=False,
        max_tokens=1_000,
        message_count=2,
        input_chars=2_000,
        usage_available=True,
        prompt=1_000,
        completion=200,
        total=1_200,
        reasoning=50,
        cache_hit=800,
        cache_miss=200,
        latency=1.5,
        finish_reason="stop",
    )
    app = FastAPI()
    app.state.llm_telemetry = collector
    app.include_router(router)
    client = TestClient(app)

    # Test /stats
    stats = client.get("/debug/llm/stats?timeframe=24h").json()
    assert stats["total_tokens"] == 1_200
    assert stats["prompt_tokens"] == 1_000
    assert stats["completion_tokens"] == 200
    assert stats["reasoning_tokens"] == 50
    assert stats["cache_hit_tokens"] == 800
    assert stats["cache_miss_tokens"] == 200
    assert stats["cache_hit_rate"] == 80.0
    assert stats["request_count"] == 1
    assert stats["estimated_cost_usd"] > 0
    assert "chat_json" in stats["by_purpose"]
    assert len(stats["timeseries"]) > 0

    # Test /records
    records = client.get("/debug/llm/records?limit=10").json()
    assert records["total"] == 1
    assert len(records["items"]) == 1
    item = records["items"][0]
    assert item["request_id"] == "request-1"
    assert item["prompt"] == 1_000
    assert item["completion"] == 200
    assert item["total"] == 1_200
    assert item["latency_ms"] == 1500.0

    # Test filtering by purpose (single & comma-separated)
    assert client.get("/debug/llm/records?purpose=chat_json").json()["total"] == 1
    assert client.get("/debug/llm/records?purpose=chat_json,memory").json()["total"] == 1
    assert client.get("/debug/llm/records?purpose=coding").json()["total"] == 0

    # Test persistence: reload collector from db
    new_collector = LLMTelemetryCollector(clock=lambda: 1_000.0, db_path=db_path)
    assert len(new_collector) == 1
    new_stats = new_collector.get_stats()
    assert new_stats["total_tokens"] == 1_200

    # Test /reset
    reset_resp = client.post("/debug/llm/reset").json()
    assert reset_resp["status"] == "ok"
    assert len(collector) == 0
    empty_records = client.get("/debug/llm/records").json()
    assert empty_records["total"] == 0

