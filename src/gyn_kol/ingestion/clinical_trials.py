"""Fetch Australian gynaecology clinical trials from ClinicalTrials.gov API.

ANZCTR is behind Cloudflare JS challenge and cannot be scraped with httpx.
ClinicalTrials.gov cross-lists Australian trials (including ANZCTR-registered
ones) and provides a free, public JSON API.

httpx is blocked by TLS fingerprinting on ClinicalTrials.gov, so we shell
out to curl via asyncio.subprocess.
"""

import asyncio
import json
import logging
import shutil
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from gyn_kol.models.trial import Trial

logger = logging.getLogger(__name__)

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
PAGE_SIZE = 50

GYN_CONDITIONS = [
    "endometriosis",
    "ovarian cancer",
    "uterine fibroids",
    "hysterectomy",
    "laparoscopy gynaecology",
    "hysteroscopy",
    "cervical cancer",
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def _curl_json(url: str) -> dict:
    """Fetch JSON from a URL using curl subprocess (bypasses TLS fingerprinting)."""
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl not found on PATH")

    proc = await asyncio.create_subprocess_exec(
        curl, "-s", "--max-time", "30", url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"curl failed (rc={proc.returncode}): {stderr.decode()}")

    return json.loads(stdout)


async def _search_trials(condition: str) -> list[dict]:
    """Search ClinicalTrials.gov for Australian trials matching a condition."""
    all_studies: list[dict] = []
    page_token: str | None = None

    while True:
        params = {
            "query.cond": condition,
            "query.locn": "Australia",
            "pageSize": str(PAGE_SIZE),
            "countTotal": "true",
        }
        if page_token:
            params["pageToken"] = page_token

        url = f"{CTGOV_API}?{urlencode(params)}"
        data = await _curl_json(url)

        studies = data.get("studies", [])
        if not studies:
            break

        all_studies.extend(studies)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

        await asyncio.sleep(0.5)  # Polite delay between pages

    return all_studies


def _extract_trial(study: dict, condition: str) -> dict:
    """Extract relevant fields from a ClinicalTrials.gov study record."""
    proto = study.get("protocolSection", {})
    ident = proto.get("identificationModule", {})
    status_mod = proto.get("statusModule", {})
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
    contacts_mod = proto.get("contactsLocationsModule", {})
    conditions_mod = proto.get("conditionsModule", {})

    # Extract PI name from responsible party or overall officials
    pi_name = None
    resp_party = sponsor_mod.get("responsibleParty", {})
    if resp_party.get("investigatorFullName"):
        pi_name = resp_party["investigatorFullName"]
    else:
        for official in contacts_mod.get("overallOfficials", []):
            if official.get("role") in ("PRINCIPAL_INVESTIGATOR", "STUDY_DIRECTOR"):
                pi_name = official.get("name")
                break

    # Extract Australian institution from locations
    institution = None
    pi_affiliation = resp_party.get("investigatorAffiliation")
    if pi_affiliation:
        institution = pi_affiliation
    else:
        for loc in contacts_mod.get("locations", []):
            if loc.get("country") == "Australia":
                institution = loc.get("facility")
                break

    return {
        "nct_id": ident.get("nctId"),
        "title": ident.get("briefTitle", ""),
        "pi_name_raw": pi_name,
        "institution": institution,
        "status": status_mod.get("overallStatus"),
        "conditions": conditions_mod.get("conditions", [condition]),
        "raw_payload": study,
    }


async def fetch_clinical_trials(session: AsyncSession) -> int:
    """Fetch Australian gynaecology trials from ClinicalTrials.gov API."""
    stored = 0

    for condition in GYN_CONDITIONS:
        logger.info("ClinicalTrials.gov search: %s (Australia)", condition)
        try:
            studies = await _search_trials(condition)
            logger.info("Found %d trials for %s", len(studies), condition)

            for study in studies:
                trial_data = _extract_trial(study, condition)
                nct_id = trial_data.get("nct_id")
                if not nct_id:
                    continue

                existing = await session.execute(
                    select(Trial).where(Trial.nct_id == nct_id)
                )
                if existing.scalar_one_or_none():
                    continue

                trial = Trial(
                    nct_id=nct_id,
                    title=trial_data["title"],
                    pi_name_raw=trial_data.get("pi_name_raw"),
                    institution=trial_data.get("institution"),
                    status=trial_data.get("status"),
                    conditions=trial_data["conditions"],
                    raw_payload=trial_data.get("raw_payload"),
                )
                session.add(trial)
                stored += 1

        except Exception:
            logger.warning("ClinicalTrials.gov search failed for %s", condition, exc_info=True)

    await session.commit()
    logger.info("Stored %d trials", stored)
    return stored
