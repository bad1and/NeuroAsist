"""Record OSV matches for a Python environment and Cargo lock; not release approval."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def request_json(url: str, payload: dict | None = None) -> dict:
    request = Request(url, data=None if payload is None else json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "User-Agent": "Iris-dependency-review/1"})
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def query_all(query: dict, initial: dict, fetch=request_json) -> list[str]:
    """Consume every OSV page, rejecting a repeated continuation token."""
    result, seen, ids = initial, set(), set()
    while True:
        ids.update(v["id"] for v in result.get("vulns", []))
        token = result.get("next_page_token")
        if not token:
            return sorted(ids)
        if token in seen:
            raise RuntimeError("OSV returned a repeated page token")
        seen.add(token)
        result = fetch("https://api.osv.dev/v1/query", {**query, "page_token": token})


def review_errors(report: dict, review: dict) -> list[str]:
    """Require a decision for every matched ID and the exact input hashes.

    This checks review coverage, not the correctness of a legal/security grant.
    """
    errors = []
    if report["target"] != review.get("target"):
        errors.append("Review target differs from the scanned target")
    if report["source_sha256"] != review.get("source_sha256"):
        errors.append("Review source hashes differ from the scanned inputs")
    allowed = {"not_reachable_in_windows_profile", "conditional_on_trusted_models", "not_applicable_to_windows_target",
               "outside_windows_dependency_graph", "maintenance_warning"}
    decisions = {(d["package"]["ecosystem"], d["package"]["name"].lower(), d["version"]): d for d in review["decisions"]}
    for match in report["matches"]:
        key = (match["package"]["ecosystem"], match["package"]["name"].lower(), match["version"])
        decision = decisions.get(key)
        if not decision or decision.get("decision") not in allowed or not decision.get("reason") or not decision.get("evidence_paths"):
            errors.append(f"No documented decision for {key}")
            continue
        missing = set(match["advisory_ids"]) - set(decision["advisory_ids"])
        if missing:
            errors.append(f"Unreviewed advisory IDs for {key}: {', '.join(sorted(missing))}")
    return errors


def scan(output: Path, python_source: str, target: str) -> dict:
    queries = []
    if python_source == "installed":
        for d in metadata.distributions():
            queries.append({"package": {"ecosystem": "PyPI", "name": d.metadata["Name"]},
                            "version": d.version.split("+", 1)[0]})
    else:
        for line in (ROOT / "requirements/constraints.txt").read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+)==([^;\s]+)", line)
            if match:
                queries.append({"package": {"ecosystem": "PyPI", "name": match[1]}, "version": match[2]})
    tree = subprocess.check_output([
        "cargo", "tree", "--locked", "--target", target, "--edges", "normal,build", "--prefix", "none",
        "--format", "{p}", "--manifest-path", str(ROOT / "apps/desktop/src-tauri/Cargo.toml"),
    ], cwd=ROOT, text=True, encoding="utf-8")
    target_packages = {(m[1], m[2]) for line in tree.splitlines()
                       if (m := re.match(r"^([\w-]+) v([^\s]+)", line))}
    for p in tomllib.loads((ROOT / "apps/desktop/src-tauri/Cargo.lock").read_text(encoding="utf-8"))["package"]:
        if p.get("source", "").startswith("registry+"):
            queries.append({"package": {"ecosystem": "crates.io", "name": p["name"]}, "version": p["version"]})
    matches = []
    for start in range(0, len(queries), 100):
        batch = queries[start:start + 100]
        response = request_json("https://api.osv.dev/v1/querybatch", {"queries": batch})
        if len(response["results"]) != len(batch):
            raise RuntimeError("Incomplete OSV batch response")
        for query, result in zip(batch, response["results"], strict=True):
            ids = query_all(query, result)
            if ids:
                p = query["package"]
                matches.append({**query, "advisory_ids": ids,
                                "in_target_graph": None if p["ecosystem"] == "PyPI" else (p["name"], query["version"]) in target_packages})
    ids = sorted({i for m in matches for i in m["advisory_ids"]})
    with ThreadPoolExecutor(max_workers=6) as executor:
        advisories = dict(zip(ids, executor.map(lambda i: request_json("https://api.osv.dev/v1/vulns/" + i), ids), strict=True))
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(), "python_source": python_source, "target": target,
        "scope": "Environment/constraints and entire registry Cargo.lock, including build and foreign targets; matches require reachability review",
        "source_sha256": {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in
                          ["requirements/runtime.txt", "requirements/build.txt", "requirements/torch-cpu.txt",
                           "requirements/constraints.txt", "apps/desktop/src-tauri/Cargo.lock"]},
        "queries": queries, "target_packages": sorted(target_packages), "matches": matches, "advisories": advisories,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-source", choices=["installed", "constraints"], default="installed")
    parser.add_argument("--target", default="x86_64-pc-windows-msvc")
    parser.add_argument("--decisions", type=Path, help="Fail on new unmatched IDs or stale source hashes; does not approve distribution")
    args = parser.parse_args()
    report = scan(args.output, args.python_source, args.target)
    print(f"OSV snapshot: {len(report['queries'])} queries; {len(report['matches'])} matching versions; {len(report['advisories'])} advisory IDs.")
    for match in report["matches"]:
        print(match["package"]["ecosystem"], match["package"]["name"], match["version"],
              "target=" + str(match["in_target_graph"]), ",".join(match["advisory_ids"]))
    if args.decisions:
        errors = review_errors(report, json.loads(args.decisions.read_text(encoding="utf-8")))
        if errors:
            raise SystemExit("\n".join(errors))
        print("Every match is covered by the dated review; distribution and artifact acceptance remain separate.")
