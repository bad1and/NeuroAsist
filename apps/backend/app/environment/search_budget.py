"""Fail-closed Tavily Free admission and durable reservations across processes."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3


class SearchBudget:
    limit = 900

    def __init__(self, path: Path | None):
        self.path = path

    def reserve(self, usage: dict) -> dict:
        account, key = usage.get("account"), usage.get("key")
        if not isinstance(account, dict) or not isinstance(key, dict):
            return {"status": "unverified_free_plan"}
        if str(account.get("current_plan", "")).casefold() not in {"free", "researcher"}:
            return {"status": "unverified_free_plan"}
        fields = [account.get(n) for n in ("plan_usage", "plan_limit", "paygo_usage", "paygo_limit")]
        fields += [key.get(n) for n in ("usage", "limit")]
        if any(type(n) is not int or n < 0 for n in fields):
            return {"status": "unverified_free_plan"}
        remote, remote_limit, paygo, paygo_limit, key_used, key_limit = fields
        if paygo or paygo_limit or not 0 < remote_limit <= 1000:
            return {"status": "unverified_free_plan"}
        if not self.path:
            return {"status": "budget_unavailable"}
        month = datetime.now(UTC).strftime("%Y-%m")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # No refunds: a timed out or cancelled request may have been billed.
        with sqlite3.connect(self.path, timeout=2) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS search_budget (month TEXT PRIMARY KEY, used INTEGER NOT NULL)")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT used FROM search_budget WHERE month=?", (month,)).fetchone()
            used = max(row[0] if row else 0, remote)
            allowed = used < min(self.limit, remote_limit) and key_used + max(0, used - remote) < key_limit
            reserved = used + int(allowed)
            connection.execute("INSERT INTO search_budget VALUES (?,?) ON CONFLICT(month) DO UPDATE SET used=excluded.used", (month, reserved))
        return {"status": "reserved" if allowed else "quota_exhausted", "month": month,
                "used": reserved, "limit": self.limit, "remaining": max(0, min(self.limit, remote_limit) - reserved)}
