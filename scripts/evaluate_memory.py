"""Run the deterministic long-term-memory release evaluation.

The corpus contains recorded extractor proposals rather than live provider
calls.  That keeps policy, canonicalisation and retrieval measurements stable
in CI; provider prompt quality can be evaluated separately with the same JSON
shape before its proposals enter MemoryService.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.semantic.embedding import HashEmbeddingProvider
from apps.backend.app.semantic.vector_index import SqliteVecIndex
from apps.backend.app.storage.timeline import TimelineStore


DEFAULT_CORPUS = REPOSITORY_ROOT / "tests" / "fixtures" / "memory_eval.json"


def _key(slot: object, value: object) -> str:
    clean = " ".join(str(value).casefold().replace("ё", "е").split())
    return f"{slot}|{clean}"


def _service(directory: Path) -> tuple[TimelineStore, MemoryService]:
    store = TimelineStore(directory / "memory-eval.sqlite3")
    store.init_db()
    index = SqliteVecIndex(
        store._db_path,
        HashEmbeddingProvider(dimension=256),
        store.semantic_index_items,
    )
    return store, MemoryService(
        store,
        RuntimeSettings(memory_mode="automatic"),
        sensitive_mode="ask",
        vector_index=index,
        semantic_enabled=True,
        semantic_limit=8,
    )


def _apply_turn(store: TimelineStore, service: MemoryService, turn: dict[str, Any]) -> list[dict[str, object]]:
    source, _ = store.append_message(
        role="user",
        content=str(turn["text"]),
        input_mode=str(turn.get("input_mode", "text")),
        metadata=dict(turn.get("metadata", {})),
    )
    return service.apply_llm_candidates(list(turn.get("proposals", [])), source)


def _evaluate_writes(cases: list[dict[str, Any]], root: Path) -> dict[str, object]:
    true_positive = false_positive = false_negative = 0
    details: list[dict[str, object]] = []
    for case in cases:
        case_root = root / f"write-{case['id']}"
        case_root.mkdir()
        store, service = _service(case_root)
        for turn in case["turns"]:
            _apply_turn(store, service, turn)
        actual = {
            _key(item.get("slot_key"), item.get("value_text"))
            for item in store.list_memories(status="active", limit=200)
        }
        expected = {
            _key(item["slot"], item["value"])
            for item in case.get("expected_active", [])
        }
        true_positive += len(actual & expected)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
        details.append({
            "id": case["id"],
            "passed": actual == expected,
            "expected": sorted(expected),
            "actual": sorted(actual),
        })
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    return {
        "precision": true_positive / precision_denominator if precision_denominator else 1.0,
        "recall": true_positive / recall_denominator if recall_denominator else 1.0,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "cases_passed": sum(bool(item["passed"]) for item in details),
        "case_count": len(details),
        "cases": details,
    }


def _evaluate_retrieval(cases: list[dict[str, Any]], root: Path) -> dict[str, object]:
    recalled = expected_total = 0
    details: list[dict[str, object]] = []
    for case in cases:
        case_root = root / f"retrieval-{case['id']}"
        case_root.mkdir()
        store, service = _service(case_root)
        ids_by_key: dict[str, str] = {}
        for fact in case.get("facts", []):
            created = _apply_turn(store, service, fact)
            if created:
                ids_by_key[str(fact["key"])] = str(created[-1]["id"])
        for topic in case.get("topics", []):
            created = store.create_topic(topic)
            ids_by_key[str(topic["key"])] = f"topic:{created['id']}"
        for commitment in case.get("commitments", []):
            created = store.create_commitment(commitment)
            ids_by_key[str(commitment["key"])] = f"commitment:{created['id']}"
        service.reindex()
        limit = int(case.get("top_k", 5))
        actual_ids = [str(item["id"]) for item in service.retrieve(str(case["query"]), limit=limit)]
        expected_keys = [str(item) for item in case.get("expected_keys", [])]
        expected_ids = {ids_by_key[key] for key in expected_keys}
        hits = expected_ids & set(actual_ids)
        recalled += len(hits)
        expected_total += len(expected_ids)
        details.append({
            "id": case["id"],
            "passed": hits == expected_ids,
            "expected_keys": expected_keys,
            "actual_keys": [
                key for item_id in actual_ids
                for key, mapped_id in ids_by_key.items()
                if mapped_id == item_id
            ],
        })
    return {
        "recall_at_k": recalled / expected_total if expected_total else 1.0,
        "recalled": recalled,
        "expected": expected_total,
        "cases_passed": sum(bool(item["passed"]) for item in details),
        "case_count": len(details),
        "cases": details,
    }


def evaluate(corpus_path: Path = DEFAULT_CORPUS) -> dict[str, object]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    thresholds = dict(corpus["thresholds"])
    with tempfile.TemporaryDirectory(prefix="iris-memory-eval-") as temporary:
        root = Path(temporary)
        writes = _evaluate_writes(list(corpus["write_cases"]), root)
        retrieval = _evaluate_retrieval(list(corpus["retrieval_cases"]), root)
    passed = (
        float(writes["precision"]) >= float(thresholds["write_precision"])
        and float(writes["recall"]) >= float(thresholds["write_recall"])
        and float(retrieval["recall_at_k"]) >= float(thresholds["retrieval_recall_at_k"])
    )
    return {
        "corpus_version": corpus["version"],
        "passed": passed,
        "thresholds": thresholds,
        "write": writes,
        "retrieval": retrieval,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Iris long-term memory")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.corpus)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
