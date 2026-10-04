"""Repeatable public-source smoke check; never loads API keys or calls an LLM."""
import asyncio
import json
from apps.backend.app.environment.search_service import SearchService

QUERIES = ("GONE.Fludd Мамбл биография", "какие треки удалили Яндекс Музыка российские платформы 2026",
           "ЛСП последняя песня дата релиза")


async def main():
    service = SearchService()
    try:
        for query in QUERIES:
            snapshot = await service.search(query, force_refresh=True)
            print(json.dumps({"query": query, "status": snapshot.status, "latency_ms": snapshot.latency_ms,
                              "attempts": snapshot.attempts, "sources": snapshot.metadata()["sources"],
                              "llm_tokens": 0}, ensure_ascii=False))
    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(main())
