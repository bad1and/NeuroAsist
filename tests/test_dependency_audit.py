import pytest

from scripts.audit_dependencies import query_all, review_errors


def test_osv_pagination_keeps_matches_from_every_page():
    query = {"package": {"ecosystem": "PyPI", "name": "example"}, "version": "1"}
    calls = []

    def fetch(url, payload):
        calls.append(payload)
        return {"vulns": [{"id": "later"}, {"id": "first"}]}

    assert query_all(query, {"vulns": [{"id": "first"}], "next_page_token": "next"}, fetch) == ["first", "later"]
    assert calls == [{**query, "page_token": "next"}]


def test_osv_repeating_page_token_fails_instead_of_reporting_complete_scan():
    result = {"next_page_token": "again"}
    with pytest.raises(RuntimeError, match="repeated page token"):
        query_all({}, result, lambda *_: result)


def test_review_rejects_new_advisory_for_an_already_reviewed_package():
    match = {"package": {"ecosystem": "PyPI", "name": "example"}, "version": "1", "advisory_ids": ["old", "new"]}
    report = {"target": "windows", "source_sha256": {"input": "hash"}, "matches": [match]}
    review = {"target": "windows", "source_sha256": report["source_sha256"], "decisions": [
        {**match, "advisory_ids": ["old"], "decision": "not_reachable_in_windows_profile", "reason": "Disabled server API", "evidence_paths": ["app.py"]},
    ]}
    assert any("new" in error for error in review_errors(report, review))


def test_review_rejects_changed_inputs_even_when_match_ids_are_unchanged():
    report = {"target": "windows", "source_sha256": {"input": "new hash"}, "matches": []}
    review = {"target": "windows", "source_sha256": {"input": "old hash"}, "decisions": []}
    assert any("hashes" in error for error in review_errors(report, review))
