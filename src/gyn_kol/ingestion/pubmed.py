import asyncio
import logging
from typing import Any

import httpx
import xmltodict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from gyn_kol.models.coauthorship import Coauthorship
from gyn_kol.models.paper import Author, Paper

logger = logging.getLogger(__name__)

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

MESH_QUERIES = [
    "gynaecology",
    "laparoscopy",
    "endometriosis",
    "hysteroscopy",
    "hysterectomy",
    "ovarian cancer",
    "fibroids",
]

_semaphore = asyncio.Semaphore(8)


def _build_search_query(mesh_term: str, years: int = 5) -> str:
    return f'({mesh_term}[MeSH Terms]) AND (Australia[Affiliation]) AND ("last {years} years"[PDat])'


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30))
async def _esearch(
    client: httpx.AsyncClient, query: str, max_results: int, api_key: str
) -> list[str]:
    async with _semaphore:
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "usehistory": "n",
        }
        if api_key:
            params["api_key"] = api_key

        resp = await client.get(f"{NCBI_BASE}/esearch.fcgi", params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("esearchresult", {}).get("idlist", [])


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30))
async def _efetch(
    client: httpx.AsyncClient, pmids: list[str], api_key: str
) -> list[dict[str, Any]]:
    async with _semaphore:
        params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        if api_key:
            params["api_key"] = api_key

        resp = await client.get(f"{NCBI_BASE}/efetch.fcgi", params=params)
        resp.raise_for_status()
        parsed = xmltodict.parse(resp.text)

        articles_raw = parsed.get("PubmedArticleSet", {}).get("PubmedArticle", [])
        if isinstance(articles_raw, dict):
            articles_raw = [articles_raw]
        return articles_raw


def _parse_article(article: dict[str, Any]) -> dict[str, Any]:
    medline = article.get("MedlineCitation", {})
    pmid = medline.get("PMID", {})
    if isinstance(pmid, dict):
        pmid = pmid.get("#text", "")

    art = medline.get("Article", {})
    title = art.get("ArticleTitle", "")
    if isinstance(title, dict):
        title = title.get("#text", "")

    journal_info = art.get("Journal", {})
    journal = journal_info.get("Title", "")

    pub_date_raw = journal_info.get("JournalIssue", {}).get("PubDate", {})
    year = pub_date_raw.get("Year", "")
    month = pub_date_raw.get("Month", "")
    pub_date = f"{year}-{month}" if month else str(year)

    # DOI
    doi = None
    article_ids = art.get("ELocationID", [])
    if isinstance(article_ids, dict):
        article_ids = [article_ids]
    for eid in article_ids:
        if isinstance(eid, dict) and eid.get("@EIdType") == "doi":
            doi = eid.get("#text", "")

    # Authors
    author_list_raw = art.get("AuthorList", {}).get("Author", [])
    if isinstance(author_list_raw, dict):
        author_list_raw = [author_list_raw]

    authors = []
    for i, auth in enumerate(author_list_raw):
        last = auth.get("LastName", "")
        fore = auth.get("ForeName", "")
        name = f"{fore} {last}".strip()
        if not name:
            continue

        aff_info = auth.get("AffiliationInfo", {})
        if isinstance(aff_info, list):
            aff = "; ".join(a.get("Affiliation", "") for a in aff_info if isinstance(a, dict))
        elif isinstance(aff_info, dict):
            aff = aff_info.get("Affiliation", "")
        else:
            aff = ""

        authors.append({"name": name, "affiliation": aff, "position": i})

    return {
        "pmid": str(pmid),
        "doi": doi,
        "title": str(title),
        "journal": str(journal),
        "pub_date": pub_date,
        "authors": authors,
        "raw": article,
    }


def _extract_state(affiliation: str) -> str | None:
    aff_lower = affiliation.lower()
    state_map = {
        "new south wales": "NSW",
        "nsw": "NSW",
        "sydney": "NSW",
        "victoria": "VIC",
        "melbourne": "VIC",
        "queensland": "QLD",
        "brisbane": "QLD",
        "western australia": "WA",
        "perth": "WA",
        "south australia": "SA",
        "adelaide": "SA",
        "tasmania": "TAS",
        "hobart": "TAS",
        "northern territory": "NT",
        "darwin": "NT",
        "act": "ACT",
        "canberra": "ACT",
    }
    for keyword, state in state_map.items():
        if keyword in aff_lower:
            return state
    return None


async def _store_article(session: AsyncSession, parsed: dict[str, Any]) -> None:
    # Check if paper already exists
    existing = await session.execute(select(Paper).where(Paper.pmid == parsed["pmid"]))
    if existing.scalar_one_or_none():
        return

    paper = Paper(
        pmid=parsed["pmid"],
        doi=parsed["doi"],
        title=parsed["title"],
        journal=parsed["journal"],
        pub_date=parsed["pub_date"],
        raw_payload=parsed["raw"],
    )
    session.add(paper)
    await session.flush()

    for auth_data in parsed["authors"]:
        # Check for existing author by name (simple dedup within PubMed)
        name_lower = auth_data["name"].lower().strip()
        existing_author = await session.execute(
            select(Author).where(Author.name_normalised == name_lower)
        )
        author = existing_author.scalar_one_or_none()

        if not author:
            author = Author(
                name_raw=auth_data["name"],
                name_normalised=name_lower,
                affiliation_raw=auth_data["affiliation"],
                state=_extract_state(auth_data["affiliation"]),
            )
            session.add(author)
            await session.flush()

        coauth = Coauthorship(
            author_id=author.author_id,
            paper_id=paper.paper_id,
            author_position=auth_data["position"],
        )
        session.add(coauth)

    await session.flush()


async def fetch_pubmed_results(
    session: AsyncSession,
    query: str | None = None,
    max_results: int = 500,
    api_key: str = "",
) -> int:
    stored = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        queries = [_build_search_query(q) for q in MESH_QUERIES] if query is None else [query]

        for q in queries:
            logger.info("PubMed search: %s", q)
            pmids = await _esearch(client, q, max_results, api_key)
            logger.info("Found %d PMIDs", len(pmids))

            # Fetch in batches of 100
            for i in range(0, len(pmids), 100):
                batch = pmids[i : i + 100]
                articles = await _efetch(client, batch, api_key)
                for article in articles:
                    parsed = _parse_article(article)
                    await _store_article(session, parsed)
                    stored += 1

        await session.commit()

    logger.info("Stored %d articles total", stored)
    return stored
