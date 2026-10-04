"""Isolated model replay with fixture evidence; never changes production history.

Run as a module with a JSON credential object on stdin (same in-memory pattern
as Core). --baseline-ref compares repository code without changing the checkout.
--tts measures first synthesized audio separately from first visible model text.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
import types
from datetime import UTC, datetime
from pathlib import Path

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.dialogue_style import DialogueStyleService
from apps.backend.app.core.config import Settings
from apps.backend.app.environment.search_service import SearchResult, SearchSnapshot
from apps.backend.app.llm.base import current_llm_call_purpose
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineHistoryAdapter, TimelineStore


class CountingProvider(DeepSeekProvider):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls = []

    async def generate(self, messages):
        self.calls.append(current_llm_call_purpose() or "chat_json")
        return await super().generate(messages)

    async def generate_structured(self, messages, **kwargs):
        self.calls.append(current_llm_call_purpose() or "structured")
        return await super().generate_structured(messages, **kwargs)

    async def stream(self, messages):
        self.calls.append(current_llm_call_purpose() or "chat_live")
        async for part in super().stream(messages):
            yield part


class FixtureEnvironment:
    """Retrieval is simulated; this experiment does not verify the news report."""
    def __init__(self):
        self.search_service = self
        self.queries = []

    async def search(self, query, **_kwargs):
        self.queries.append(query)
        return SearchSnapshot(query=query, status="ok", cached=True,
            searched_at=datetime.now(UTC).isoformat(),
            results=(SearchResult("Тестовая сводка", "В переданной сводке сообщается о 559 беспилотниках за ночь.",
                                  "https://example.com/fixture"),))

    async def get_ambient_header(self, **_kwargs):
        return ""

    async def evaluate_and_enrich(self, *_args, **_kwargs):
        return None


def baseline_classes(ref):
    names = ("persona", "prompts", "dialogue_pacing", "dialogue_style", "search_intent", "agent")
    aliases = {name: f"iris_replay_baseline_{name}" for name in names}
    modules = {}
    for name in names:
        path = f"apps/backend/app/agents/character/{name}.py"
        source = subprocess.run(["git", "show", f"{ref}:{path}"], check=True, capture_output=True, encoding="utf-8").stdout
        for dependency, alias in aliases.items():
            source = source.replace(f"apps.backend.app.agents.character.{dependency}", alias)
        module = types.ModuleType(aliases[name])
        sys.modules[module.__name__] = module
        exec(compile(source, path, "exec"), module.__dict__)
        modules[name] = module
    return modules["agent"].CharacterAgent, modules["dialogue_style"].DialogueStyleService


async def evaluate(settings, *, runs=2, baseline_ref=None, with_tts=False):
    provider = CountingProvider(settings)
    report = {"model": settings.deepseek_model, "fixture_news": True, "thinking_changed": False,
              "production_history_changed": False, "runs": [], "tts": {"requested": with_tts}}
    tts = None
    if with_tts:
        from apps.backend.app.voice.service import VoiceService
        from apps.backend.app.voice.providers import TTSRequest
        try:
            tts = VoiceService._build_tts_provider_by_name(settings.voice_tts_provider, settings)
            start = time.perf_counter()
            await tts.preload()
            report["tts"].update(provider=settings.voice_tts_provider, voice=settings.voice_teratts_voice,
                                 preload_ms=round((time.perf_counter() - start) * 1000))
        except Exception as exc:
            report["tts"]["unavailable"] = f"{type(exc).__name__}: {exc}"
            if tts is not None:
                await tts.close()
            tts = None
    versions = [("current", CharacterAgent, DialogueStyleService, runs)]
    if baseline_ref:
        agent_class, style_class = baseline_classes(baseline_ref)
        versions.insert(0, ("baseline", agent_class, style_class, 1))
    try:
        with tempfile.TemporaryDirectory(prefix="iris-dialogue-replay-") as directory:
            for label, agent_class, style_class, count in versions:
                for run in range(count):
                    store = TimelineStore(Path(directory) / f"{label}-{run}.sqlite3")
                    store.init_db()
                    environment = FixtureEnvironment()
                    for role, text in (("user", "найди информацию о дронах над Россией сегодня"),
                                       ("assistant", "По переданной сводке, за ночь сбили 559 беспилотников. Это, блядь, уже конвейер какой-то.")):
                        store.append_message(role=role, content=text, input_mode="text", session_id="replay",
                            metadata={"web_search": {"query": "дроны над Россией сегодня", "status": "ok"}} if role == "assistant" else None)
                    rows = []
                    for user_text in ("да", "пу пу пу", "но я и говорю что это пиздец какойто",
                                      "Объясни, чем отличается оперативная память от диска."):
                        agent = agent_class(provider, TimelineHistoryAdapter(store), 10,
                            dialogue_style_service=style_class(store), runtime_settings=RuntimeSettings(),
                            situational_coordinator=environment)
                        calls_before, searches_before = len(provider.calls), len(environment.queries)
                        start, first_text, first_answer, parts = time.perf_counter(), None, None, []
                        async for part in agent.stream_user_message("replay", user_text, input_mode="voice"):
                            parts.append(part)
                            visible = re.sub(r"\[\[.*?\]\]", "", part).strip()
                            if visible and first_text is None:
                                first_text = round((time.perf_counter() - start) * 1000)
                            if visible and visible != "Так, секунду, проверю." and first_answer is None:
                                first_answer = round((time.perf_counter() - start) * 1000)
                        reply = re.sub(r"\[\[.*?\]\]", "", "".join(parts)).strip()
                        row = {"user": user_text, "reply": reply, "first_text_ms": first_text,
                               "first_answer_ms": first_answer,
                               "completed_ms": round((time.perf_counter() - start) * 1000),
                               "calls": provider.calls[calls_before:], "lookups": len(environment.queries) - searches_before}
                        if tts is not None and len(rows) == 0:
                            speech = reply.removeprefix("Так, секунду, проверю. ").split(". ")[0]
                            row["tts_text"] = speech
                            started = time.perf_counter()
                            async for chunk in tts.stream(TTSRequest(text=speech, language="ru", voice=settings.voice_teratts_voice)):
                                if chunk.data and "first_synthesized_audio_ms" not in row:
                                    row["first_synthesized_audio_ms"] = round((time.perf_counter() - started) * 1000)
                        rows.append(row)
                        print(json.dumps({"implementation": label, "run": run + 1, **row}, ensure_ascii=False), flush=True)
                    report["runs"].append({"implementation": label, "run": run + 1, "turns": rows})
    finally:
        if tts is not None:
            await tts.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--tts", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    credentials = json.load(sys.stdin)
    result = asyncio.run(evaluate(Settings(deepseek_api_key=credentials.get("deepseek_api_key")),
                                  baseline_ref=args.baseline_ref, with_tts=args.tts))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
