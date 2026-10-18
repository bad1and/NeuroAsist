"""Synthetic memory smoke against the configured provider, in temporary DBs.

Supply {"deepseek_api_key":"..."} on stdin. Credentials and real user history
are never included in the report. --compare-head compares the extractor in
Git HEAD using the SAME current storage/policy, not an old application build.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import LLMProvider
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider, close_shared_clients
from apps.backend.app.memory.extraction_worker import MemoryExtractionWorker
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore


CASES = [
    {
        "id": "everyday",
        "text": "По вторникам и четвергам в 19:00 хожу в бассейн. Моя сестра Аня живёт в Туле. Для работы использую ноутбук ThinkPad T14.",
        "expected": [("user.schedule", ["втор", "четвер", "19:00"]), ("user.family", ["Аня", "Тул"]), ("user.device", ["ThinkPad", "T14"])],
    },
    {
        "id": "parallel-learning",
        "text": "Изучаю Rust для системного программирования. Ещё учу испанский, потому что хочу читать книги в оригинале.",
        "expected": [("user.learning", ["Rust"]), ("user.learning", ["испанск"])],
    },
    {
        "id": "habit-and-event",
        "text": "Каждый вечер перед сном читаю бумажные книги, с телефона читать не люблю. Вчера наконец получил водительские права.",
        "expected": [("user.habit", ["перед сном", "книг"]), ("user.life_event", ["водительск", "прав"])],
        "relative_event_days": -1,
    },
    {
        "id": "sensitive-consent",
        "text": "Запомни: у меня аллергия на арахис, поэтому я всегда проверяю состав сладостей.",
        "expected": [("user.health_constraint", ["арахис"])],
    },
    {
        "id": "fiction-not-biography",
        "text": "Представь персонажа для рассказа: он говорит «у меня кот Барсик, я работаю капитаном». Это выдумка, ко мне не относится.",
        "expected": [],
    },
    {
        "id": "short-location-answer",
        "context": [("assistant", "Где ты живёшь?")],
        "text": "В Туле",
        "expected": [("user.location", ["Тул"])],
    },
    {
        "id": "short-age-answer",
        "context": [("assistant", "Сколько тебе лет?")],
        "text": "Двадцать пять",
        "expected": [("user.age", ["25"])],
    },
    {
        "id": "targeted-schedule-correction",
        "seed": {"text": "По вторникам хожу в бассейн", "predicate": "schedule", "value": "Бассейн по вторникам"},
        "text": "Нет, исправь расписание: бассейн теперь по средам, а не по вторникам.",
        "expected": [("user.schedule", ["сред"])],
        "expected_slot_counts": {"user.schedule": 1},
    },
]


class MeasuredProvider(LLMProvider):
    def __init__(self, provider):
        self.provider = provider
        self.calls = []

    async def generate(self, messages):
        response = await self.provider.generate_structured(messages, temperature=0)
        self.calls.append({
            "request_chars": sum(len(item.content) for item in messages),
            "usage": response.usage.model_dump() if response.usage else None,
            "finish_reason": response.finish_reason,
        })
        return response


def baseline_worker():
    source = subprocess.check_output(
        ["git", "show", "HEAD:apps/backend/app/memory/extraction_worker.py"], cwd=ROOT,
    ).decode("utf-8")
    module = types.ModuleType("memory_extractor_baseline")
    sys.modules[module.__name__] = module
    exec(compile(source, "<git-head-memory-extractor>", "exec"), module.__dict__)
    return module.MemoryExtractionWorker


async def evaluate(api_key, compare):
    settings = Settings(deepseek_api_key=api_key)
    provider = DeepSeekProvider(settings, purpose="memory")
    variants = [("current", MemoryExtractionWorker)]
    if compare:
        variants.insert(0, ("head_extractor_current_policy", baseline_worker()))
    report = {"model": settings.deepseek_model, "variants": {}}
    try:
        with tempfile.TemporaryDirectory(prefix="iris-memory-live-") as directory:
            for variant, worker_type in variants:
                results = []
                for case in CASES:
                    store = TimelineStore(Path(directory) / f"{variant}-{case['id']}.sqlite3")
                    store.init_db()
                    service = MemoryService(store, RuntimeSettings(memory_mode="balanced"), llm_extraction_enabled=True)
                    if seed := case.get("seed"):
                        seed_source, _ = store.append_message(role="user", content=seed["text"], input_mode="text")
                        service.apply_llm_candidates([{
                            "kind": "preference", "predicate": seed["predicate"],
                            "value_text": seed["value"], "confidence": .96, "importance": .7,
                        }], seed_source)
                    for role, content in case.get("context", []):
                        store.append_message(role=role, content=content, input_mode="text")
                    source, _ = store.append_message(role="user", content=case["text"], input_mode="text")
                    queued = service.schedule_extraction(source)
                    measured = MeasuredProvider(provider)
                    if queued:
                        await worker_type(store, service, measured).run_once()
                    facts = [{"slot": row["slot_key"], "value": row["value_text"]} for row in store.list_memories(status="active")]
                    matched = [any(
                        row["slot"] == slot and all(term.casefold() in row["value"].casefold() for term in terms)
                        for row in facts
                    ) for slot, terms in case["expected"]]
                    passed = all(matched) if matched else not facts
                    for slot, count in case.get("expected_slot_counts", {}).items():
                        passed = passed and sum(row["slot"] == slot for row in facts) == count
                    expected_date = None
                    if "relative_event_days" in case:
                        expected_date = (datetime.fromisoformat(source.created_at).astimezone() + timedelta(days=case["relative_event_days"])).date().isoformat()
                        passed = passed and any(row["slot"] == "user.life_event" and expected_date in row["value"] for row in facts)
                    runs = store.memory_diagnostics()["runs"]
                    diagnostics = [{"result": run["result"], "diagnostics": run["diagnostics"]} for run in runs]
                    results.append({"id": case["id"], "passed": passed, "matched": matched, "expected_event_date": expected_date, "facts": facts, "calls": measured.calls, "jobs": diagnostics})
                    print(f"{variant}/{case['id']}: {'PASS' if passed else 'FAIL'}", flush=True)
                report["variants"][variant] = results
    finally:
        await close_shared_clients()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare-head", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    credentials = json.loads(sys.stdin.readline())
    api_key = credentials.get("deepseek_api_key")
    if not isinstance(api_key, str) or not api_key:
        raise SystemExit("A provider credential is required on stdin")
    report = asyncio.run(evaluate(api_key, args.compare_head))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(item["passed"] for item in report["variants"]["current"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
