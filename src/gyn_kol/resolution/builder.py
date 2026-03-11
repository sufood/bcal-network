import logging
from collections import Counter

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician
from gyn_kol.resolution.normalise import normalise_name

logger = logging.getLogger(__name__)


async def build_master_records(
    session: AsyncSession, clusters: dict[str, list[dict]]
) -> int:
    # Clear old master records — they are fully derived from raw source data
    result = await session.execute(delete(MasterClinician))
    logger.info("Cleared %d old master clinician records", result.rowcount)

    built = 0

    for clinician_id, records in clusters.items():
        # Pick most common name as display name
        name_counts: Counter[str] = Counter()
        for r in records:
            name_counts[r["name_raw"]] += 1
        display_name = name_counts.most_common(1)[0][0]

        # Collect sources
        sources = list({r["source"] for r in records})

        # Pick best state (most common non-None)
        states = [r["state"] for r in records if r.get("state")]
        state = Counter(states).most_common(1)[0][0] if states else None

        # Pick best institution
        institutions = [r["institution"] for r in records if r.get("institution")]
        institution = Counter(institutions).most_common(1)[0][0] if institutions else None

        # Pick best specialty (most common non-None)
        specialties = [r["specialty"] for r in records if r.get("specialty")]
        specialty = Counter(specialties).most_common(1)[0][0] if specialties else None

        # Count signals
        source_counter = Counter(r["source"] for r in records)

        clinician = MasterClinician(
            clinician_id=clinician_id,
            name_display=display_name,
            name_normalised=normalise_name(display_name),
            primary_institution=institution,
            state=state,
            specialty=specialty,
            source_flags=sources,
            pub_count=source_counter.get("pubmed", 0),
            trial_count=source_counter.get("trials", 0),
            grant_count=source_counter.get("nhmrc", 0),
        )
        session.add(clinician)
        built += 1

    await session.commit()
    logger.info("Built %d master clinician records", built)
    return built
