import logging

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician

logger = logging.getLogger(__name__)


async def compute_and_store_centrality(session: AsyncSession, G: nx.Graph) -> int:
    if G.number_of_nodes() == 0:
        return 0

    degree = nx.degree_centrality(G)
    betweenness = nx.betweenness_centrality(G)
    clustering = nx.clustering(G)

    # Map author_id → clinician records and update
    result = await session.execute(select(MasterClinician))
    clinicians = result.scalars().all()

    updated = 0
    for c in clinicians:
        # Clinician ID might not directly map to author_id
        # For now, check if any node in the graph matches
        cid = c.clinician_id
        if cid in degree:
            c.degree_centrality = round(degree[cid], 6)
            c.betweenness_centrality = round(betweenness[cid], 6)
            c.clustering_coefficient = round(clustering[cid], 6)
            updated += 1

    await session.commit()
    logger.info("Updated centrality for %d clinicians", updated)
    return updated
