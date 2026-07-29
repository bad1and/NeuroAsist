"""Exact, deterministic correction of project-specific STT terms."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STT_TERMS: dict[str, list[str]] = {
    "Iris": ["iris"],
    "Ирис": ["ирис", "айрис"],
    "NeuroAsist": ["neuroasist", "нейроасист", "нейро ассист"],
    "GigaAM": ["gigaam", "гигаам", "гига ам", "гига эм", "гигаэм"],
    "DeepSeek": ["deepseek", "дипсик", "дип сик"],
    "ComfyUI": ["comfyui", "комфиуай", "комфи юай", "комфи ю ай"],
    "GitHub": ["github", "гитхаб", "гит хаб"],
}


@dataclass(frozen=True)
class TermReplacement:
    source: str
    target: str
    start: int
    end: int

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class CorrectedTranscript:
    raw_text: str
    text: str
    replacements: tuple[TermReplacement, ...] = ()


def _clean_terms(entries: dict[str, object]) -> dict[str, list[str]]:
    cleaned: dict[str, list[str]] = {}
    aliases_seen: dict[str, str] = {}
    for raw_canonical, raw_aliases in entries.items():
        canonical = str(raw_canonical).strip()
        if not canonical or not isinstance(raw_aliases, list):
            raise ValueError("STT terms must map a canonical term to a list of aliases")
        aliases: list[str] = []
        for raw_alias in raw_aliases:
            alias = " ".join(str(raw_alias).strip().split())
            if not alias:
                continue
            key = alias.casefold()
            owner = aliases_seen.get(key)
            if owner is not None and owner != canonical:
                raise ValueError(f"STT alias {alias!r} is assigned to multiple terms")
            aliases_seen[key] = canonical
            if key not in {item.casefold() for item in aliases}:
                aliases.append(alias)
        if aliases:
            cleaned[canonical] = aliases
    return cleaned


def load_stt_terms(path: Path) -> dict[str, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {key: list(value) for key, value in DEFAULT_STT_TERMS.items()}
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not read STT terms: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("STT terms file must contain a JSON object")
    return _clean_terms(payload)


def save_stt_terms(path: Path, entries: dict[str, object]) -> dict[str, list[str]]:
    cleaned = _clean_terms(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return cleaned


def correct_stt_terms(text: str, entries: dict[str, list[str]]) -> CorrectedTranscript:
    if not text or not entries:
        return CorrectedTranscript(text, text)
    aliases: list[tuple[str, str]] = []
    for canonical, values in entries.items():
        aliases.extend((alias, canonical) for alias in values)
    aliases.sort(key=lambda item: (-len(item[0]), item[0].casefold(), item[1]))
    owner = {" ".join(alias.casefold().split()): canonical for alias, canonical in aliases}
    alternatives = [
        re.escape(alias).replace(r"\ ", r"\s+")
        for alias, _canonical in aliases
    ]
    pattern = re.compile(
        rf"(?<!\w)(?:{'|'.join(alternatives)})(?!\w)",
        flags=re.IGNORECASE | re.UNICODE,
    )
    replacements: list[TermReplacement] = []

    def replace(match: re.Match[str]) -> str:
        source = match.group(0)
        canonical = owner[" ".join(source.casefold().split())]
        if source == canonical:
            return source
        replacements.append(TermReplacement(source, canonical, match.start(), match.end()))
        return canonical

    corrected = pattern.sub(replace, text)
    return CorrectedTranscript(text, corrected, tuple(replacements))
