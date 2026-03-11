import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician

logger = logging.getLogger(__name__)


def assign_tier(
    influence_score: float | None,
    early_adopter_score: float | None,
    betweenness_centrality: float | None,
) -> int:
    score = influence_score or 0.0

    # Tier 4 override: high centrality outlier regardless of score
    if betweenness_centrality is not None and betweenness_centrality > 0.15:
        return 4

    if score >= 75:
        return 1
    if score >= 50:
        return 2
    if score >= 25:
        return 3

    return 3  # Default to Tier 3 for very low scores


async def assign_all_tiers(session: AsyncSession) -> int:
    result = await session.execute(select(MasterClinician))
    clinicians = result.scalars().all()

    assigned = 0
    for c in clinicians:
        c.tier = assign_tier(c.influence_score, c.early_adopter_score, c.betweenness_centrality)
        assigned += 1

    await session.commit()
    logger.info("Assigned tiers to %d clinicians", assigned)
    return assigned
