from __future__ import annotations

import json
import re
from pathlib import Path


DEFAULT_PRONUNCIATIONS = {
    "NeuroAsist": "Нейро Асист",
    "OpenAI": "Оупен Эй Ай",
    "GitHub": "Гитхаб",
    "YouTube": "Ютуб",
    "Discord": "Дискорд",
}


def load_pronunciations(path: Path) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            json.dumps({"pronunciations": DEFAULT_PRONUNCIATIONS}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = payload.get("pronunciations", payload)
        if not isinstance(values, dict):
            raise ValueError("pronunciations must be an object")
        custom = {str(key).strip(): str(value).strip() for key, value in values.items() if str(key).strip() and str(value).strip()}
    except (OSError, ValueError, json.JSONDecodeError):
        custom = {}
    return {**DEFAULT_PRONUNCIATIONS, **custom}


def apply_pronunciations(text: str, entries: dict[str, str]) -> str:
    for source in sorted(entries, key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
        text = pattern.sub(entries[source], text)
    return text
