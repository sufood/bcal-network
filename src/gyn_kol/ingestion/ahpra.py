from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from playwright.async_api import Page

from gyn_kol.models.ahpra_registration import AhpraRegistration
from gyn_kol.resolution.normalise import normalise_name

logger = logging.getLogger(__name__)

AHPRA_SEARCH_URL = "https://www.ahpra.gov.au/Registration/Registers-of-Practitioners.aspx"

DEFAULT_SEARCH_TERMS = ["Gynaecologist", "Oncologist"]
DEFAULT_STATES = ["NSW"]

# Maximum pages to paginate through per search (safety cap)
MAX_PAGES = 100

# Realistic browser settings
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _parse_results_page(html: str) -> list[dict[str, Any]]:
    """Parse AHPRA search results from rendered HTML.

    The AHPRA results page uses a div-based layout (not a <table>).
    Each practitioner is a ``div.search-results-table-row`` with the
    registration number in ``data-practitioner-row-id``.  Specialty
    is inside ``<span data-mobile-speciality>`` (British spelling).
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[dict[str, Any]] = []

    # Strategy 1 (primary): Div-based AHPRA results layout
    rows = soup.select("div.search-results-table-row[data-practitioner-row-id]")
    if rows:
        logger.debug("AHPRA results matched div strategy with %d rows", len(rows))
        for row in rows:
            reg_number = row.get("data-practitioner-row-id", "")

            # Name: first link inside the row (practitioner name is a hyperlink)
            name_el = row.select_one("a")
            name = name_el.get_text(strip=True) if name_el else ""
            if not name:
                continue

            result: dict[str, Any] = {
                "name_raw": name,
                "registration_number": reg_number or None,
            }

            # Profession: text from the profession column
            prof_el = row.select_one("div.col-span-row div.col.division, div.col-span-row .division")
            if not prof_el:
                # Fallback: look for standalone text near the name
                col_els = row.select("div.search-results-table-col")
                if len(col_els) >= 2:
                    prof_el = col_els[1]
            if prof_el:
                result["profession"] = prof_el.get_text(strip=True)

            # Registration types and specialty from col-span-row sections.
            # Each practitioner can have multiple rows (General + Specialist).
            reg_types: list[str] = []
            specialty: str | None = None

            reg_type_els = row.select("div.col.reg-type, div.reg-type")
            for rt_el in reg_type_els:
                # Registration type text is in a <p> tag
                p_tag = rt_el.select_one("p")
                if p_tag:
                    reg_types.append(p_tag.get_text(strip=True))

                # Specialty is in <span data-mobile-speciality> (note British spelling)
                spec_span = rt_el.select_one("span[data-mobile-speciality]")
                if spec_span:
                    spec_text = spec_span.get_text(strip=True)
                    # Strip the "Specialty: " prefix
                    if spec_text.lower().startswith("specialty:"):
                        spec_text = spec_text[len("Specialty:"):].strip()
                    if spec_text:
                        specialty = spec_text

            # If no reg-type divs found, try broader search
            if not reg_types:
                span_els = row.select("span[data-mobile-speciality]")
                for span_el in span_els:
                    spec_text = span_el.get_text(strip=True)
                    if spec_text.lower().startswith("specialty:"):
                        spec_text = spec_text[len("Specialty:"):].strip()
                    if spec_text:
                        specialty = spec_text

            # Use the most specific registration type
            if "Specialist" in reg_types:
                result["registration_type"] = "Specialist"
            elif reg_types:
                result["registration_type"] = reg_types[0]

            if specialty:
                result["specialty"] = specialty

            results.append(result)
        return results

    # Strategy 2: Table-based results (legacy fallback)
    table_selectors = [
        "table.search-results tbody tr",
        "table.tablefilter tbody tr",
        "table tbody tr",
    ]
    for selector in table_selectors:
        table_rows = soup.select(selector)
        if table_rows:
            logger.debug("AHPRA results matched table selector '%s' with %d rows", selector, len(table_rows))
            for row in table_rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue

                name = cells[0].get_text(strip=True) if cells else ""
                if not name:
                    continue

                table_result: dict[str, Any] = {"name_raw": name}

                if len(cells) >= 2:
                    table_result["profession"] = cells[1].get_text(strip=True)
                if len(cells) >= 3:
                    table_result["registration_number"] = cells[2].get_text(strip=True)
                if len(cells) >= 4:
                    table_result["registration_type"] = cells[3].get_text(strip=True)
                if len(cells) >= 5:
                    table_result["specialty"] = cells[4].get_text(strip=True)

                # Check for registration number in links
                for link in row.find_all("a"):
                    href = str(link.get("href", ""))
                    if "registration" in href.lower() or "practitioner" in href.lower():
                        link_text = link.get_text(strip=True)
                        if link_text and "registration_number" not in table_result:
                            table_result["registration_number"] = link_text

                results.append(table_result)
            return results

    # Strategy 3: Generic card-based results (fallback)
    card_selectors = [
        ".search-result",
        ".practitioner-result",
        ".result-item",
        ".search-results-item",
    ]
    for selector in card_selectors:
        cards = soup.select(selector)
        if cards:
            logger.debug("AHPRA results matched card selector '%s' with %d items", selector, len(cards))
            for card in cards:
                name_el = card.select_one("h3, h4, .name, .practitioner-name, strong")
                name = name_el.get_text(strip=True) if name_el else ""
                if not name:
                    continue

                card_result: dict[str, Any] = {"name_raw": name}

                reg_el = card.select_one(".registration-number, .reg-number")
                if reg_el:
                    card_result["registration_number"] = reg_el.get_text(strip=True)

                prof_el = card.select_one(".profession")
                if prof_el:
                    card_result["profession"] = prof_el.get_text(strip=True)

                spec_el = card.select_one("span[data-mobile-speciality], .specialty")
                if spec_el:
                    spec_text = spec_el.get_text(strip=True)
                    if spec_text.lower().startswith("specialty:"):
                        spec_text = spec_text[len("Specialty:"):].strip()
                    card_result["specialty"] = spec_text

                results.append(card_result)
            return results

    if not results:
        logger.warning("AHPRA: no results parsed — page structure may have changed. Logging page snippet.")
        body = soup.find("body")
        if body:
            logger.debug("Page body snippet: %s", str(body)[:2000])

    return results


async def _search_and_paginate(
    page: Page,
    search_term: str,
    state: str,
) -> list[dict[str, Any]]:
    """Execute an AHPRA search and paginate through all result pages.

    Args:
        page: Playwright Page object.
        search_term: Term to enter in the search field (e.g., "Gynaecologist").
        state: Australian state abbreviation (e.g., "NSW").

    Returns:
        List of result dicts from all pages.
    """
    all_results: list[dict[str, Any]] = []

    logger.info("AHPRA search: term='%s', state='%s'", search_term, state)

    # Navigate to search page — avoid "networkidle" as AHPRA keeps persistent
    # analytics connections that prevent idle from ever being reached.
    await page.goto(AHPRA_SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
    # Wait for the search form to render
    try:
        await page.wait_for_selector("#name-reg, #predictiveSearchHomeBtn", timeout=15000)
    except Exception:
        logger.debug("AHPRA: search form elements not found, proceeding anyway")
    await asyncio.sleep(random.uniform(2, 4))

    # Fill practitioner search field (NOT the global site search)
    # The form has: input#name-reg (visible text field for name/registration)
    search_input = page.locator("#name-reg")
    await search_input.fill(search_term)
    await asyncio.sleep(random.uniform(0.5, 1.5))

    # Select health profession from custom dropdown
    # The dropdown is a div#health-profession-dropdown with <li> items
    profession_dropdown = page.locator("#health-profession-dropdown .select")
    try:
        if await profession_dropdown.count() > 0 and await profession_dropdown.is_visible():
            await profession_dropdown.click()
            await asyncio.sleep(0.5)
            # Look for "Medical Practitioner" in the dropdown list
            option = page.locator("#health-profession-dropdown li:has-text('Medical Practitioner')")
            if await option.count() > 0:
                await option.click()
                logger.debug("Selected health profession: Medical Practitioner")
                await asyncio.sleep(0.5)
    except Exception:
        logger.debug("Could not select health profession dropdown")

    # Select state from custom dropdown
    # The dropdown is div#state-dropdown with <li> items
    state_dropdown = page.locator("#state-dropdown .select")
    try:
        if await state_dropdown.count() > 0 and await state_dropdown.is_visible():
            await state_dropdown.click()
            await asyncio.sleep(0.5)
            state_option = page.locator(f"#state-dropdown li:has-text('{state}')")
            if await state_option.count() > 0:
                await state_option.click()
                logger.debug("Selected state: %s", state)
                await asyncio.sleep(0.5)
    except Exception:
        logger.debug("Could not select state dropdown")

    await asyncio.sleep(random.uniform(0.5, 1))

    # Click the practitioner search submit button
    search_btn = page.locator("#predictiveSearchHomeBtn")
    await search_btn.click()

    # Wait for results to load — wait for result elements or URL change
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_selector(
            "table tbody tr, .search-result, .practitioner-result, .result-item, .no-results",
            timeout=15000,
        )
    except Exception:
        logger.debug("AHPRA: result elements not found after search, proceeding with page content")
    await asyncio.sleep(random.uniform(2, 4))

    # Parse initial results
    html = await page.content()
    page_results = _parse_results_page(html)

    if not page_results:
        logger.warning("AHPRA: no results for '%s' in %s", search_term, state)
    else:
        all_results.extend(page_results)
        logger.info("AHPRA: initial load found %d results", len(page_results))

    # AHPRA uses "Load More" button instead of traditional pagination
    for page_num in range(2, MAX_PAGES + 1):
        load_more_selectors = [
            "button:has-text('Load More')",
            "button:has-text('Load more')",
            "a:has-text('Load More')",
            ".load-more button",
            "#load-more-btn",
            "button.load-more",
        ]
        load_more_found = False
        for sel in load_more_selectors:
            load_more_btn = page.locator(sel).first
            try:
                if await load_more_btn.count() > 0 and await load_more_btn.is_visible():
                    prev_count = len(all_results)
                    await load_more_btn.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                    await asyncio.sleep(random.uniform(1, 2))

                    html = await page.content()
                    page_results = _parse_results_page(html)
                    new_results = page_results[prev_count:]

                    if new_results:
                        all_results.extend(new_results)
                        logger.info("AHPRA page %d: loaded %d more results (total: %d)", page_num, len(new_results), len(all_results))
                        load_more_found = True
                    break
            except Exception:
                continue

        if not load_more_found:
            logger.info("AHPRA: no more results after page %d", page_num)
            break

    logger.info("AHPRA search complete: %d total results for '%s' in %s", len(all_results), search_term, state)
    return all_results


async def fetch_ahpra_registrations(
    session: AsyncSession,
    search_terms: list[str] | None = None,
    states: list[str] | None = None,
    headless: bool = True,
) -> int:
    """Scrape AHPRA practitioner register using Playwright browser automation.

    Args:
        session: Async DB session.
        search_terms: Search terms to use (default: ["Gynaecologist", "Oncologist"]).
        states: States to search (default: ["NSW"]).
        headless: Run browser in headless mode (set False for debugging).

    Returns:
        Number of new registrations stored.
    """
    if search_terms is None:
        search_terms = DEFAULT_SEARCH_TERMS
    if states is None:
        states = DEFAULT_STATES

    stored = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            for search_term in search_terms:
                for state in states:
                    try:
                        results = await _search_and_paginate(page, search_term, state)
                    except Exception:
                        logger.error(
                            "AHPRA search failed for '%s' in %s",
                            search_term,
                            state,
                            exc_info=True,
                        )
                        continue

                    for result in results:
                        reg_num = result.get("registration_number")

                        # Dedup by registration number if available
                        if reg_num:
                            existing = await session.execute(
                                select(AhpraRegistration).where(
                                    AhpraRegistration.registration_number == reg_num
                                )
                            )
                            if existing.scalar_one_or_none():
                                continue

                        name_raw = result["name_raw"]
                        registration = AhpraRegistration(
                            name_raw=name_raw,
                            name_normalised=normalise_name(name_raw),
                            registration_number=reg_num,
                            profession=result.get("profession"),
                            registration_type=result.get("registration_type"),
                            registration_status=result.get("registration_status"),
                            specialty=result.get("specialty"),
                            state=state,
                            search_profession=search_term,
                            search_state=state,
                            raw_payload=result,
                        )
                        session.add(registration)
                        stored += 1

                    # Delay between different searches
                    await asyncio.sleep(random.uniform(3, 6))

        finally:
            await browser.close()

    await session.commit()
    logger.info("Stored %d new AHPRA registrations", stored)
    return stored
