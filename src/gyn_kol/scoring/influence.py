import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician

logger = logging.getLogger(__name__)


def score_research_output(clinician: MasterClinician, cohort_max_pubs: int, cohort_max_trials: int) -> float:
    """Research Output dimension: 0–30 points."""
    pub_score = 0.0
    if cohort_max_pubs > 0 and clinician.pub_count:
        pub_score = (clinician.pub_count / cohort_max_pubs) * 15

    h_score = 0.0
    if clinician.h_index_proxy:
        h_score = min(clinician.h_index_proxy / 30.0, 1.0) * 10

    trial_score = 0.0
    if cohort_max_trials > 0 and clinician.trial_count:
        trial_score = (clinician.trial_count / cohort_max_trials) * 5

    return min(pub_score + h_score + trial_score, 30.0)


def score_clinical_leadership(clinician: MasterClinician) -> float:
    """Clinical Leadership dimension: 0–25 points."""
    score = 0.0
    flags = clinician.source_flags or []

    if "ranzcog" in flags:
        score += 10
    if "ages" in flags:
        score += 8

    # Grant funding indicates clinical research leadership
    if clinician.grant_count and clinician.grant_count > 0:
        score += min(clinician.grant_count * 2, 7)

    return min(score, 25.0)


def score_network_centrality(clinician: MasterClinician) -> float:
    """Network Centrality dimension: 0–20 points. Uses graph centrality when available."""
    if clinician.betweenness_centrality is None:
        return 0.0

    bc_score = min(clinician.betweenness_centrality * 50, 10.0)
    dc_score = 0.0
    if clinician.degree_centrality is not None:
        dc_score = min(clinician.degree_centrality * 20, 10.0)

    return min(bc_score + dc_score, 20.0)


def score_digital_presence(clinician: MasterClinician) -> float:
    """Digital Presence dimension: 0–15 points."""
    score = 0.0
    flags = clinician.source_flags or []

    if clinician.review_count and clinician.review_count > 0:
        score += min(clinician.review_count / 50.0 * 8, 8.0)

    # Presence in institutional pages suggests digital visibility
    if "hospital" in flags or "university" in flags:
        score += 4

    if "linkedin" in flags:
        score += 3

    return min(score, 15.0)


def score_peer_nomination(clinician: MasterClinician) -> float:
    """Peer Nomination dimension: 0–10 points. Populated via manual override."""
    return 0.0


def calculate_influence_score(clinician: MasterClinician, cohort_max_pubs: int, cohort_max_trials: int) -> float:
    """Composite influence score: 0–100."""
    research = score_research_output(clinician, cohort_max_pubs, cohort_max_trials)
    leadership = score_clinical_leadership(clinician)
    centrality = score_network_centrality(clinician)
    digital = score_digital_presence(clinician)
    peer = score_peer_nomination(clinician)

    return round(research + leadership + centrality + digital + peer, 2)


async def score_all_clinicians(session: AsyncSession) -> int:
    result = await session.execute(select(MasterClinician))
    clinicians = result.scalars().all()

    if not clinicians:
        return 0

    cohort_max_pubs = max((c.pub_count or 0) for c in clinicians)
    cohort_max_trials = max((c.trial_count or 0) for c in clinicians)

    scored = 0
    for c in clinicians:
        c.influence_score = calculate_influence_score(c, cohort_max_pubs, cohort_max_trials)
        scored += 1

    await session.commit()
    logger.info("Scored %d clinicians for influence", scored)
    return scored
