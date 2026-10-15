"""Bounded persona replay, with provider usage and a human review rubric.

Credentials arrive as JSON on stdin, never in command arguments or a report.
No Core, production history, memory, TTS or search is started. --snapshot saves
only assembled prompts; --baseline-snapshot compares exactly those prompts.
Example: python -m scripts.evaluate_character_voice --snapshot output/prompts.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from apps.backend.app.agents.character.dialogue_pacing import DialoguePacing, infer_dialogue_pacing
from apps.backend.app.agents.character.dialogue_style import dialogue_style_prompt, has_street_voice
from apps.backend.app.agents.character.memes import MemeLibrary
from apps.backend.app.agents.character.persona import get_persona
from apps.backend.app.agents.character.prompts import character_json_prompt, character_live_prompt
from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import ChatMessage, llm_call_purpose
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider, close_shared_clients
from apps.backend.app.schemas.character import CharacterTurn
from pydantic import ValidationError


CORPUS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "character_voice_eval.json"


def prompt_snapshot() -> dict:
    return {
        "persona_version": get_persona("default").persona_version,
        "live": character_live_prompt(),
        "json": character_json_prompt(include_memory_protocol=False),
        "style": {m: dialogue_style_prompt(m) for m in ("street", "restrained", "clean")},
        "pacing": {m: DialoguePacing(m).prompt_block(input_mode="text")
                   for m in ("micro", "conversational", "banter", "focused", "deep")},
    }


def case_messages(case: dict, prompts: dict, *, live: bool) -> list[ChatMessage]:
    history = [ChatMessage(**m) for m in case.get("history", [])]
    pacing = infer_dialogue_pacing(case["user"], history).mode
    # Old snapshots predate banter. Their actual request classifier used focused
    # for jokes and conversational for "прожарь"; don't give them the new cue.
    if pacing not in prompts["pacing"]:
        from apps.backend.app.agents.character.turn_intent import analyze_dialogue_turn
        pacing = "focused" if analyze_dialogue_turn(case["user"], history).kind == "request" else "conversational"
    meme_context = MemeLibrary().prompt(case["user"], recent_messages=history, mode=pacing,
                                       style=case.get("style", "street"),
                                       allow_humor=case.get("humor_policy", "normal") not in {"avoid", "restrained"}) if prompts.get("persona_version", 0) >= 11 else ""
    return [
        ChatMessage(role="system", content=prompts["live" if live else "json"]),
        *([ChatMessage(role="system", content=case["state_context"])] if case.get("state_context") else []),
        *history,
        *([ChatMessage(role="system", content=case["ambient"])] if case.get("ambient") else []),
        *([ChatMessage(role="system", content=meme_context)] if meme_context else []),
        ChatMessage(role="system", content=infer_dialogue_pacing(case["user"], history).prompt_block(input_mode="voice" if live else "text", recent_messages=history)
                    if prompts.get("persona_version", 0) >= 11 else prompts["pacing"][pacing]),
        ChatMessage(role="system", content=dialogue_style_prompt(case.get("style", "street"), turn_mode=pacing,
                    user_text=case["user"], humor_policy=case.get("humor_policy", "normal"))
                    if prompts.get("persona_version", 0) >= 11 else prompts["style"][case.get("style", "street")]),
        ChatMessage(role="user", content=case["user"]),
    ]


async def evaluate(settings: Settings, cases: list[dict], variants: dict[str, dict], *, modes=("live", "json")) -> dict:
    report = {"created_at": datetime.now(UTC).isoformat(), "model": settings.deepseek_model,
              "production_history_changed": False, "search_enabled": False,
              "judging": "Human rubric; slang frequency is diagnostic, not a quality score.",
              "variants": variants, "rows": []}
    try:
        # Sequential requests give trustworthy per-call streaming metrics and
        # reuse the connection/cache. No hidden judge or style-regeneration call.
        provider = DeepSeekProvider(settings)
        for variant, prompts in variants.items():
            for mode in modes:
                for case in cases:
                    row = {"variant": variant, "mode": mode, "id": case["id"],
                           "user": case["user"], "rubric": case["rubric"]}
                    messages = case_messages(case, prompts, live=mode == "live")
                    try:
                        with llm_call_purpose("chat_live" if mode == "live" else "chat_json"):
                            if mode == "live":
                                raw = "".join([part async for part in provider.stream(messages)])
                                row["raw"] = raw
                                reply = re.sub(r"\[\[.*?\]\]", "", raw, flags=re.DOTALL).strip()
                                row["protocol_valid"] = raw.startswith("[[avatar ") and bool(reply.strip())
                            else:
                                response = await provider.generate(messages)
                                raw = response.content
                                row["raw"] = raw
                                payload = json.loads(raw)
                                row["reply"] = payload.get("reply", "")
                                parsed = CharacterTurn.model_validate_json(raw)
                                reply = parsed.reply
                                row["protocol_valid"] = True
                        row.update(reply=reply, raw=raw, informal_vocabulary=has_street_voice(reply))
                    except Exception as exc:
                        # Exceptions can contain a request; only log its type.
                        row.update(error=type(exc).__name__, protocol_valid=False)
                        if isinstance(exc, ValidationError):
                            row["validation_errors"] = [
                                {"loc": e["loc"], "type": e["type"]} for e in exc.errors()
                            ]
                    metrics = provider.last_call_metrics
                    if metrics is not None:
                        row["metrics"] = metrics.model_dump(mode="json")
                    report["rows"].append(row)
                    print(json.dumps({k: v for k, v in row.items() if k not in {"raw", "rubric"}}, ensure_ascii=False), flush=True)
    finally:
        await close_shared_clients()
    return report


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Offline: save current prompts, without reading credentials")
    parser.add_argument("--baseline-snapshot", type=Path)
    parser.add_argument("--limit", type=int, default=12, help="Cases per variant per mode; 1..32")
    parser.add_argument("--mode", choices=("live", "json", "both"), default="both")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.snapshot:
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot.write_text(json.dumps(prompt_snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if not 1 <= args.limit <= 32:
        parser.error("--limit must be 1..32")
    if not args.output:
        parser.error("--output is required for API replay")
    credentials = json.load(sys.stdin)
    key = credentials.get("deepseek_api_key")
    if not isinstance(key, str) or not key.strip():
        parser.error("stdin must supply a nonempty deepseek_api_key")
    variants = {}
    if args.baseline_snapshot:
        variants["baseline"] = json.loads(args.baseline_snapshot.read_text(encoding="utf-8"))
    variants["current"] = prompt_snapshot()
    cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"][:args.limit]
    modes = ("live", "json") if args.mode == "both" else (args.mode,)
    result = asyncio.run(evaluate(Settings(deepseek_api_key=key), cases, variants, modes=modes))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
