import logging

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.coauthorship import Coauthorship

logger = logging.getLogger(__name__)


async def build_coauthorship_graph(session: AsyncSession) -> nx.Graph:
    result = await session.execute(select(Coauthorship))
    coauthorships = result.scalars().all()

    # Group by paper to find co-author pairs
    papers: dict[str, list[str]] = {}
    for ca in coauthorships:
        papers.setdefault(ca.paper_id, []).append(ca.author_id)

    G = nx.Graph()
    for _paper_id, author_ids in papers.items():
        for i, a1 in enumerate(author_ids):
            G.add_node(a1)
            for a2 in author_ids[i + 1 :]:
                if G.has_edge(a1, a2):
                    G[a1][a2]["weight"] += 1
                else:
                    G.add_edge(a1, a2, weight=1)

    logger.info("Built co-authorship graph: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G
