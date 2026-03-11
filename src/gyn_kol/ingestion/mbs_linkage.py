"""Link MBS items to clinicians based on AHPRA specialty rules.

Items 35723/35724 (para-aortic lymph node dissection) are linked to any
clinician with a gynaecology-related AHPRA specialty.

Item 104 (initial specialist consultation) is generic to all specialists
and is linked ONLY to confirmed AHPRA-registered gynaecologists.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician
from gyn_kol.models.clinician_mbs import ClinicianMbs
from gyn_kol.models.mbs_item import MbsItem

logger = logging.getLogger(__name__)

# Substrings that indicate a gynaecology-related specialty in AHPRA data
# or MasterClinician.specialty (which is populated from AHPRA specialty
# and CollegeProfile subspecialty via the entity resolution pipeline).
GYN_KEYWORDS = [
    "obstetrics",
    "gynaecol",
    "gynecol",
    "gynae",
    "o&g",
    "o & g",
]

# Item numbers for surgical procedures — inherently GYN-relevant
GYN_PROCEDURE_ITEMS = {"35723", "35724"}

# Item numbers that are generic to all specialists — only relevant when
# the provider is a confirmed gynaecologist
SPECIALIST_CONSULTATION_ITEMS = {"104"}


def _is_gynaecologist(specialty: str | None) -> bool:
    """Check whether a specialty string indicates gynaecology."""
    if not specialty:
        return False
    lower = specialty.lower()
    return any(kw in lower for kw in GYN_KEYWORDS)


async def link_mbs_to_clinicians(session: AsyncSession) -> dict[str, int]:
    """Create clinician–MBS mappings based on specialty match rules.

    Returns dict with counts:
        total_mappings, procedure_links, consultation_links, clinicians_linked
    """
    # Load all stored MBS items
    mbs_items = (await session.execute(select(MbsItem))).scalars().all()
    if not mbs_items:
        logger.warning("No MBS items in database — run MBS ingestion first")
        return {
            "total_mappings": 0,
            "procedure_links": 0,
            "consultation_links": 0,
            "clinicians_linked": 0,
        }

    item_by_number: dict[str, MbsItem] = {i.item_number: i for i in mbs_items}

    # Load all master clinicians
    clinicians = (await session.execute(select(MasterClinician))).scalars().all()
    logger.info("Linking MBS items to %d clinicians", len(clinicians))

    procedure_links = 0
    consultation_links = 0
    linked_clinician_ids: set[str] = set()

    for clinician in clinicians:
        if not _is_gynaecologist(clinician.specialty):
            continue

        for item_number, mbs_item in item_by_number.items():
            # Decide whether to link based on item type
            if item_number in GYN_PROCEDURE_ITEMS:
                basis = (
                    f"Specialty: {clinician.specialty}; "
                    f"item {item_number} is para-aortic lymph node dissection "
                    f"for gynaecological malignancy staging"
                )
            elif item_number in SPECIALIST_CONSULTATION_ITEMS:
                basis = (
                    f"Specialty: {clinician.specialty}; "
                    f"item {item_number} is generic specialist consultation, "
                    f"linked because provider is a confirmed gynaecologist"
                )
            else:
                # Unknown item type — still link if clinician is GYN
                basis = f"Specialty: {clinician.specialty}"

            # Dedup: check for existing mapping
            existing = await session.execute(
                select(ClinicianMbs).where(
                    ClinicianMbs.clinician_id == clinician.clinician_id,
                    ClinicianMbs.mbs_item_id == mbs_item.mbs_item_id,
                )
            )
            if existing.scalar_one_or_none():
                continue

            mapping = ClinicianMbs(
                clinician_id=clinician.clinician_id,
                mbs_item_id=mbs_item.mbs_item_id,
                relevance_basis=basis,
                link_method="specialty_match",
            )
            session.add(mapping)
            linked_clinician_ids.add(clinician.clinician_id)

            if item_number in GYN_PROCEDURE_ITEMS:
                procedure_links += 1
            elif item_number in SPECIALIST_CONSULTATION_ITEMS:
                consultation_links += 1

    await session.commit()

    total = procedure_links + consultation_links
    result = {
        "total_mappings": total,
        "procedure_links": procedure_links,
        "consultation_links": consultation_links,
        "clinicians_linked": len(linked_clinician_ids),
    }
    logger.info("MBS linkage complete: %s", result)
    return result
