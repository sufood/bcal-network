"""Fetch MBS item schedule data and store target items.

Downloads the MBS XML schedule from mbsonline.gov.au, parses it with
ElementTree, and stores only the target items of interest.  Falls back
to scraping individual item pages from www9.health.gov.au when the XML
download is unavailable.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import tempfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from gyn_kol.models.mbs_item import MbsItem

logger = logging.getLogger(__name__)

MBS_DOWNLOADS_URL = "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/Content/downloads"
MBS_ITEM_LOOKUP_URL = "https://www9.health.gov.au/mbs/fullDisplay.cfm?type=item&q={item_number}&qt=ItemID"

_semaphore = asyncio.Semaphore(2)

# Target MBS item numbers of interest for GYN KOL identification.
# Keys are item numbers; values are gynaecology relevance notes.
TARGET_ITEMS: dict[str, str] = {
    "35723": (
        "Para-aortic lymph node dissection (unilateral) for staging "
        "gynaecological malignancy — Category 3/T8/Gynaecological"
    ),
    "35724": (
        "Para-aortic lymph node dissection after prior treatment for "
        "malignancy — Category 3/T8/Gynaecological"
    ),
    "104": (
        "Initial specialist consultation (45+ min) after referral — "
        "generic to all specialists; only relevant when provider is an "
        "AHPRA-registered gynaecologist"
    ),
}


# ------------------------------------------------------------------
# XML download + parse
# ------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def _resolve_xml_url(client: httpx.AsyncClient) -> str | None:
    """Scrape the MBS downloads page to find the latest XML file URL."""
    async with _semaphore:
        resp = await client.get(MBS_DOWNLOADS_URL, follow_redirects=True)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    # Look for links containing "MBS-XML" and ending in ".XML"
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if "MBS-XML" in href and href.upper().endswith(".XML"):
            if href.startswith("http"):
                return href
            # Relative URL — resolve against the base
            return f"https://www.mbsonline.gov.au{href}"
    return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def _download_file(client: httpx.AsyncClient, url: str, dest: Path) -> None:
    """Download a file to disk."""
    async with _semaphore, client.stream("GET", url, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                f.write(chunk)
    logger.info("Downloaded %s → %s", url, dest)


def _el_text(item_el: ElementTree.Element, tag: str) -> str | None:
    """Extract text from a child element."""
    el = item_el.find(tag)
    return el.text.strip() if el is not None and el.text else None


def _el_float(item_el: ElementTree.Element, tag: str) -> float | None:
    """Extract a float from a child element."""
    val = _el_text(item_el, tag)
    if val:
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _extract_item_fields(item_el: ElementTree.Element) -> dict[str, Any]:
    """Extract all relevant fields from an MBS XML <Item> element."""
    raw: dict[str, str | None] = {}
    for child in item_el:
        raw[child.tag] = child.text.strip() if child.text else None

    return {
        "description": _el_text(item_el, "Description"),
        "category": _el_text(item_el, "Category"),
        "group": _el_text(item_el, "Group"),
        "subgroup": _el_text(item_el, "SubGroup") or _el_text(item_el, "SubHeading"),
        "schedule_fee": _el_float(item_el, "ScheduleFee"),
        "benefit_75": _el_float(item_el, "Benefit75"),
        "benefit_85": _el_float(item_el, "Benefit85"),
        "item_start_date": _el_text(item_el, "ItemStartDate"),
        "item_end_date": _el_text(item_el, "ItemEndDate"),
        "raw": raw,
    }


def _parse_mbs_xml(xml_path: Path, target_items: set[str]) -> list[dict[str, Any]]:
    """Parse the MBS XML file and extract target items.

    Uses iterative parsing for memory efficiency on the large MBS XML.
    """
    results: list[dict[str, Any]] = []

    try:
        tree = ElementTree.parse(xml_path)
    except ElementTree.ParseError:
        logger.error("Failed to parse MBS XML file", exc_info=True)
        return results

    root = tree.getroot()

    # The MBS XML uses <Item> elements with sub-elements like <ItemNum>
    for item_el in root.iter("Item"):
        item_num_el = item_el.find("ItemNum")
        if item_num_el is None or not item_num_el.text:
            continue

        item_num = item_num_el.text.strip()
        if item_num not in target_items:
            continue

        parsed = _extract_item_fields(item_el)
        parsed["item_number"] = item_num
        results.append(parsed)

    logger.info("Parsed %d target items from MBS XML", len(results))
    return results


# ------------------------------------------------------------------
# HTML scrape fallback (individual item pages)
# ------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=15))
async def _scrape_single_item(client: httpx.AsyncClient, item_number: str) -> dict[str, Any] | None:
    """Scrape a single MBS item from the web lookup page."""
    url = MBS_ITEM_LOOKUP_URL.format(item_number=item_number)
    async with _semaphore:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Look for the description and fee info in the page
    result: dict[str, Any] = {"item_number": item_number, "raw": {"url": url}}

    # Description is typically in a main content area
    desc_el = soup.find(string=re.compile(r"Description", re.IGNORECASE))
    if desc_el:
        parent = desc_el.find_parent("tr") or desc_el.find_parent("div")
        if parent:
            cells = parent.find_all("td")
            if len(cells) >= 2:
                result["description"] = cells[-1].get_text(strip=True)

    # Try to extract structured data from table rows
    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).lower()
        value = cells[-1].get_text(strip=True)

        if "category" in label:
            result["category"] = value
        elif "group" in label and "sub" not in label:
            result["group"] = value
        elif "subgroup" in label or "sub-group" in label:
            result["subgroup"] = value
        elif "schedule fee" in label:
            with contextlib.suppress(ValueError):
                result["schedule_fee"] = float(value.replace("$", "").replace(",", ""))
        elif "75%" in label or "benefit 75" in label:
            with contextlib.suppress(ValueError):
                result["benefit_75"] = float(value.replace("$", "").replace(",", ""))
        elif "85%" in label or "benefit 85" in label:
            with contextlib.suppress(ValueError):
                result["benefit_85"] = float(value.replace("$", "").replace(",", ""))
        elif "item start" in label:
            result["item_start_date"] = value

    # Also try to grab the full page text for description if we missed it
    if "description" not in result:
        # Look for the main content block
        content = soup.select_one("#content, .content, main")
        if content:
            # The description is usually the longest paragraph
            paragraphs = [p.get_text(strip=True) for p in content.find_all("p") if len(p.get_text(strip=True)) > 50]
            if paragraphs:
                result["description"] = max(paragraphs, key=len)

    return result if len(result) > 2 else None  # Must have more than just item_number + raw


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------

async def _store_item(
    session: AsyncSession,
    item_data: dict[str, Any],
    relevance_note: str,
) -> bool:
    """Store a single MBS item, deduplicating on item_number.

    Returns True if a new record was stored.
    """
    existing = await session.execute(
        select(MbsItem).where(MbsItem.item_number == item_data["item_number"])
    )
    if existing.scalar_one_or_none():
        return False

    item = MbsItem(
        item_number=item_data["item_number"],
        description=item_data.get("description"),
        category=item_data.get("category"),
        group=item_data.get("group"),
        subgroup=item_data.get("subgroup"),
        schedule_fee=item_data.get("schedule_fee"),
        benefit_75=item_data.get("benefit_75"),
        benefit_85=item_data.get("benefit_85"),
        gynaecology_relevance=relevance_note,
        item_start_date=item_data.get("item_start_date"),
        item_end_date=item_data.get("item_end_date"),
        raw_payload=item_data.get("raw"),
    )
    session.add(item)
    return True


async def fetch_mbs_items(
    session: AsyncSession,
    target_items: dict[str, str] | None = None,
) -> int:
    """Download MBS XML schedule and store target items.

    Tries the XML download first.  If the download page cannot be
    resolved or the XML fails to parse, falls back to scraping
    individual item lookup pages.

    Args:
        session: Async DB session.
        target_items: Dict mapping item_number → gynaecology_relevance note.
                      Defaults to ``TARGET_ITEMS``.

    Returns:
        Number of new items stored.
    """
    targets = target_items or TARGET_ITEMS
    stored = 0

    async with httpx.AsyncClient(timeout=120.0) as client:
        items: list[dict[str, Any]] = []

        # Attempt 1: Download and parse the full MBS XML
        try:
            xml_url = await _resolve_xml_url(client)
            if xml_url:
                with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    await _download_file(client, xml_url, tmp_path)
                    items = _parse_mbs_xml(tmp_path, set(targets.keys()))
                finally:
                    tmp_path.unlink(missing_ok=True)
            else:
                logger.warning("Could not resolve MBS XML download URL")
        except Exception:
            logger.warning("MBS XML download/parse failed, falling back to scrape", exc_info=True)

        # Attempt 2: Scrape individual item pages for any missing items
        found_nums = {i["item_number"] for i in items}
        missing = set(targets.keys()) - found_nums
        if missing:
            logger.info("Scraping %d missing MBS items individually", len(missing))
            for item_num in sorted(missing):
                try:
                    scraped = await _scrape_single_item(client, item_num)
                    if scraped:
                        items.append(scraped)
                    await asyncio.sleep(1)  # Polite delay
                except Exception:
                    logger.warning("Failed to scrape MBS item %s", item_num, exc_info=True)

        # Store items
        for item_data in items:
            item_num = item_data["item_number"]
            relevance = targets.get(item_num, "")
            if await _store_item(session, item_data, relevance):
                stored += 1

        await session.commit()

    logger.info("Stored %d new MBS items", stored)
    return stored
