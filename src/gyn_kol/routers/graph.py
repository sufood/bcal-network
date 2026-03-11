import networkx as nx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.database import get_session
from gyn_kol.graph.builder import build_clinician_graph, build_coauthorship_graph, build_ego_graph
from gyn_kol.graph.export import export_json

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("")
async def get_graph(session: AsyncSession = Depends(get_session)) -> dict:
    G = await build_coauthorship_graph(session)
    return export_json(G)


@router.get("/clinician-graph")
async def get_clinician_graph(
    tier: int | None = None,
    state: str | None = None,
    min_weight: int = Query(1, ge=1),
    max_nodes: int = Query(200, ge=10, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the clinician-level co-authorship graph, optionally filtered."""
    G = await build_clinician_graph(session)

    # Filter by tier/state
    if tier is not None:
        remove = [n for n, d in G.nodes(data=True) if d.get("tier") != tier]
        G.remove_nodes_from(remove)
    if state:
        remove = [n for n, d in G.nodes(data=True) if d.get("state") != state]
        G.remove_nodes_from(remove)

    # Filter weak edges
    if min_weight > 1:
        weak = [(u, v) for u, v, d in G.edges(data=True) if d.get("weight", 1) < min_weight]
        G.remove_edges_from(weak)
        G.remove_nodes_from(list(nx.isolates(G)))

    # Cap node count by influence score
    if G.number_of_nodes() > max_nodes:
        scored = sorted(
            G.nodes(data=True),
            key=lambda x: x[1].get("influence_score", 0) or 0,
            reverse=True,
        )
        keep = {n for n, _ in scored[:max_nodes]}
        G.remove_nodes_from([n for n in list(G.nodes) if n not in keep])

    return export_json(G)


@router.get("/clinician-graph/{clinician_id}/ego")
async def get_ego_graph(
    clinician_id: str,
    radius: int = Query(1, ge=1, le=2),
    max_neighbors: int = Query(20, ge=5, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the ego network for a specific clinician."""
    ego = await build_ego_graph(session, clinician_id, radius=radius, max_neighbors=max_neighbors)
    if ego.number_of_nodes() == 0:
        raise HTTPException(status_code=404, detail="Clinician not found in graph")
    return export_json(ego)
