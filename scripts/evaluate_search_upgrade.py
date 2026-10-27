"""Bounded real-model search decisions; credentials arrive only through stdin.

python -m scripts.evaluate_search_upgrade --output output/search-decisions.json
No production history, settings, search quota or databases are modified.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
import sys

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider, close_shared_clients


class History:
    def get_recent_messages(self, *args, **kwargs):
        return []


class Environment:
    search_service = object()  # Only advertise the schema; never execute it.


async def evaluate(api_key: str, output: Path):
    provider = DeepSeekProvider(Settings(deepseek_api_key=api_key))
    agent = CharacterAgent(provider, History(), 8, situational_coordinator=Environment())
    prompts = [
        ("Поищи, почему в Python 3.12 под Windows возникает ModuleNotFoundError при импорте requests.", []),
        ("Поищи, что сейчас нового с космическими телескопами.", []),
        ("Проверь новости о пострадавших после землетрясения в Турции за сегодня.", []),
        ("Найди свежие официальные сведения о следующем обновлении Minecraft Java.", []),
        ("А вчера что у них случилось? Проверь.", [ChatMessage(role="user", content="Обсуждаем дата-центры Яндекса и новости о них.")]),
    ]
    report = {"model": provider._model, "production_data_changed": False, "search_executed": False, "rows": []}
    reactions = []
    try:
        for question, context in prompts:
            recent = [ChatMessage(role="assistant", content=value + " Проверка завершена.") for value in reactions[-3:]]
            messages = [ChatMessage(role="system", content=agent._persona.identity + " " + agent._persona.speech_style
                + "\nТекущая дата: " + datetime.now().astimezone().isoformat()
                + "\n" + agent._skills.prompt(live=True, native=True)), *recent, *context,
                ChatMessage(role="user", content=question)]
            async with asyncio.timeout(35):
                response = await provider.generate_with_tools(messages, tools=agent._skills.tools())
            calls = response.tool_calls or []
            arguments = [json.loads(call["function"]["arguments"]) for call in calls]
            reaction = arguments[0].get("acknowledgement", "") if arguments else ""
            if reaction:
                reactions.append(reaction)
            report["rows"].append({"user": question, "calls": calls, "acknowledgement": reaction,
                "response_without_call": response.content[:1000] if not calls else "",
                "valid_acknowledgement": bool(agent._valid_bridge(reaction)), "usage": response.usage.model_dump() if hasattr(response.usage, "model_dump") else str(response.usage),
                "latency_ms": response.latency_ms})
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"case": len(report["rows"]), "tool_calls": len(calls), "acknowledgement": reaction}), flush=True)
        report["checks"] = {
            "all_decisions_are_searches": all(row["calls"] and all(c["function"]["name"] == "web_search" for c in row["calls"]) for row in report["rows"]),
            "reactions_are_valid": len(reactions) >= 3 and all(agent._valid_bridge(value) for value in reactions),
            "reactions_vary": len(set(reactions)) >= 3,
            "exact_error_preserved": bool(report["rows"][0]["calls"]) and "ModuleNotFoundError" in report["rows"][0]["calls"][0]["function"]["arguments"],
        }
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        await close_shared_clients()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    credentials = json.load(sys.stdin)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(evaluate(credentials["deepseek_api_key"], args.output))
    print(json.dumps(result["checks"], ensure_ascii=False))
