from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from gyn_kol.models.canrefer_profile import CanreferProfile
from gyn_kol.resolution.normalise import normalise_name

logger = logging.getLogger(__name__)

CANREFER_BASE_URL = "https://www.canrefer.org.au"
CANREFER_LISTING_URL = f"{CANREFER_BASE_URL}/gynaecological-oncologists"

_semaphore = asyncio.Semaphore(3)

# Australian states used as section headers on the listing page
_STATE_NAMES = {
    "new south wales": "NSW",
    "nsw": "NSW",
    "victoria": "VIC",
    "vic": "VIC",
    "queensland": "QLD",
    "qld": "QLD",
    "south australia": "SA",
    "sa": "SA",
    "western australia": "WA",
    "wa": "WA",
    "tasmania": "TAS",
    "tas": "TAS",
    "northern territory": "NT",
    "nt": "NT",
    "australian capital territory": "ACT",
    "act": "ACT",
}


def _resolve_state(text: str) -> str | None:
    """Map a state header/label to its abbreviation."""
    return _STATE_NAMES.get(text.strip().lower())


def _extract_slug(url: str) -> str | None:
    """Extract the specialist slug from a Canrefer profile URL."""
    match = re.search(r"/specialists/([^/?#]+)", url, re.IGNORECASE)
    return match.group(1).lower() if match else None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def _fetch_page(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a URL and return the response text."""
    async with _semaphore:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _parse_listing_page(html: str) -> list[dict[str, Any]]:
    """Parse the gynaecological oncologists listing page.

    Returns a list of dicts with: name, location, phone, profile_url, slug, state.
    """
    soup = BeautifulSoup(html, "lxml")
    specialists: list[dict[str, Any]] = []
    current_state: str | None = None

    # The page organises specialists by state with section headers.
    # Try multiple selector strategies for the state headings.
    content = soup.select_one("main, .content, #content, article, .page-content, body")
    if content is None:
        content = soup

    for element in content.descendants:
        if not isinstance(element, Tag):
            continue

        # Detect state section headers
        if element.name in ("h2", "h3", "h4"):
            resolved = _resolve_state(element.get_text(strip=True))
            if resolved:
                current_state = resolved
                continue

        # Detect specialist entries — look for links to /specialists/
        if element.name == "a":
            href = str(element.get("href", ""))
            if "/specialists/" not in str(href).lower():
                continue

            full_url = href if href.startswith("http") else f"{CANREFER_BASE_URL}{href}"
            slug = _extract_slug(full_url)
            if not slug:
                continue

            name = element.get_text(strip=True)
            if not name:
                continue

            # Try to find location and phone in surrounding context
            parent = element.parent
            location = None
            phone = None
            if parent:
                # Look for sibling or nearby text with location/phone info
                text = parent.get_text(" ", strip=True)
                # Phone pattern: +61... or (0x)...
                phone_match = re.search(r"(\+61[\d\s]+|\(0\d\)\s*\d{4}\s*\d{4}|\d{4}\s*\d{4})", text)
                if phone_match:
                    phone = phone_match.group(1).strip()

                # Location is often a suburb near the name
                grandparent = parent.parent
                if grandparent:
                    location_el = grandparent.select_one(".location, .suburb, .address, span:not(:first-child)")
                    if location_el:
                        location = location_el.get_text(strip=True)

            specialists.append({
                "name": name,
                "location": location,
                "phone": phone,
                "profile_url": full_url,
                "slug": slug,
                "state": current_state,
            })

    # Deduplicate by slug (same specialist might appear multiple times)
    seen_slugs: set[str] = set()
    unique: list[dict[str, Any]] = []
    for spec in specialists:
        if spec["slug"] not in seen_slugs:
            seen_slugs.add(spec["slug"])
            unique.append(spec)

    logger.info("Canrefer listing: found %d unique specialists", len(unique))
    return unique


def _parse_profile_jsonld(html: str) -> dict[str, Any] | None:
    """Extract JSON-LD structured data from a specialist profile page."""
    soup = BeautifulSoup(html, "lxml")
    script_tags = soup.find_all("script", type="application/ld+json")

    for script in script_tags:
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        # The JSON-LD might be a WebPage wrapping a Person, or directly a Person
        if isinstance(data, dict):
            if data.get("@type") == "Person":
                return data
            main_entity = data.get("mainEntity")
            if isinstance(main_entity, dict) and main_entity.get("@type") == "Person":
                return main_entity

    logger.debug("No Person JSON-LD found in profile page")
    return None


def _extract_profile_data(jsonld: dict[str, Any], listing_entry: dict[str, Any]) -> dict[str, Any]:
    """Map JSON-LD fields to CanreferProfile model fields."""
    # Extract work locations
    work_locations = []
    for loc in jsonld.get("workLocation", []):
        if isinstance(loc, dict):
            addr = loc.get("address", {})
            if isinstance(addr, str):
                address_str = addr
            elif isinstance(addr, dict):
                parts = [addr.get("streetAddress", ""), addr.get("addressLocality", ""),
                         addr.get("addressRegion", ""), addr.get("postalCode", "")]
                address_str = ", ".join(p for p in parts if p)
            else:
                address_str = ""
            work_locations.append({
                "name": loc.get("name", ""),
                "address": address_str,
                "phone": loc.get("telephone", ""),
                "fax": loc.get("faxNumber", ""),
                "email": loc.get("email", ""),
            })

    # Extract hospitals (worksFor)
    hospitals = []
    for org in jsonld.get("worksFor", []):
        if isinstance(org, dict):
            hospitals.append({
                "name": org.get("name", ""),
                "type": org.get("@type", ""),
                "description": org.get("description", ""),
            })
        elif isinstance(org, str):
            hospitals.append({"name": org, "type": "", "description": ""})

    # Extract MDTs (memberOf)
    mdts = []
    for mem in jsonld.get("memberOf", []):
        if isinstance(mem, dict):
            mdts.append({"name": mem.get("name", ""), "type": mem.get("@type", "")})
        elif isinstance(mem, str):
            mdts.append({"name": mem, "type": ""})

    # Job titles
    job_titles = jsonld.get("jobTitle", [])
    if isinstance(job_titles, str):
        job_titles = [job_titles]

    # Languages
    languages = jsonld.get("knowsLanguage", [])
    if isinstance(languages, str):
        languages = [languages]

    name_raw = jsonld.get("name", listing_entry["name"])

    return {
        "name_raw": name_raw,
        "name_normalised": normalise_name(name_raw),
        "given_name": jsonld.get("givenName"),
        "family_name": jsonld.get("familyName"),
        "honorific_prefix": jsonld.get("honorificPrefix"),
        "gender": jsonld.get("gender"),
        "state": listing_entry.get("state"),
        "slug": listing_entry["slug"],
        "job_titles": job_titles,
        "languages": languages,
        "work_locations": work_locations,
        "hospitals": hospitals,
        "mdts": mdts,
        "phone": listing_entry.get("phone"),
        "profile_url": listing_entry["profile_url"],
        "raw_payload": jsonld,
    }


async def fetch_canrefer_profiles(session: AsyncSession, state: str | None = None) -> int:
    """Scrape Canrefer gynaecological oncologists listing and detail pages.

    Args:
        session: Async DB session.
        state: Optional state filter (e.g. "NSW"). If None, fetches all states.

    Returns:
        Number of new profiles stored.
    """
    stored = 0
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # Phase 1: Fetch listing page
        try:
            listing_html = await _fetch_page(client, CANREFER_LISTING_URL)
        except Exception:
            logger.error("Failed to fetch Canrefer listing page", exc_info=True)
            return 0

        specialists = _parse_listing_page(listing_html)

        # Filter by state if requested
        if state:
            state_upper = state.upper()
            specialists = [s for s in specialists if s.get("state") == state_upper]
            logger.info("Filtered to %d specialists in %s", len(specialists), state_upper)

        # Phase 2: Fetch individual profile pages
        for spec in specialists:
            # Check if already stored (dedup by slug)
            existing = await session.execute(
                select(CanreferProfile).where(CanreferProfile.slug == spec["slug"])
            )
            if existing.scalar_one_or_none():
                logger.debug("Skipping existing profile: %s", spec["slug"])
                continue

            try:
                profile_html = await _fetch_page(client, spec["profile_url"])
                await asyncio.sleep(0.5)  # Polite delay
            except Exception:
                logger.warning("Failed to fetch profile for %s", spec["name"], exc_info=True)
                continue

            jsonld = _parse_profile_jsonld(profile_html)
            if jsonld:
                profile_data = _extract_profile_data(jsonld, spec)
            else:
                # Fall back to listing data only
                logger.warning("No JSON-LD for %s, using listing data only", spec["name"])
                profile_data = {
                    "name_raw": spec["name"],
                    "name_normalised": normalise_name(spec["name"]),
                    "state": spec.get("state"),
                    "slug": spec["slug"],
                    "phone": spec.get("phone"),
                    "profile_url": spec["profile_url"],
                }

            cp = CanreferProfile(**profile_data)
            session.add(cp)
            stored += 1

    await session.commit()
    logger.info("Stored %d new Canrefer profiles", stored)
    return stored
