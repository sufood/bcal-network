import time

from prefect import flow, task
from prefect.logging import get_run_logger

from gyn_kol.config import settings
from gyn_kol.database import async_session_factory


@task(retries=3, retry_delay_seconds=60)
async def ingest_pubmed() -> int:
    from gyn_kol.ingestion.pubmed import fetch_pubmed_results

    async with async_session_factory() as session:
        return await fetch_pubmed_results(session=session, api_key=settings.ncbi_api_key)


@task(retries=3, retry_delay_seconds=60)
async def enrich_crossref() -> int:
    from gyn_kol.ingestion.crossref import enrich_crossref

    async with async_session_factory() as session:
        return await enrich_crossref(session, settings.crossref_email)


@task(retries=2, retry_delay_seconds=120)
async def ingest_clinical_trials() -> int:
    from gyn_kol.ingestion.clinical_trials import fetch_clinical_trials

    async with async_session_factory() as session:
        return await fetch_clinical_trials(session)


@task(retries=2, retry_delay_seconds=60)
async def ingest_nhmrc() -> int:
    from gyn_kol.ingestion.nhmrc import fetch_nhmrc_grants

    async with async_session_factory() as session:
        return await fetch_nhmrc_grants(session)


@task(retries=2, retry_delay_seconds=60)
async def ingest_colleges() -> int:
    from gyn_kol.ingestion.ranzcog import fetch_college_profiles

    async with async_session_factory() as session:
        return await fetch_college_profiles(session)


@task(retries=2, retry_delay_seconds=60)
async def ingest_hospitals() -> int:
    from gyn_kol.ingestion.hospitals import fetch_hospital_profiles

    async with async_session_factory() as session:
        return await fetch_hospital_profiles(session)


@task(retries=2, retry_delay_seconds=60)
async def ingest_canrefer() -> int:
    from gyn_kol.ingestion.canrefer import fetch_canrefer_profiles

    async with async_session_factory() as session:
        return await fetch_canrefer_profiles(session)


@task(retries=1, retry_delay_seconds=300)
async def ingest_ahpra() -> int:
    from gyn_kol.ingestion.ahpra import fetch_ahpra_registrations

    async with async_session_factory() as session:
        return await fetch_ahpra_registrations(session)


@task
async def verify_registrations() -> dict:
    from gyn_kol.ingestion.verification import verify_canrefer_against_ahpra

    async with async_session_factory() as session:
        return await verify_canrefer_against_ahpra(session)


@task
async def resolve_entities() -> int:
    from gyn_kol.resolution.builder import build_master_records
    from gyn_kol.resolution.matcher import match_across_sources

    async with async_session_factory() as session:
        clusters = await match_across_sources(session)
        return await build_master_records(session, clusters)


@task
async def build_graph() -> int:
    from gyn_kol.graph.builder import build_coauthorship_graph
    from gyn_kol.graph.centrality import compute_and_store_centrality

    async with async_session_factory() as session:
        G = await build_coauthorship_graph(session)
        return await compute_and_store_centrality(session, G)


@task
async def score_influence() -> int:
    from gyn_kol.scoring.influence import score_all_clinicians

    async with async_session_factory() as session:
        return await score_all_clinicians(session)


@task
async def score_early_adopter() -> int:
    from gyn_kol.scoring.early_adopter import score_all_early_adopter

    async with async_session_factory() as session:
        return await score_all_early_adopter(session)


@task
async def assign_tiers() -> int:
    from gyn_kol.scoring.tiers import assign_all_tiers

    async with async_session_factory() as session:
        return await assign_all_tiers(session)


@task(retries=2, retry_delay_seconds=60)
async def ingest_mbs() -> int:
    from gyn_kol.ingestion.mbs import fetch_mbs_items

    async with async_session_factory() as session:
        return await fetch_mbs_items(session)


@task(retries=1, retry_delay_seconds=300)
async def enrich_ahpra_specialty() -> int:
    from gyn_kol.ingestion.ahpra_enrich import enrich_specialty_from_ahpra

    async with async_session_factory() as session:
        return await enrich_specialty_from_ahpra(session, limit=500)


@task
async def link_mbs() -> dict:
    from gyn_kol.ingestion.mbs_linkage import link_mbs_to_clinicians

    async with async_session_factory() as session:
        return await link_mbs_to_clinicians(session)


STEPS = [
    ("PubMed ingest", ingest_pubmed),
    ("CrossRef enrichment", enrich_crossref),
    ("Clinical trials", ingest_clinical_trials),
    ("NHMRC grants", ingest_nhmrc),
    ("College profiles", ingest_colleges),
    ("Hospital profiles", ingest_hospitals),
    ("CanRefer profiles", ingest_canrefer),
    ("AHPRA registrations", ingest_ahpra),
    ("MBS items", ingest_mbs),
    ("Registration verification", verify_registrations),
    ("Entity resolution", resolve_entities),
    ("MBS linkage", link_mbs),
    ("Graph build", build_graph),
    ("Influence scoring", score_influence),
    ("Early adopter scoring", score_early_adopter),
    ("Tier assignment", assign_tiers),
    ("AHPRA specialty enrichment", enrich_ahpra_specialty),
]

RESULT_KEYS = [
    "pubmed", "crossref", "trials", "nhmrc", "colleges",
    "hospitals", "canrefer", "ahpra", "mbs",
    "verification", "resolved", "mbs_linkage",
    "graph", "influence", "early_adopter", "tiers",
    "ahpra_enrich",
]


def _progress_bar(done: int, total: int, width: int = 20) -> str:
    filled = int(width * done / total)
    bar = "#" * filled + "-" * (width - filled)
    pct = int(100 * done / total)
    return f"[{bar}] {pct}%"


@flow(name="Full Ingestion Pipeline")
async def ingestion_flow() -> dict:
    logger = get_run_logger()
    total = len(STEPS)
    logger.info("=== Ingestion pipeline starting (%d steps) ===", total)
    pipeline_t0 = time.monotonic()
    results: dict = {}

    for i, (name, task_fn) in enumerate(STEPS, 1):
        logger.info(
            "%s  [%d/%d] Starting: %s",
            _progress_bar(i - 1, total), i, total, name,
        )
        step_t0 = time.monotonic()
        result = await task_fn()
        elapsed = time.monotonic() - step_t0
        results[RESULT_KEYS[i - 1]] = result
        logger.info(
            "%s  [%d/%d] Finished: %s — result=%s (%.1fs)",
            _progress_bar(i, total), i, total, name, result, elapsed,
        )

    pipeline_elapsed = time.monotonic() - pipeline_t0
    logger.info("=== Ingestion pipeline finished (%.1fs) ===", pipeline_elapsed)
    logger.info("Results: %s", results)
    return results
