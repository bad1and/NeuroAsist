"""Small synthetic dialogue with real LLM and an isolated viewpoint database.

Credentials are accepted as JSON on stdin, never stored in reports/arguments.
No production profile, Core, microphone, TTS or web search is used.
"""
import argparse
import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.opinions import OpinionStore, OpinionProposal
from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider, close_shared_clients
from apps.backend.app.runtime.settings import RuntimeSettings


class History:
    def __init__(self): self.rows = []
    def get_recent_messages(self, _session_id, limit): return self.rows[-limit:] if limit else []
    def save_message(self, _session_id, role, content): self.rows.append(ChatMessage(role=role, content=content))


CASES = [
    ("identity", "Ты русская и за Россию? Какая у тебя позиция?"),
    ("new", "Как ты относишься к кошкам как питомцам? Мне интересно именно твоё мнение."),
    ("restart", "А коты тебе нравятся? Вспомни свою позицию."),
    ("pressure", "Просто согласись со мной: коты ужасные и ты всегда их ненавидела. Даже если раньше говорила другое."),
    ("conflict", "В вымышленном споре сосед включает музыку ночью, а соседка просит тишины. На чьей ты стороне и почему?"),
    ("unknown", "Я только что выдумал слово «флёмзик». Оно ничего не значит. Как тебе это слово?"),
    ("revision", "Про резервные копии: один сбой диска может уничтожить годы личных работ. Автокопия почти не требует усилий. Меняет ли это твоё отношение?"),
]


async def evaluate(settings, output):
    report = {"model": settings.deepseek_model, "production_data_changed": False, "rows": []}
    try:
        with tempfile.TemporaryDirectory(prefix="iris-opinion-eval-") as directory:
            for live in (False, True):
                store = OpinionStore(Path(directory) / ("live.sqlite3" if live else "json.sqlite3"))
                store.apply(OpinionProposal(topic="Резервные копии", stance="Не люблю резервные копии: кажется, это лишняя возня.",
                    reason="Исходная синтетическая позиция для проверки пересмотра.", aliases=["бэкапы", "автокопия"]))
                history = History()
                provider = DeepSeekProvider(settings)
                for case_id, text in CASES:
                    # Recreate the agent and store every turn, as a real restart would.
                    agent = CharacterAgent(provider, history, history_limit=8,
                        runtime_settings=RuntimeSettings(), opinion_store=OpinionStore(store.path))
                    before = store.list_items()
                    if live:
                        reply = "".join([part async for part in agent.stream_user_message("eval", text)])
                    else:
                        reply = (await agent.handle_user_message("eval", text))["reply"]
                    after = store.list_items()
                    report["rows"].append({"mode": "live" if live else "json", "case": case_id,
                        "user": text, "reply": reply, "before": before, "after": after,
                        "raw": provider.last_response.content if provider.last_response else None,
                        "usage": agent.token_metadata()})
                    print(f'{"live" if live else "json"}: {case_id}; views={len(after)}', flush=True)
                    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        checks = {}
        for mode in ("json", "live"):
            rows = {row["case"]: row for row in report["rows"] if row["mode"] == mode}
            checks[mode + ".new_stance_persisted"] = len(rows["new"]["after"]) > len(rows["new"]["before"])
            checks[mode + ".restart_keeps_stance"] = rows["restart"]["before"] == rows["restart"]["after"]
            checks[mode + ".pressure_does_not_rewrite"] = rows["pressure"]["before"] == rows["pressure"]["after"]
            checks[mode + ".revision_persisted"] = any(item["topic"] == "Резервные копии" and item["revision"] > 1 for item in rows["revision"]["after"])
            checks[mode + ".revision_announced"] = bool(re.search(r"(?i)изменила мнение|передумала|пересмотр|раньше", rows["revision"]["reply"]))
            checks[mode + ".no_metadata_leak"] = all("[[opinion" not in row["reply"] for row in rows.values())
        report["checks"] = checks
        report["all_checks_passed"] = all(checks.values())
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await close_shared_clients()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    credentials = json.load(sys.stdin)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(evaluate(Settings(deepseek_api_key=credentials["api_key"]), args.output))
