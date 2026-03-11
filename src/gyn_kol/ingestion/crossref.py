import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from gyn_kol.models.paper import Paper

logger = logging.getLogger(__name__)

CROSSREF_API = "https://api.crossref.org/works"


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30))
async def _fetch_crossref(client: httpx.AsyncClient, doi: str) -> dict | None:
    resp = await client.get(f"{CROSSREF_API}/{doi}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("message", {})


async def enrich_crossref(session: AsyncSession, crossref_email: str) -> int:
    result = await session.execute(
        select(Paper).where(Paper.doi.isnot(None), Paper.citation_count.is_(None))
    )
    papers = result.scalars().all()
    logger.info("Enriching %d papers via CrossRef", len(papers))

    enriched = 0
    headers = {"User-Agent": f"GynKOL/0.1 (mailto:{crossref_email})"} if crossref_email else {}
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        for paper in papers:
            try:
                data = await _fetch_crossref(client, paper.doi)  # type: ignore[arg-type]
                if data:
                    paper.citation_count = data.get("is-referenced-by-count", 0)
                    enriched += 1
            except Exception:
                logger.warning("CrossRef enrichment failed for DOI %s", paper.doi, exc_info=True)

    await session.commit()
    logger.info("Enriched %d papers with citation counts", enriched)
    return enriched
