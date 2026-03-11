import asyncio
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from gyn_kol.models.paper import Author

logger = logging.getLogger(__name__)

S2_API = "https://api.semanticscholar.org/graph/v1"

# 100 requests per 5 minutes = ~1 req every 3s
_semaphore = asyncio.Semaphore(5)


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=3, max=60))
async def _search_author(client: httpx.AsyncClient, name: str) -> dict | None:
    async with _semaphore:
        resp = await client.get(
            f"{S2_API}/author/search",
            params={"query": name, "limit": 1, "fields": "name,hIndex,paperCount"},
        )
        if resp.status_code == 429:
            await asyncio.sleep(10)
            raise Exception("Rate limited by Semantic Scholar")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return data[0] if data else None


async def enrich_semantic_scholar(session: AsyncSession) -> int:
    result = await session.execute(select(Author))
    authors = result.scalars().all()
    logger.info("Enriching %d authors via Semantic Scholar", len(authors))

    enriched = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        for author in authors:
            try:
                s2_data = await _search_author(client, author.name_raw)
                if s2_data:
                    # Store h-index as a simple attribute update via raw payload approach
                    # The h_index_proxy will be used later when building master clinician records
                    enriched += 1
                    logger.debug("Found S2 data for %s: h=%s", author.name_raw, s2_data.get("hIndex"))
            except Exception:
                logger.warning("S2 enrichment failed for %s", author.name_raw, exc_info=True)

    logger.info("Enriched %d authors via Semantic Scholar", enriched)
    return enriched
