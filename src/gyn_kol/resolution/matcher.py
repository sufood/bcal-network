import logging
import uuid

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.ahpra_registration import AhpraRegistration
from gyn_kol.models.canrefer_profile import CanreferProfile
from gyn_kol.models.college_profile import CollegeProfile
from gyn_kol.models.grant import Grant
from gyn_kol.models.paper import Author
from gyn_kol.models.trial import Trial
from gyn_kol.resolution.normalise import normalise_name

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 88


def _names_match(name_a: str, name_b: str) -> bool:
    return fuzz.token_sort_ratio(name_a, name_b) >= MATCH_THRESHOLD


def _state_boost(state_a: str | None, state_b: str | None) -> bool:
    if state_a and state_b:
        return state_a.upper() == state_b.upper()
    return False


async def match_across_sources(session: AsyncSession) -> dict[str, list[dict]]:
    """Match names across all source tables, return clusters keyed by a new clinician_id."""

    # Gather all name records from each source
    all_records: list[dict] = []

    # Authors
    authors = (await session.execute(select(Author))).scalars().all()
    for a in authors:
        all_records.append({
            "source": "pubmed",
            "id": a.author_id,
            "name_raw": a.name_raw,
            "name_norm": normalise_name(a.name_raw),
            "state": a.state,
            "institution": a.affiliation_raw,
            "specialty": None,
        })

    # Trials
    trials = (await session.execute(select(Trial))).scalars().all()
    for t in trials:
        if t.pi_name_raw:
            all_records.append({
                "source": "trials",
                "id": t.trial_id,
                "name_raw": t.pi_name_raw,
                "name_norm": normalise_name(t.pi_name_raw),
                "state": None,
                "institution": t.institution,
                "specialty": None,
            })

    # Grants
    grants = (await session.execute(select(Grant))).scalars().all()
    for g in grants:
        if g.recipient_name_raw:
            all_records.append({
                "source": "nhmrc",
                "id": g.grant_id,
                "name_raw": g.recipient_name_raw,
                "name_norm": normalise_name(g.recipient_name_raw),
                "state": None,
                "institution": g.institution,
                "specialty": None,
            })

    # College profiles — infer specialty from source when subspecialty is missing
    _COLLEGE_DEFAULT_SPECIALTY = {
        "ranzcog": "Obstetrics and Gynaecology",
        "ages": "Gynaecological Surgery",
    }
    profiles = (await session.execute(select(CollegeProfile))).scalars().all()
    for p in profiles:
        specialty = p.subspecialty or _COLLEGE_DEFAULT_SPECIALTY.get(p.source or "")
        all_records.append({
            "source": p.source or "college",
            "id": p.profile_id,
            "name_raw": p.name_raw,
            "name_norm": normalise_name(p.name_raw),
            "state": p.state,
            "institution": None,
            "specialty": specialty,
        })

    # Canrefer profiles
    canrefer = (await session.execute(select(CanreferProfile))).scalars().all()
    for c in canrefer:
        # Extract specialty from job_titles (e.g., ["Gynaecological Oncologist"])
        specialty = None
        if c.job_titles and isinstance(c.job_titles, list) and c.job_titles:
            specialty = c.job_titles[0]
        all_records.append({
            "source": "canrefer",
            "id": c.profile_id,
            "name_raw": c.name_raw,
            "name_norm": c.name_normalised or normalise_name(c.name_raw),
            "state": c.state,
            "institution": (c.hospitals[0]["name"] if c.hospitals else None),
            "specialty": specialty,
        })

    # AHPRA registrations
    ahpra = (await session.execute(select(AhpraRegistration))).scalars().all()
    for a in ahpra:
        all_records.append({
            "source": "ahpra",
            "id": a.registration_id,
            "name_raw": a.name_raw,
            "name_norm": a.name_normalised or normalise_name(a.name_raw),
            "state": a.state,
            "institution": None,
            "specialty": a.specialty,
        })

    logger.info("Matching %d records across sources", len(all_records))

    # Greedy clustering
    clusters: list[list[dict]] = []
    assigned = set()

    for i, rec_a in enumerate(all_records):
        if i in assigned:
            continue

        cluster = [rec_a]
        assigned.add(i)

        for j, rec_b in enumerate(all_records):
            if j in assigned:
                continue
            if _names_match(rec_a["name_norm"], rec_b["name_norm"]):
                cluster.append(rec_b)
                assigned.add(j)

        clusters.append(cluster)

    # Assign clinician IDs
    result: dict[str, list[dict]] = {}
    for cluster in clusters:
        clinician_id = str(uuid.uuid4())
        result[clinician_id] = cluster

    logger.info("Resolved %d unique clinicians from %d records", len(result), len(all_records))
    return result
