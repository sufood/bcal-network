import logging

from prefect import flow, task

from gyn_kol.database import async_session_factory

logger = logging.getLogger(__name__)


@task
async def recalculate_influence() -> int:
    from gyn_kol.scoring.influence import score_all_clinicians

    async with async_session_factory() as session:
        return await score_all_clinicians(session)


@task
async def recalculate_early_adopter() -> int:
    from gyn_kol.scoring.early_adopter import score_all_early_adopter

    async with async_session_factory() as session:
        return await score_all_early_adopter(session)


@task
async def recalculate_tiers() -> int:
    from gyn_kol.scoring.tiers import assign_all_tiers

    async with async_session_factory() as session:
        return await assign_all_tiers(session)


@task
async def rebuild_graph() -> int:
    from gyn_kol.graph.builder import build_clinician_graph
    from gyn_kol.graph.centrality import compute_and_store_centrality

    async with async_session_factory() as session:
        G = await build_clinician_graph(session)
        return await compute_and_store_centrality(session, G)


@flow(name="Rescore Pipeline")
async def rescore_flow() -> dict:
    graph_count = await rebuild_graph()
    influence_count = await recalculate_influence()
    ea_count = await recalculate_early_adopter()
    tier_count = await recalculate_tiers()

    return {
        "graph_updated": graph_count,
        "influence_scored": influence_count,
        "early_adopter_scored": ea_count,
        "tiers_assigned": tier_count,
    }
