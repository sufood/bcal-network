import logging

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician
from gyn_kol.models.clinician_source_link import ClinicianSourceLink
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


async def build_clinician_graph(session: AsyncSession) -> nx.Graph:
    """Build a co-authorship graph at the clinician level (collapsed from authors)."""
    # Step 1: Build author_id -> clinician_id mapping from source links
    link_result = await session.execute(
        select(ClinicianSourceLink).where(ClinicianSourceLink.source == "pubmed")
    )
    author_to_clinician: dict[str, str] = {}
    for link in link_result.scalars().all():
        author_to_clinician[link.source_record_id] = link.clinician_id

    # Step 2: Fetch coauthorships and group by paper
    ca_result = await session.execute(select(Coauthorship))
    papers: dict[str, list[str]] = {}
    for ca in ca_result.scalars().all():
        papers.setdefault(ca.paper_id, []).append(ca.author_id)

    # Step 3: Build clinician-level edges
    G = nx.Graph()
    for _paper_id, author_ids in papers.items():
        # Map to clinician IDs, deduplicate (multiple authors may resolve to same clinician)
        clinician_ids = list({
            author_to_clinician[aid]
            for aid in author_ids
            if aid in author_to_clinician
        })
        for i, c1 in enumerate(clinician_ids):
            G.add_node(c1)
            for c2 in clinician_ids[i + 1 :]:
                if G.has_edge(c1, c2):
                    G[c1][c2]["weight"] += 1
                else:
                    G.add_edge(c1, c2, weight=1)

    # Step 4: Annotate nodes with clinician metadata
    mc_result = await session.execute(select(MasterClinician))
    for c in mc_result.scalars().all():
        if c.clinician_id in G:
            G.nodes[c.clinician_id].update({
                "label": c.name_display or "Unknown",
                "tier": c.tier,
                "state": c.state or "",
                "influence_score": c.influence_score or 0,
                "institution": c.primary_institution or "",
            })

    logger.info("Built clinician graph: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


async def build_ego_graph(
    session: AsyncSession,
    clinician_id: str,
    radius: int = 1,
    max_neighbors: int = 20,
) -> nx.Graph:
    """Extract ego network for a clinician, capped to strongest connections."""
    full_graph = await build_clinician_graph(session)
    if clinician_id not in full_graph:
        return nx.Graph()

    ego = nx.ego_graph(full_graph, clinician_id, radius=radius)

    # Prune to top N neighbors by edge weight (shared papers)
    neighbors = [n for n in ego.nodes if n != clinician_id]
    if len(neighbors) > max_neighbors:
        scored = sorted(
            neighbors,
            key=lambda n: ego[clinician_id].get(n, {}).get("weight", 0),
            reverse=True,
        )
        keep = set(scored[:max_neighbors])
        keep.add(clinician_id)
        ego.remove_nodes_from([n for n in list(ego.nodes) if n not in keep])

    return ego
