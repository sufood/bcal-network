"""Post-resolution AHPRA enrichment — look up specialty by clinician name.

After entity resolution, many master clinicians lack a specialty because
they were found via PubMed/trials/grants which don't carry that info.
This module searches AHPRA by each clinician's full name, navigates to
their detail page, and extracts specialist registration type and specialty.

Only targets clinicians without specialty, ordered by influence score.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from playwright.async_api import Page

from gyn_kol.models.ahpra_registration import AhpraRegistration
from gyn_kol.models.clinician import MasterClinician
from gyn_kol.resolution.normalise import normalise_name

logger = logging.getLogger(__name__)

AHPRA_SEARCH_URL = "https://www.ahpra.gov.au/Registration/Registers-of-Practitioners.aspx"

# Default: enrich the top N clinicians without specialty
DEFAULT_LIMIT = 500

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _parse_detail_page(html: str) -> dict[str, Any]:
    """Parse an AHPRA practitioner detail page for registration info.

    The detail page has sections like:
      - "Registration Type – General"
      - "Registration Type – Specialist"

    Under the Specialist section, the specialty is in a div.field-entry
    next to a div.field-title containing "Specialty".

    Returns:
        Dict with name, profession, registration_number, registration_type,
        specialty, and all_registrations.
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict[str, Any] = {}

    # Practitioner name
    name_el = soup.select_one("h2.practitioner-name")
    if name_el:
        result["name_raw"] = name_el.get_text(strip=True)

    # Profession
    prof_el = soup.select_one("h3.practitioner-profession")
    if prof_el:
        result["profession"] = prof_el.get_text(strip=True)

    # Registration number from the reg-details section
    reg_el = soup.select_one("div.practitioner-reg-details")
    if reg_el:
        text = reg_el.get_text(strip=True)
        # Registration number is typically in format like "MED0001234567"
        import re
        match = re.search(r"[A-Z]{3}\d{10,}", text)
        if match:
            result["registration_number"] = match.group()

    # Parse all registration type sections
    all_registrations: list[dict[str, str]] = []
    specialty: str | None = None

    # Each section has a section-title with "Registration Type – <type>"
    sections = soup.select("div.practitioner-detail-section")
    for section in sections:
        title_el = section.select_one("div.section-title")
        if not title_el:
            continue
        title_text = title_el.get_text(strip=True)

        if "Registration Type" not in title_text:
            continue

        reg_info: dict[str, str] = {"registration_type": title_text}

        # Look for specialty within this section
        # Structure: div.section-row > div.field-title "Specialty" + div.field-entry "value"
        rows = section.select("div.section-row")
        for row in rows:
            field_title = row.select_one("div.field-title, .field-title")
            field_entry = row.select_one("div.field-entry, .field-entry")
            if field_title and field_entry:
                key = field_title.get_text(strip=True).lower()
                value = field_entry.get_text(strip=True)
                if key == "specialty" and value:
                    reg_info["specialty"] = value
                    # Prefer specialist specialty over general
                    if "specialist" in title_text.lower():
                        specialty = value

        # Also check for field-entry with data-text-color="blue" (specialty value)
        if "specialty" not in reg_info:
            blue_entries = section.select("div.field-entry[data-text-color='blue']")
            for entry in blue_entries:
                text = entry.get_text(strip=True)
                # Skip entries that look like dates or status values
                if text and not text.startswith("30/") and text not in ("None",):
                    parent_row = entry.find_parent("div", class_="section-row")
                    if parent_row:
                        title = parent_row.select_one("div.field-title, .field-title")
                        if title and "specialty" in title.get_text(strip=True).lower():
                            reg_info["specialty"] = text
                            if "specialist" in title_text.lower():
                                specialty = text

        all_registrations.append(reg_info)

    # If no specialist specialty found, take any specialty from any registration type
    if not specialty:
        for reg in all_registrations:
            if reg.get("specialty"):
                specialty = reg["specialty"]
                break

    result["specialty"] = specialty
    result["all_registrations"] = all_registrations

    # Determine primary registration type
    if any("specialist" in r.get("registration_type", "").lower() for r in all_registrations):
        result["registration_type"] = "Specialist"
    elif all_registrations:
        result["registration_type"] = "General"

    return result


async def _search_and_open_detail(
    page: Page, full_name: str,
) -> dict[str, Any] | None:
    """Search AHPRA by full name, find the best match, click into detail page.

    AHPRA uses javascript:void(0) links — must click the result element
    directly rather than navigating to a URL.

    Returns parsed detail page dict, or None if no match found.
    """
    await page.goto(AHPRA_SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_selector("#name-reg, #predictiveSearchHomeBtn", timeout=15000)
    except Exception:
        logger.debug("AHPRA enrichment: search form not found, proceeding anyway")
    await asyncio.sleep(random.uniform(2, 4))

    # Fill full name into search field
    search_input = page.locator("#name-reg")
    await search_input.fill(full_name)
    await asyncio.sleep(random.uniform(0.5, 1.5))

    # Select "Medical Practitioner" profession
    profession_dropdown = page.locator("#health-profession-dropdown .select")
    try:
        if await profession_dropdown.count() > 0 and await profession_dropdown.is_visible():
            await profession_dropdown.click()
            await asyncio.sleep(0.5)
            option = page.locator("#health-profession-dropdown li:has-text('Medical Practitioner')")
            if await option.count() > 0:
                await option.click()
                await asyncio.sleep(0.5)
    except Exception:
        pass

    # Submit search
    search_btn = page.locator("#predictiveSearchHomeBtn")
    await search_btn.click()

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_selector(
            "div.search-results-table-row, table tbody tr, .no-results",
            timeout=15000,
        )
    except Exception:
        pass
    await asyncio.sleep(random.uniform(2, 4))

    # Collect result names and find best match index
    name_norm = normalise_name(full_name)
    result_rows = page.locator("div.search-results-table-row[data-practitioner-row-id]")
    row_count = await result_rows.count()

    if row_count == 0:
        return None

    best_idx = -1
    best_score = 0.0
    best_name = ""
    best_reg_id = ""

    for idx in range(row_count):
        row = result_rows.nth(idx)
        link = row.locator("a").first
        if await link.count() == 0:
            continue
        row_name = (await link.text_content() or "").strip()
        reg_id = (await row.get_attribute("data-practitioner-row-id")) or ""
        score = fuzz.token_sort_ratio(name_norm, normalise_name(row_name))
        if score > best_score:
            best_score = score
            best_idx = idx
            best_name = row_name
            best_reg_id = reg_id

    # AHPRA names include full formal names (middle names, honorifics) so
    # token_sort_ratio can be low even for correct matches.  Use a two-tier
    # check: require >=70 on token_sort AND verify that every token in the
    # search name appears in the AHPRA name (partial containment).
    if best_idx < 0 or best_score < 60:
        logger.debug("AHPRA: no match for '%s' in %d results (best=%.0f)", full_name, row_count, best_score)
        return None

    # Verify partial containment: all tokens from search name should appear in AHPRA name
    if best_score < 80:
        search_tokens = set(name_norm.lower().split())
        ahpra_tokens = set(normalise_name(best_name).lower().split())
        if not search_tokens.issubset(ahpra_tokens):
            logger.debug(
                "AHPRA: score=%.0f but tokens don't match for '%s' vs '%s'",
                best_score, full_name, best_name,
            )
            return None

    # Click the best matching result link to open the detail page
    best_link = result_rows.nth(best_idx).locator("a").first
    await best_link.click()

    # Wait for the detail page to load (practitioner detail section)
    try:
        await page.wait_for_selector(
            "h2.practitioner-name, div.practitioner-detail-section",
            timeout=15000,
        )
    except Exception:
        logger.debug("AHPRA: detail page didn't load for '%s'", full_name)
        return None
    await asyncio.sleep(random.uniform(1, 2))

    html = await page.content()
    detail = _parse_detail_page(html)
    detail["_match_score"] = best_score
    detail["_search_name"] = best_name
    detail["_registration_number"] = best_reg_id or detail.get("registration_number")
    return detail


async def enrich_specialty_from_ahpra(
    session: AsyncSession,
    limit: int = DEFAULT_LIMIT,
    headless: bool = True,
) -> int:
    """Search AHPRA by full clinician name, visit detail page, update specialty.

    Args:
        session: Async DB session.
        limit: Max number of clinicians to look up.
        headless: Run browser headlessly.

    Returns:
        Number of clinicians updated with specialty.
    """
    from playwright.async_api import async_playwright

    # Get clinicians without specialty, ordered by influence score desc
    stmt = (
        select(MasterClinician)
        .where(MasterClinician.specialty.is_(None))
        .order_by(MasterClinician.influence_score.desc())
        .limit(limit)
    )
    clinicians = (await session.execute(stmt)).scalars().all()

    if not clinicians:
        logger.info("AHPRA enrichment: all clinicians already have specialty")
        return 0

    logger.info(
        "AHPRA enrichment: looking up %d clinicians without specialty", len(clinicians)
    )

    updated = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            for i, clinician in enumerate(clinicians):
                name = clinician.name_display or ""
                if not name or len(name) < 3:
                    continue

                try:
                    detail = await _search_and_open_detail(page, name)
                except Exception:
                    logger.debug(
                        "AHPRA enrichment: failed for '%s'", name, exc_info=True
                    )
                    await asyncio.sleep(random.uniform(1, 2))
                    continue

                if not detail:
                    logger.debug(
                        "AHPRA enrichment [%d/%d]: no match for '%s'",
                        i + 1, len(clinicians), name,
                    )
                    await asyncio.sleep(random.uniform(1, 2))
                    continue

                specialty = detail.get("specialty")
                match_score = detail.get("_match_score", 0)

                if specialty:
                    await session.execute(
                        update(MasterClinician)
                        .where(MasterClinician.clinician_id == clinician.clinician_id)
                        .values(specialty=specialty)
                    )
                    updated += 1
                    logger.info(
                        "AHPRA enrichment [%d/%d]: %s → %s (match=%.0f, regs=%s)",
                        i + 1, len(clinicians), name, specialty, match_score,
                        [r.get("registration_type", "?") for r in detail.get("all_registrations", [])],
                    )

                    # Store in ahpra_registrations if not already there
                    reg_num = detail.get("_registration_number") or detail.get("registration_number")
                    if reg_num:
                        existing = await session.execute(
                            select(AhpraRegistration).where(
                                AhpraRegistration.registration_number == reg_num
                            )
                        )
                        if not existing.scalar_one_or_none():
                            session.add(AhpraRegistration(
                                name_raw=detail.get("name_raw", name),
                                name_normalised=normalise_name(
                                    detail.get("name_raw", name)
                                ),
                                registration_number=reg_num,
                                profession=detail.get("profession"),
                                registration_type=detail.get("registration_type"),
                                specialty=specialty,
                                state=clinician.state,
                                raw_payload=detail,
                            ))
                else:
                    logger.debug(
                        "AHPRA enrichment [%d/%d]: no specialist specialty for '%s' (regs=%s)",
                        i + 1, len(clinicians), name,
                        [r.get("registration_type", "?") for r in detail.get("all_registrations", [])],
                    )

                # Rate limit — be polite to AHPRA
                await asyncio.sleep(random.uniform(2, 4))

                # Commit periodically
                if (i + 1) % 10 == 0:
                    await session.commit()
                    logger.info(
                        "AHPRA enrichment: progress %d/%d, updated %d so far",
                        i + 1, len(clinicians), updated,
                    )

        finally:
            await browser.close()

    await session.commit()
    logger.info("AHPRA enrichment: updated %d/%d clinicians", updated, len(clinicians))
    return updated
