from __future__ import annotations

import asyncio


class SemanticSyncWorker:
    def __init__(self, memory_service) -> None:
        self._memory_service = memory_service

    async def run_once(self) -> bool:
        return await asyncio.to_thread(self._memory_service.sync_next_index_job)
