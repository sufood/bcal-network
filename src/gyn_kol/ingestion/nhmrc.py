"""Fetch NHMRC grant outcomes from published XLSX files.

NHMRC publishes grant outcome summaries as XLSX files at stable URLs.
httpx is blocked by TLS fingerprinting, so we use curl subprocess.
"""

import asyncio
import contextlib
import logging
import shutil
import tempfile
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from gyn_kol.models.grant import Grant

logger = logging.getLogger(__name__)

# NHMRC publishes per-year XLSX outcome summaries — fetch recent years
NHMRC_GRANTS_URLS = [
    "https://www.nhmrc.gov.au/sites/default/files/documents/attachments/grant%20documents/Summary-of-result-2025-app-round-22122025.xlsx",
    "https://www.nhmrc.gov.au/sites/default/files/documents/attachments/grant%20documents/Summary-of-result-2024-app-round-100725.xlsx",
    "https://www.nhmrc.gov.au/sites/default/files/documents/attachments/grant%20documents/Summary-of-result-2023-app-round-15122023.xlsx",
]

GYN_KEYWORDS = [
    "gynaecol",
    "gynecol",
    "obstetric",
    "endometriosis",
    "ovarian",
    "uterine",
    "cervical",
    "laparoscop",
    "hysterectomy",
    "reproductive",
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def _download_file(url: str, dest: Path) -> None:
    """Download a file using curl subprocess."""
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl not found on PATH")

    proc = await asyncio.create_subprocess_exec(
        curl, "-sL", "--max-time", "60", "-o", str(dest), url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"curl failed (rc={proc.returncode}): {stderr.decode()}")

    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"Downloaded file is empty: {url}")


def _filter_gyn_grants(df: pd.DataFrame) -> pd.DataFrame:
    text_cols = [c for c in df.columns if df[c].dtype == "object"]
    if not text_cols:
        return df.head(0)

    combined = df[text_cols].fillna("").apply(lambda row: " ".join(str(v) for v in row).lower(), axis=1)
    mask = combined.apply(lambda text: any(kw in text for kw in GYN_KEYWORDS))
    return df[mask]


async def fetch_nhmrc_grants(session: AsyncSession) -> int:
    stored = 0

    for url in NHMRC_GRANTS_URLS:
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            await _download_file(url, tmp_path)
            logger.info("Downloaded NHMRC grants file: %s", url.split("/")[-1])

            # Read all sheets — NHMRC files sometimes have multiple tabs
            try:
                all_sheets = pd.read_excel(tmp_path, sheet_name=None, engine="openpyxl")
            except Exception:
                logger.warning("Failed to read XLSX: %s", url, exc_info=True)
                continue
            finally:
                tmp_path.unlink(missing_ok=True)

            for sheet_name, df in all_sheets.items():
                if df.empty:
                    continue
                logger.info("Processing sheet '%s': %d rows", sheet_name, len(df))

                gyn_df = _filter_gyn_grants(df)
                if gyn_df.empty:
                    continue
                logger.info("Filtered to %d GYN-related grants in '%s'", len(gyn_df), sheet_name)

                # Column name detection — NHMRC XLSX files vary in naming
                name_col = next((c for c in df.columns if any(k in str(c).lower() for k in ("investigator", "cia name", "chief investigator"))), None)
                inst_col = next((c for c in df.columns if any(k in str(c).lower() for k in ("institution", "organisation", "admin institution"))), None)
                amount_col = next((c for c in df.columns if any(k in str(c).lower() for k in ("amount", "budget", "total"))), None)
                year_col = next((c for c in df.columns if "year" in str(c).lower()), None)
                id_col = next((c for c in df.columns if any(k in str(c).lower() for k in ("app id", "grant id", "application id", "id"))), None)
                title_col = next((c for c in df.columns if "title" in str(c).lower()), None)

                for _, row in gyn_df.iterrows():
                    nhmrc_id = str(row[id_col]).strip() if id_col and pd.notna(row.get(id_col)) else None
                    if nhmrc_id:
                        existing = await session.execute(select(Grant).where(Grant.nhmrc_id == nhmrc_id))
                        if existing.scalar_one_or_none():
                            continue

                    amount_val = None
                    if amount_col:
                        with contextlib.suppress(ValueError, TypeError):
                            amount_val = int(float(str(row[amount_col]).replace(",", "").replace("$", "")))

                    year_val = None
                    if year_col:
                        with contextlib.suppress(ValueError, TypeError):
                            year_val = int(row[year_col])

                    keywords_list = []
                    if title_col:
                        title_text = str(row[title_col]).lower()
                        keywords_list = [kw for kw in GYN_KEYWORDS if kw in title_text]

                    grant = Grant(
                        nhmrc_id=nhmrc_id,
                        recipient_name_raw=str(row[name_col]).strip() if name_col and pd.notna(row.get(name_col)) else None,
                        institution=str(row[inst_col]).strip() if inst_col and pd.notna(row.get(inst_col)) else None,
                        amount=amount_val,
                        year=year_val,
                        keywords=keywords_list or None,
                    )
                    session.add(grant)
                    stored += 1

        except Exception:
            logger.warning("NHMRC grants ingestion failed for %s", url, exc_info=True)

    await session.commit()
    logger.info("Stored %d NHMRC grants", stored)
    return stored
