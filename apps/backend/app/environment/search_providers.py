"""Optional user-selected search APIs. No credentials enter public metadata."""
from __future__ import annotations

import httpx

from apps.backend.app.environment.retrieval import canonical_url, clean_text, parse_date

API_PROVIDERS = ("brave", "tavily", "serper")


async def api_search(client: httpx.AsyncClient, provider: str, key: str, query: str,
                     *, mode: str = "web", since: str = "", until: str = "") -> list[dict]:
    news = mode == "news"
    if provider == "brave":
        params = {"q": query, "count": 10, "search_lang": "ru", "extra_snippets": "true"}
        if since and until:
            params["freshness"] = f"{since[:10]}to{until[:10]}"
        response = await client.get(f"https://api.search.brave.com/res/v1/{'news' if news else 'web'}/search",
                                    params=params, headers={"X-Subscription-Token": key})
    elif provider == "tavily":
        body = {"query": query, "topic": "news" if news else "general", "search_depth": "basic",
                "max_results": 10, "include_answer": False, "include_raw_content": False,
                "include_published_date": True, "auto_parameters": False}
        if since:
            body["start_date"] = since[:10]
        if until:
            body["end_date"] = until[:10]
        response = await client.post("https://api.tavily.com/search", json=body,
                                     headers={"Authorization": f"Bearer {key}"})
    elif provider == "serper":
        body = {"q": query, "num": 10, "hl": "ru", "gl": "ru"}
        if since and until:
            body["tbs"] = f"cdr:1,cd_min:{since[:10]},cd_max:{until[:10]}"
        response = await client.post(f"https://google.serper.dev/{'news' if news else 'search'}",
                                     json=body, headers={"X-API-KEY": key})
    else:
        raise ValueError("Unsupported search provider")
    response.raise_for_status()
    if len(response.content) > 1_000_000:
        raise ValueError("Search response too large")
    payload = response.json()
    if provider == "brave":
        items = payload.get("results", []) if news else payload.get("web", {}).get("results", [])
    elif provider == "tavily":
        items = payload.get("results", [])
    else:
        items = payload.get("news" if news else "organic", [])
    if not isinstance(items, list):
        raise ValueError("Invalid search response")
    results = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        url = canonical_url(str(item.get("url") or item.get("link") or ""))
        title = clean_text(str(item.get("title") or ""), 120)
        date = parse_date(str(item.get("published_date") or item.get("page_age") or item.get("date") or ""))
        if url and title:
            results.append({"title": title, "url": url,
                            "snippet": clean_text(str(item.get("content") or item.get("description") or item.get("snippet") or ""), 300),
                            "published_at": date.isoformat() if date else "", "provider": provider})
    return results
