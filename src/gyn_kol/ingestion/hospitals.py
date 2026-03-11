"""Fetch hospital/institutional profiles for gynaecology specialists.

Hospital websites vary widely in structure. This module uses:
1. CSS selector-based card extraction (structured pages)
2. Regex name extraction as fallback (unstructured pages)
3. curl subprocess for downloads (httpx blocked by TLS fingerprinting)
"""

import asyncio
import logging
import re
import shutil

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from gyn_kol.models.institutional_profile import InstitutionalProfile

logger = logging.getLogger(__name__)

INSTITUTIONS = [
    {
        "name": "Royal Women's Hospital Melbourne",
        "url": "https://www.thewomens.org.au/research/research-centres/womens-gynaecology-research-centre/wgrc-our-people",
        "state": "VIC",
    },
    {
        "name": "Mercy Hospital for Women",
        "url": "https://health-services.mercyhealth.com.au/service/private-obstetric-care-mhw/",
        "state": "VIC",
    },
    {
        "name": "King Edward Memorial Hospital",
        "url": "https://www.kemh.health.wa.gov.au/Our-services/Gynaecology",
        "state": "WA",
    },
    {
        "name": "Monash Medical Centre",
        "url": "https://monashhealth.org/services/gynaecology/",
        "state": "VIC",
    },
    {
        "name": "Royal Brisbane and Women's Hospital",
        "url": "https://metronorth.health.qld.gov.au/rbwh/healthcare-services/gynaecology",
        "state": "QLD",
    },
    {
        "name": "John Hunter Hospital",
        "url": "https://www.hnehealth.nsw.gov.au/facilities/hospitals/john-hunter-hospital",
        "state": "NSW",
    },
]

# Pattern to match clinician names with title prefixes
_NAME_PATTERN = re.compile(
    r"(?:Dr|Prof(?:essor)?|A/Prof|Associate Prof(?:essor)?|Clinical A/Prof)"
    r"\s+[A-Z][a-z]+(?:\s+[A-Z][a-z'-]+){1,3}"
)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def _fetch_html(url: str) -> str:
    """Fetch HTML using curl subprocess (bypasses TLS fingerprinting)."""
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl not found on PATH")

    proc = await asyncio.create_subprocess_exec(
        curl, "-sL", "--max-time", "30", url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"curl failed (rc={proc.returncode}): {stderr.decode()}")

    return stdout.decode("utf-8", errors="replace")


async def _scrape_institution(institution: dict) -> list[dict]:
    """Scrape a hospital page for specialist profiles."""
    html = await _fetch_html(institution["url"])
    soup = BeautifulSoup(html, "lxml")

    profiles: list[dict] = []

    # Strategy 1: CSS selector-based card extraction
    selectors = [
        "div.staff-card",
        "div.doctor-card",
        "div.specialist-profile",
        "div.team-member",
        "li.staff-item",
        "article.person",
        "div.person-card",
    ]

    for selector in selectors:
        cards = soup.select(selector)
        if cards:
            logger.info("%s: matched selector '%s' with %d results", institution["name"], selector, len(cards))
            for card in cards:
                name_el = card.select_one("h2, h3, h4, .name, .title")
                name = name_el.get_text(strip=True) if name_el else ""
                if not name:
                    continue

                title_el = card.select_one(".position, .role, .designation")
                dept_el = card.select_one(".department, .unit, .specialty")

                profiles.append({
                    "name_raw": name,
                    "institution": institution["name"],
                    "title": title_el.get_text(strip=True) if title_el else None,
                    "department": dept_el.get_text(strip=True) if dept_el else None,
                })
            return profiles

    # Strategy 2: Extract names from text using regex
    # Filter out common false positives (buildings, awards, etc.)
    false_positive_words = {"building", "ward", "centre", "center", "wing", "unit", "award", "lecture", "theatre"}
    seen: set[str] = set()
    for el in soup.find_all(string=_NAME_PATTERN):
        text = el.strip()
        for match in _NAME_PATTERN.finditer(text):
            name = match.group().strip()
            if name in seen:
                continue
            # Skip if name contains a false-positive word
            if any(w in name.lower() for w in false_positive_words):
                continue
            seen.add(name)
            profiles.append({
                "name_raw": name,
                "institution": institution["name"],
                "title": None,
                "department": None,
            })

    if profiles:
        logger.info("%s: extracted %d names via regex fallback", institution["name"], len(profiles))
    else:
        logger.warning("%s: no profiles found — page structure may have changed", institution["name"])

    return profiles


async def fetch_hospital_profiles(session: AsyncSession) -> int:
    stored = 0

    for inst in INSTITUTIONS:
        try:
            profiles = await _scrape_institution(inst)
            for prof in profiles:
                existing = await session.execute(
                    select(InstitutionalProfile).where(
                        InstitutionalProfile.name_raw == prof["name_raw"],
                        InstitutionalProfile.institution == prof["institution"],
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                ip = InstitutionalProfile(
                    name_raw=prof["name_raw"],
                    institution=prof["institution"],
                    title=prof.get("title"),
                    department=prof.get("department"),
                    research_interests=prof.get("research_interests"),
                )
                session.add(ip)
                stored += 1
        except Exception:
            logger.warning("Hospital scrape failed for %s", inst["name"], exc_info=True)

    await session.commit()
    logger.info("Stored %d institutional profiles", stored)
    return stored
