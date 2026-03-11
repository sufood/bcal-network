"""Fetch college profiles from RANZCOG and AGES directories.

RANZCOG directory is now an Angular SPA at integrate.ranzcog.edu.au and
requires Playwright to render. AGES members page is static HTML.
"""

import asyncio
import logging
import random

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.college_profile import CollegeProfile

logger = logging.getLogger(__name__)

RANZCOG_DIRECTORY_URL = "https://integrate.ranzcog.edu.au/find-womens-health-doctor"
AGES_BOARD_URL = "https://ages.com.au/ages-society/ages-board/"
AGES_PREV_BOARD_URL = "https://ages.com.au/ages-society/previous-ages-board/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Australian states to search
_STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]


async def _scrape_ranzcog_playwright() -> list[dict]:
    """Scrape RANZCOG directory using Playwright (SPA requires JS rendering)."""
    profiles: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            logger.info("Loading RANZCOG directory...")
            await page.goto(RANZCOG_DIRECTORY_URL, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(random.uniform(2, 4))

            # The SPA has a search form — try clicking search without filters to get all results
            # Look for a search/submit button
            search_btn_selectors = [
                "button:has-text('Search')",
                "button:has-text('Find')",
                "button[type='submit']",
                ".search-btn",
                "button.mat-raised-button",
            ]

            for sel in search_btn_selectors:
                btn = page.locator(sel).first
                try:
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        await asyncio.sleep(random.uniform(2, 4))
                        logger.info("RANZCOG: clicked search button with selector '%s'", sel)
                        break
                except Exception:
                    continue

            # Paginate and collect results
            page_num = 0
            max_pages = 50
            while page_num < max_pages:
                page_num += 1
                html = await page.content()
                soup = BeautifulSoup(html, "lxml")

                # Try various selectors for result cards
                card_selectors = [
                    "div.doctor-card",
                    "div.result-card",
                    "div.practitioner-card",
                    "mat-card",
                    "div.search-result",
                    "div.card",
                    "tr.result-row",
                ]

                found_cards = False
                for selector in card_selectors:
                    cards = soup.select(selector)
                    if cards:
                        logger.info("RANZCOG page %d: matched '%s' with %d results", page_num, selector, len(cards))
                        for card in cards:
                            name_el = card.select_one("h2, h3, h4, .name, .doctor-name, .practitioner-name, strong")
                            name = name_el.get_text(strip=True) if name_el else ""
                            if not name:
                                continue

                            spec_el = card.select_one(".specialty, .subspecialty, .practice-type")
                            state_el = card.select_one(".state, .location, .suburb, .address")

                            profiles.append({
                                "name_raw": name,
                                "source": "ranzcog",
                                "subspecialty": spec_el.get_text(strip=True) if spec_el else None,
                                "state": state_el.get_text(strip=True) if state_el else None,
                            })
                        found_cards = True
                        break

                if not found_cards and page_num == 1:
                    # Log page snippet for debugging
                    body = soup.find("body")
                    if body:
                        logger.warning("RANZCOG: no result cards found. Body snippet: %s", str(body)[:1000])
                    break

                # Try to find next page button
                next_selectors = [
                    "button:has-text('Next')",
                    "a:has-text('Next')",
                    "button[aria-label='Next page']",
                    ".mat-paginator-navigation-next",
                    "a.next-page",
                ]
                next_found = False
                for sel in next_selectors:
                    next_btn = page.locator(sel).first
                    try:
                        if await next_btn.count() > 0 and await next_btn.is_visible() and await next_btn.is_enabled():
                            await next_btn.click()
                            await page.wait_for_load_state("networkidle", timeout=30000)
                            await asyncio.sleep(random.uniform(1, 2))
                            next_found = True
                            break
                    except Exception:
                        continue

                if not next_found:
                    break

        finally:
            await browser.close()

    if not profiles:
        logger.warning("RANZCOG: no profiles found — page structure may have changed")

    return profiles


async def _scrape_ages(client: httpx.AsyncClient) -> list[dict]:
    """Scrape AGES board members from current and previous board pages.

    The AGES /members page is empty (login-gated). Board pages list names
    as text containing 'Dr', 'Prof', 'A/Prof' prefixes.
    """
    import re

    profiles: list[dict] = []
    name_pattern = re.compile(r"(?:Dr|Prof|A/Prof|Associate Prof(?:essor)?)\s+[\w\s'-]+")

    for url in [AGES_BOARD_URL, AGES_PREV_BOARD_URL]:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception:
            logger.warning("AGES: failed to fetch %s", url, exc_info=True)
            continue

        soup = BeautifulSoup(resp.text, "lxml")

        # Extract names from text nodes — AGES board page lists names in
        # various elements (paragraphs, headings, divs)
        seen: set[str] = set()
        for el in soup.find_all(string=name_pattern):
            text = el.strip()
            for match in name_pattern.finditer(text):
                name = match.group().strip()
                if name not in seen:
                    seen.add(name)
                    profiles.append({
                        "name_raw": name,
                        "source": "ages",
                        "subspecialty": None,
                        "state": None,
                    })

        logger.info("AGES: found %d names from %s", len(seen), url.split("/")[-2])

    if not profiles:
        logger.warning("AGES: no profiles found — page structure may have changed")

    return profiles


async def fetch_college_profiles(session: AsyncSession) -> int:
    stored = 0

    # RANZCOG — Playwright (Angular SPA)
    try:
        ranzcog_profiles = await _scrape_ranzcog_playwright()
        for prof in ranzcog_profiles:
            existing = await session.execute(
                select(CollegeProfile).where(
                    CollegeProfile.name_raw == prof["name_raw"],
                    CollegeProfile.source == "ranzcog",
                )
            )
            if existing.scalar_one_or_none():
                continue

            cp = CollegeProfile(
                name_raw=prof["name_raw"],
                source=prof["source"],
                subspecialty=prof.get("subspecialty"),
                state=prof.get("state"),
            )
            session.add(cp)
            stored += 1
    except Exception:
        logger.warning("College profile scrape failed for ranzcog", exc_info=True)

    # AGES — static HTML with httpx
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            ages_profiles = await _scrape_ages(client)
            for prof in ages_profiles:
                existing = await session.execute(
                    select(CollegeProfile).where(
                        CollegeProfile.name_raw == prof["name_raw"],
                        CollegeProfile.source == "ages",
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                cp = CollegeProfile(
                    name_raw=prof["name_raw"],
                    source=prof["source"],
                    subspecialty=prof.get("subspecialty"),
                    state=prof.get("state"),
                )
                session.add(cp)
                stored += 1
    except Exception:
        logger.warning("College profile scrape failed for ages", exc_info=True)

    await session.commit()
    logger.info("Stored %d college profiles", stored)
    return stored
