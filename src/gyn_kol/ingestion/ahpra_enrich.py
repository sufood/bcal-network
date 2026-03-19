"""AHPRA enrichment — look up practitioners by name on the AHPRA register.

Two entry points:

1. ``scan_authors_against_ahpra`` — **pre-resolution**.  Takes every
   Australian-affiliated PubMed author and searches AHPRA.  Authors that
   are found get an ``AhpraRegistration`` row, which means they will pass
   the Australian-source filter during entity resolution.

2. ``enrich_specialty_from_ahpra`` — **post-resolution**.  For master
   clinicians that already exist but lack a specialty, searches AHPRA to
   fill it in.
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
from gyn_kol.models.paper import Author
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

    # Fill full name into search field
    search_input = page.locator("#name-reg")
    await search_input.fill(full_name)
    await asyncio.sleep(random.uniform(0.2, 0.5))

    # Select "Medical Practitioner" profession
    profession_dropdown = page.locator("#health-profession-dropdown .select")
    try:
        if await profession_dropdown.count() > 0 and await profession_dropdown.is_visible():
            await profession_dropdown.click()
            await asyncio.sleep(0.2)
            option = page.locator("#health-profession-dropdown li:has-text('Medical Practitioner')")
            if await option.count() > 0:
                await option.click()
                await asyncio.sleep(0.2)
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
    await asyncio.sleep(random.uniform(0.2, 0.5))

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
    await asyncio.sleep(random.uniform(0.1, 0.3))

    html = await page.content()
    detail = _parse_detail_page(html)
    detail["_match_score"] = best_score
    detail["_search_name"] = best_name
    detail["_registration_number"] = best_reg_id or detail.get("registration_number")
    return detail


async def _worker(
    worker_id: int,
    browser: Any,
    queue: asyncio.Queue,
    results: list[tuple[str, str, dict[str, Any]]],
    total: int,
    progress: dict[str, int],
) -> None:
    """Browser worker: pulls (clinician_id, name) from queue, searches AHPRA."""
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
    )
    page = await context.new_page()

    try:
        while True:
            try:
                clinician_id, name, state = queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            progress["done"] += 1
            idx = progress["done"]

            try:
                detail = await _search_and_open_detail(page, name)
            except Exception:
                logger.debug(
                    "AHPRA worker %d: failed for '%s'", worker_id, name, exc_info=True
                )
                await asyncio.sleep(random.uniform(0.5, 1))
                continue

            if detail and detail.get("specialty"):
                results.append((clinician_id, state, detail))
                logger.info(
                    "AHPRA enrichment [%d/%d] w%d: %s → %s (match=%.0f)",
                    idx, total, worker_id, name, detail["specialty"],
                    detail.get("_match_score", 0),
                )
            else:
                logger.debug(
                    "AHPRA enrichment [%d/%d] w%d: no match for '%s'",
                    idx, total, worker_id, name,
                )

            # Rate limit per worker — staggered across workers
            await asyncio.sleep(random.uniform(0.5, 1.0))
    finally:
        await context.close()


# Number of parallel browser contexts
DEFAULT_WORKERS = 8

# Number of separate browser instances to avoid Playwright serialisation
DEFAULT_BROWSERS = 2

# Workers per browser instance
WORKERS_PER_BROWSER = DEFAULT_WORKERS // DEFAULT_BROWSERS


async def _run_browser_pool(
    worker_fn: Any,
    queue: asyncio.Queue,
    results: list[tuple[str, str, dict[str, Any]]],
    total: int,
    progress: dict[str, int],
    headless: bool,
    num_workers: int,
    num_browsers: int = DEFAULT_BROWSERS,
    **worker_kwargs: Any,
) -> None:
    """Launch multiple independent browser instances, each running a subset of workers.

    Avoids Playwright's internal serialisation on a single browser by
    spreading workers across separate Chromium processes.

    Extra *worker_kwargs* (e.g. ``on_match``) are forwarded to each worker.
    """
    from playwright.async_api import async_playwright

    actual_workers = min(num_workers, total)
    actual_browsers = min(num_browsers, actual_workers)
    workers_per = max(1, actual_workers // actual_browsers)
    remainder = actual_workers - workers_per * actual_browsers

    async def _browser_group(
        browser_idx: int, n_workers: int, worker_offset: int,
    ) -> None:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            try:
                tasks = [
                    worker_fn(
                        worker_offset + i, browser, queue, results, total, progress,
                        **worker_kwargs,
                    )
                    for i in range(n_workers)
                ]
                await asyncio.gather(*tasks)
            finally:
                await browser.close()

    groups = []
    offset = 0
    for b in range(actual_browsers):
        n = workers_per + (1 if b < remainder else 0)
        groups.append(_browser_group(b, n, offset))
        offset += n

    await asyncio.gather(*groups)


async def enrich_specialty_from_ahpra(
    session: AsyncSession,
    limit: int = DEFAULT_LIMIT,
    headless: bool = True,
    num_workers: int = DEFAULT_WORKERS,
) -> int:
    """Search AHPRA by full clinician name, visit detail page, update specialty.

    Runs multiple browser instances in parallel for throughput.

    Args:
        session: Async DB session.
        limit: Max number of clinicians to look up.
        headless: Run browser headlessly.
        num_workers: Number of parallel browser contexts.

    Returns:
        Number of clinicians updated with specialty.
    """
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
        "AHPRA enrichment: looking up %d clinicians with %d workers across %d browsers",
        len(clinicians), num_workers, DEFAULT_BROWSERS,
    )

    # Pre-fetch existing registration numbers to avoid per-row SELECT
    existing_regs_result = await session.execute(
        select(AhpraRegistration.registration_number)
    )
    existing_reg_nums: set[str] = {
        r for (r,) in existing_regs_result.all() if r
    }

    # Build work queue
    queue: asyncio.Queue = asyncio.Queue()
    for clinician in clinicians:
        name = clinician.name_display or ""
        if name and len(name) >= 3:
            queue.put_nowait((str(clinician.clinician_id), name, clinician.state))

    # Shared results list — workers append (clinician_id, state, detail)
    results: list[tuple[str, str, dict[str, Any]]] = []
    progress: dict[str, int] = {"done": 0}
    total = queue.qsize()

    await _run_browser_pool(
        _worker, queue, results, total, progress,
        headless=headless, num_workers=num_workers,
    )

    # Apply results to DB (sequential — safe for async session)
    updated = 0
    for clinician_id, state, detail in results:
        specialty = detail["specialty"]
        await session.execute(
            update(MasterClinician)
            .where(MasterClinician.clinician_id == clinician_id)
            .values(specialty=specialty)
        )
        updated += 1

        reg_num = detail.get("_registration_number") or detail.get("registration_number")
        if reg_num and reg_num not in existing_reg_nums:
            existing_reg_nums.add(reg_num)
            session.add(AhpraRegistration(
                name_raw=detail.get("name_raw", detail.get("_search_name", "")),
                name_normalised=normalise_name(
                    detail.get("name_raw", detail.get("_search_name", ""))
                ),
                registration_number=reg_num,
                profession=detail.get("profession"),
                registration_type=detail.get("registration_type"),
                specialty=specialty,
                state=state,
                raw_payload=detail,
            ))

    await session.commit()
    logger.info("AHPRA enrichment: updated %d/%d clinicians", updated, len(clinicians))
    return updated


# ---------------------------------------------------------------------------
# Pre-resolution: scan ALL Australian authors against AHPRA
# ---------------------------------------------------------------------------


async def _scan_worker(
    worker_id: int,
    browser: Any,
    queue: asyncio.Queue,
    results: list[tuple[str, str, dict[str, Any]]],
    total: int,
    progress: dict[str, int],
    *,
    on_match: Any | None = None,
) -> None:
    """Like _worker but accepts any AHPRA match (specialty not required).

    If *on_match* is provided it is called as
    ``await on_match(author_id, state, detail)`` after every successful
    lookup so the caller can persist results incrementally.
    """
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
    )
    page = await context.new_page()

    try:
        while True:
            try:
                author_id, name, state = queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            progress["done"] += 1
            idx = progress["done"]

            try:
                detail = await _search_and_open_detail(page, name)
            except Exception:
                logger.debug(
                    "AHPRA scan w%d: failed for '%s'", worker_id, name, exc_info=True
                )
                await asyncio.sleep(random.uniform(0.5, 1))
                continue

            if detail:
                results.append((author_id, state, detail))
                if on_match is not None:
                    await on_match(author_id, state, detail)
                logger.info(
                    "AHPRA scan [%d/%d] w%d: %s → found (match=%.0f, specialty=%s)",
                    idx, total, worker_id, name,
                    detail.get("_match_score", 0),
                    detail.get("specialty", "n/a"),
                )
            else:
                logger.debug(
                    "AHPRA scan [%d/%d] w%d: no match for '%s'",
                    idx, total, worker_id, name,
                )

            await asyncio.sleep(random.uniform(0.5, 1.0))
    finally:
        await context.close()


async def scan_authors_against_ahpra(
    session: AsyncSession,
    headless: bool = True,
    num_workers: int = DEFAULT_WORKERS,
) -> int:
    """Search AHPRA for every Australian-affiliated PubMed author.

    Runs **before** entity resolution so that authors confirmed in the
    AHPRA register get an ``AhpraRegistration`` row.  This ensures they
    pass the Australian-source filter in ``build_master_records``.

    Authors whose normalised name already appears in ``ahpra_registrations``
    are skipped to avoid redundant lookups.

    Results are committed to the DB incrementally so progress is visible
    in real time and no work is lost if the scan is interrupted.

    Returns:
        Number of new ``AhpraRegistration`` rows created.
    """
    # All Australian authors (state detected)
    stmt = select(Author).where(Author.state.isnot(None))
    authors = (await session.execute(stmt)).scalars().all()

    if not authors:
        logger.info("AHPRA author scan: no Australian authors to scan")
        return 0

    # Pre-fetch already-known AHPRA names and reg numbers to skip duplicates
    existing_names_result = await session.execute(
        select(AhpraRegistration.name_normalised)
    )
    existing_names: set[str] = {
        n for (n,) in existing_names_result.all() if n
    }
    existing_regs_result = await session.execute(
        select(AhpraRegistration.registration_number)
    )
    existing_reg_nums: set[str] = {
        r for (r,) in existing_regs_result.all() if r
    }

    # Build queue — skip authors already matched by normalised name
    queue: asyncio.Queue = asyncio.Queue()
    skipped_existing = 0
    for author in authors:
        name = author.name_raw or ""
        if len(name) < 3:
            continue
        norm = normalise_name(name)
        if norm in existing_names:
            skipped_existing += 1
            continue
        queue.put_nowait((author.author_id, name, author.state))

    total = queue.qsize()
    logger.info(
        "AHPRA author scan: %d Australian authors to look up "
        "(%d already matched, %d total) with %d workers",
        total, skipped_existing, len(authors), num_workers,
    )

    if total == 0:
        return 0

    results: list[tuple[str, str, dict[str, Any]]] = []
    progress: dict[str, int] = {"done": 0}

    # --- Incremental DB persistence via on_match callback ---------------
    db_lock = asyncio.Lock()
    created = {"count": 0}

    async def _persist_match(
        _author_id: str, state: str, detail: dict[str, Any],
    ) -> None:
        reg_num = detail.get("_registration_number") or detail.get("registration_number")

        async with db_lock:
            if reg_num and reg_num in existing_reg_nums:
                return  # already stored from a different name variant

            name_raw = detail.get("name_raw", detail.get("_search_name", ""))
            norm = normalise_name(name_raw)

            session.add(AhpraRegistration(
                name_raw=name_raw,
                name_normalised=norm,
                registration_number=reg_num,
                profession=detail.get("profession"),
                registration_type=detail.get("registration_type"),
                specialty=detail.get("specialty"),
                state=state,
                raw_payload=detail,
            ))
            if reg_num:
                existing_reg_nums.add(reg_num)
            existing_names.add(norm)
            created["count"] += 1

            # Commit every match immediately so progress is visible
            await session.commit()
    # --------------------------------------------------------------------

    await _run_browser_pool(
        _scan_worker, queue, results, total, progress,
        headless=headless, num_workers=num_workers,
        on_match=_persist_match,
    )

    logger.info(
        "AHPRA author scan: created %d new registrations from %d matches",
        created["count"], len(results),
    )
    return created["count"]
