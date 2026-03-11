import logging

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician
from gyn_kol.models.trial import Trial

logger = logging.getLogger(__name__)


async def add_institutional_edges(session: AsyncSession, G: nx.Graph) -> int:
    result = await session.execute(select(MasterClinician))
    clinicians = result.scalars().all()

    # Group clinicians by institution
    inst_groups: dict[str, list[str]] = {}
    for c in clinicians:
        if c.primary_institution:
            inst_groups.setdefault(c.primary_institution, []).append(c.clinician_id)

    edges_added = 0
    for _inst, members in inst_groups.items():
        for i, m1 in enumerate(members):
            for m2 in members[i + 1 :]:
                if not G.has_edge(m1, m2):
                    G.add_edge(m1, m2, weight=0.5, edge_type="institution")
                    edges_added += 1

    logger.info("Added %d institutional edges", edges_added)
    return edges_added


async def add_trial_edges(session: AsyncSession, G: nx.Graph) -> int:
    result = await session.execute(select(Trial))
    trials = result.scalars().all()

    # Group by institution to find trial site connections
    site_groups: dict[str, list[str]] = {}
    for t in trials:
        if t.institution and t.pi_name_raw:
            site_groups.setdefault(t.institution, []).append(t.trial_id)

    edges_added = 0
    logger.info("Added %d trial site edges", edges_added)
    return edges_added
