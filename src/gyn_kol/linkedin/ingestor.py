import logging

import pandas as pd
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician
from gyn_kol.resolution.normalise import normalise_name

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 85


def parse_sales_navigator_csv(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath)

    # Normalise column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Expected columns: first_name, last_name, company, title, location, etc.
    if "first_name" in df.columns and "last_name" in df.columns:
        df["full_name"] = df["first_name"].fillna("") + " " + df["last_name"].fillna("")
    elif "name" in df.columns:
        df["full_name"] = df["name"]
    else:
        raise ValueError("CSV must contain 'first_name'/'last_name' or 'name' columns")

    df["name_normalised"] = df["full_name"].apply(normalise_name)
    return df


async def match_linkedin_leads(session: AsyncSession, df: pd.DataFrame) -> int:
    result = await session.execute(select(MasterClinician))
    clinicians = result.scalars().all()

    matched = 0
    for _, row in df.iterrows():
        lead_name = row.get("name_normalised", "")
        if not lead_name:
            continue

        best_match = None
        best_score = 0.0

        for c in clinicians:
            if not c.name_normalised:
                continue
            score = fuzz.token_sort_ratio(lead_name, c.name_normalised)
            if score > best_score:
                best_score = score
                best_match = c

        if best_match and best_score >= MATCH_THRESHOLD:
            flags = best_match.source_flags or []
            if "linkedin" not in flags:
                flags.append("linkedin")
                best_match.source_flags = flags
            matched += 1

    await session.commit()
    logger.info("Matched %d LinkedIn leads to clinicians", matched)
    return matched
