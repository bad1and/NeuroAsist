from __future__ import annotations

import asyncio
import json

from apps.backend.app.storage.timeline import TimelineStore


class SummaryWorker:
    def __init__(self, store: TimelineStore, after_summary=None) -> None:
        self._store = store
        self._after_summary = after_summary

    async def run_once(self) -> bool:
        job = await asyncio.to_thread(self._store.claim_summary_job)
        if job is None:
            return False
        try:
            episode_id = json.loads(job["payload_json"])["episode_id"]
            summary = await asyncio.to_thread(self._store.summarize_episode, episode_id)
            if self._after_summary is not None:
                self._after_summary(summary)
            await asyncio.to_thread(self._store.complete_summary_job, job["id"])
        except Exception as exc:
            await asyncio.to_thread(self._store.fail_summary_job, job["id"], str(exc))
        return True
