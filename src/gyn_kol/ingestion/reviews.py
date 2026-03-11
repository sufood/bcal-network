import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from gyn_kol.models.review_signal import ReviewSignal

logger = logging.getLogger(__name__)

PLACES_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
PLACES_DETAIL_URL = "https://maps.googleapis.com/maps/api/place/details/json"

TECH_KEYWORDS = [
    "minimally invasive",
    "robotic",
    "laparoscopic",
    "endometriosis",
    "keyhole",
    "da vinci",
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def _find_place(client: httpx.AsyncClient, query: str, api_key: str) -> str | None:
    resp = await client.get(
        PLACES_SEARCH_URL,
        params={
            "input": query,
            "inputtype": "textquery",
            "fields": "place_id",
            "key": api_key,
        },
    )
    resp.raise_for_status()
    candidates = resp.json().get("candidates", [])
    return candidates[0]["place_id"] if candidates else None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def _get_place_details(client: httpx.AsyncClient, place_id: str, api_key: str) -> dict:
    resp = await client.get(
        PLACES_DETAIL_URL,
        params={
            "place_id": place_id,
            "fields": "name,rating,user_ratings_total,reviews",
            "key": api_key,
        },
    )
    resp.raise_for_status()
    return resp.json().get("result", {})


def _extract_keyword_mentions(reviews: list[dict]) -> dict[str, int]:
    mentions: dict[str, int] = {}
    for review in reviews:
        text = review.get("text", "").lower()
        for kw in TECH_KEYWORDS:
            if kw in text:
                mentions[kw] = mentions.get(kw, 0) + 1
    return mentions


async def fetch_review_signals(
    session: AsyncSession,
    clinician_queries: list[dict[str, str]],
    api_key: str,
) -> int:
    stored = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        for query_info in clinician_queries:
            name = query_info.get("name", "")
            suburb = query_info.get("suburb", "")
            clinician_id = query_info.get("clinician_id")
            search_query = f"{name} gynaecologist {suburb} Australia"

            try:
                place_id = await _find_place(client, search_query, api_key)
                if not place_id:
                    logger.debug("No place found for %s", search_query)
                    continue

                existing = await session.execute(
                    select(ReviewSignal).where(ReviewSignal.place_id == place_id)
                )
                if existing.scalar_one_or_none():
                    continue

                details = await _get_place_details(client, place_id, api_key)
                reviews = details.get("reviews", [])

                signal = ReviewSignal(
                    clinician_id=clinician_id,
                    source="google_maps",
                    place_id=place_id,
                    rating=details.get("rating"),
                    review_count=details.get("user_ratings_total", 0),
                    keyword_mentions=_extract_keyword_mentions(reviews) or None,
                )
                session.add(signal)
                stored += 1

            except Exception:
                logger.warning("Review fetch failed for %s", name, exc_info=True)

    await session.commit()
    logger.info("Stored %d review signals", stored)
    return stored
