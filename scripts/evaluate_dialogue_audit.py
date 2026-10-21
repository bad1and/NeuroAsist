"""Isolated audit replay: real conversational model, fixed retrieval, temporary history.

Credentials arrive on stdin. The source history is opened read-only; only the
explicit output report is retained. No microphone or Unity renderer is used.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.dialogue_style import DialogueStyleService
from apps.backend.app.agents.character.persona import get_persona
from apps.backend.app.core.config import Settings
from apps.backend.app.environment.coordinator import SituationalCoordinator
from apps.backend.app.environment.news_service import NewsArticle, NewsDigestSnapshot
from apps.backend.app.environment.search_service import SearchService, SearchResult, SearchSnapshot
from apps.backend.app.llm.base import current_llm_call_purpose
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore, normalize_speech_words
from apps.backend.app.storage.timeline import TimelineHistoryAdapter, TimelineStore


class CountingProvider(DeepSeekProvider):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls = []

    async def generate(self, messages):
        self.calls.append(current_llm_call_purpose() or "generate")
        return await super().generate(messages)

    async def generate_structured(self, messages, **kwargs):
        self.calls.append(current_llm_call_purpose() or "structured")
        return await super().generate_structured(messages, **kwargs)

    async def generate_with_tools(self, messages, **kwargs):
        self.calls.append(current_llm_call_purpose() or "tools")
        return await super().generate_with_tools(messages, **kwargs)

    async def stream(self, messages):
        self.calls.append(current_llm_call_purpose() or "stream")
        async for delta in super().stream(messages):
            yield delta

    async def stream_with_tools(self, messages, **kwargs):
        self.calls.append(current_llm_call_purpose() or "stream_tools")
        async for delta in super().stream_with_tools(messages, **kwargs):
            yield delta


class FixedSearch(SearchService):
    def __init__(self):
        super().__init__()
        self.queries = []

    async def search(self, query, **kwargs):
        self.queries.append(query)
        budget = kwargs.get("budget")
        if budget is not None:
            budget.admit(query)
        health = bool(re.search(r"(?iu)диабет|инсулин|медов", query))
        text = ("Медовый месяц — временная фаза диабета первого типа после начала инсулинотерапии. "
                "В этот период оставшиеся бета-клетки ещё вырабатывают инсулин, и потребность в вводимом инсулине может уменьшаться. "
                "Это не отдельный тип диабета и не излечение."
                if health else "В ночь на 18 октября в Петербурге и области сообщалось об атаке дронов. "
                "В Янино отключилось электричество. В этой тестовой сводке не названы конкретные поражённые объекты и цель атаки.")
        source = SearchResult("Фаза медового месяца при диабете" if health else "Тестовая сводка о событии", text,
                              "https://diabetes.org/about-diabetes/type-1" if health else "https://example.com/fixture-event",
                              page_text=text, page_status="read", provider="fixture")
        return SearchSnapshot(query, (source,), provider="fixture", searched_at=datetime.now(UTC).isoformat())

    async def read_sources(self, query, sources, **kwargs):
        return await self.search(query, **kwargs)


class FixedNews:
    async def get_news(self, *args, **kwargs):
        date = datetime.now(UTC).isoformat()
        articles = (NewsArticle("Запущен научный спутник", "fixture", "Спутник начал научные наблюдения.", date, "science", "https://example.com/satellite"),
                    NewsArticle("Открылась выставка", "fixture", "Открылась выставка современного искусства.", date, "general", "https://example.com/exhibition"))
        return NewsDigestSnapshot("all", articles, 0, updated_at=date)


def last_dialogue(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        episode = connection.execute("SELECT episode_id FROM conversation_messages WHERE role='assistant' AND status='completed' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        rows = connection.execute("SELECT role, content FROM conversation_messages WHERE episode_id=? AND status='completed' ORDER BY created_at,sequence_no", (episode,)).fetchall()
    turns, pending, previous = [], [], []
    for role, text in rows:
        if role == "user":
            pending.append(text)
        elif role == "assistant":
            if pending:
                turns.append("\n".join(pending))
                previous.append(text)
                pending.clear()
    return turns, previous


def metrics(replies):
    counts = Counter()
    strong_replies = 0
    for reply in replies:
        words = re.findall(r"(?iu)\b(?:бля|блять|блядь|[её]б\w*|пизд\w*|за[её]б\w*|оху\w*|ниху\w*|ху[йеяё]\w*|хули|сука)\b", reply)
        strong_replies += bool(words)
        families = set()
        for word in words:
            word = word.casefold().replace("ё", "е")
            family = next((name for prefix, name in [("бля", "блять"), ("еб", "ебать"), ("пизд", "пиздец"), ("заеб", "заебись"), ("оху", "охуенно"), ("ниху", "нихуя"), ("хуй", "хуй"), ("хуе", "хуй"), ("хуя", "хуй")]
                           if word.startswith(prefix)), word)
            families.add(family)
        counts.update(families)
    return {"replies": len(replies), "with_blya": counts["блять"], "blya_ratio": round(counts["блять"] / max(1, len(replies)), 3),
            "with_strong_language": strong_replies, "strong_words_by_reply": dict(counts), "unique_strong_words": len(counts)}


async def evaluate(settings, source_history, output):
    turns, original = last_dialogue(source_history)
    corpus = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/character_voice_eval.json").read_text(encoding="utf-8"))
    provider = CountingProvider(settings)
    report = {"model": settings.deepseek_model, "persona_version": get_persona("default").persona_version, "fixture_retrieval": True, "production_history_changed": False,
              "microphone_tested": False, "unity_tested": False, "baseline": metrics(original), "series": []}
    with tempfile.TemporaryDirectory(prefix="iris-audit-replay-") as directory:
        root = Path(directory)
        runtime = RuntimeSettings(weather_enabled=False, location_mode="manual", speech_discouraged_words=["блять"])
        preferences = RuntimeSettingsStore(root / "settings.json")
        for name, inputs in [("last_dialogue", turns), ("street", corpus["street"])]:
            store = TimelineStore(root / f"{name}.db")
            store.init_db()
            search = FixedSearch()
            environment = SituationalCoordinator(search_service=search, news_service=FixedNews())
            series = {"name": name, "turns": []}
            report["series"].append(series)
            for index, text in enumerate(inputs, 1):
                agent = CharacterAgent(provider, TimelineHistoryAdapter(store), 20, runtime_settings=runtime,
                                       dialogue_style_service=DialogueStyleService(store, runtime, preferences), situational_coordinator=environment)
                before, query_count = len(provider.calls), len(search.queries)
                started = time.monotonic()
                result = "".join([part async for part in agent.stream_user_message(name, text, input_mode="voice")])
                reply = re.sub(r"\[\[.*?\]\]", "", result).strip()
                series["turns"].append({"user": text, "reply": reply, "calls": provider.calls[before:],
                                        "queries": search.queries[query_count:], "search": agent.last_web_search_metadata,
                                        "elapsed_ms": round((time.monotonic() - started) * 1000)})
                series["metrics"] = metrics([turn["reply"] for turn in series["turns"]])
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"series": name, "turn": index, "with_blya": series["metrics"]["with_blya"], "calls": len(provider.calls) - before}), flush=True)
            await search.close()
        report["word_frequency_target_passed"] = all(s["metrics"]["blya_ratio"] <= .25 for s in report["series"])
        report["preference_survived_reload"] = preferences.load(RuntimeSettings()).speech_discouraged_words == ["блять"]
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    credentials = json.load(sys.stdin)
    asyncio.run(evaluate(Settings(deepseek_api_key=credentials["deepseek_api_key"]), args.history, args.output))
