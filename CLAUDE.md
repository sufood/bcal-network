# CLAUDE.md — GYN KOL Identification App

This file provides project context, conventions, and instructions for AI-assisted development of the GYN KOL Identification App.

---

## Project Overview

A multi-module Python application that aggregates public clinician data (publications, trials, grants, college directories, reviews), resolves identities, scores clinicians by influence and early-adopter signals, maps their professional networks, and outputs a prioritised KOL outreach list with an interactive dashboard.

**Primary users:** Medical affairs / commercial teams targeting gynaecologists in Australia.

---

## Repository Structure

```
gyn-kol/
├── CLAUDE.md                  # This file
├── TODO.md                    # Task tracker
├── README.md
├── pyproject.toml             # Project deps (uv or pip)
├── .env.example               # Required env vars (never commit .env)
├── alembic/                   # DB migrations
│   └── versions/
├── docker/
│   ├── Dockerfile
│   └── compose.yml
├── src/
│   └── gyn_kol/
│       ├── __init__.py
│       ├── main.py            # FastAPI app entrypoint
│       ├── config.py          # Settings (Pydantic BaseSettings)
│       ├── database.py        # SQLAlchemy async engine + session
│       ├── models/            # SQLAlchemy ORM models
│       │   ├── clinician.py
│       │   ├── paper.py
│       │   ├── coauthorship.py
│       │   ├── trial.py
│       │   ├── grant.py
│       │   ├── college_profile.py
│       │   ├── institutional_profile.py
│       │   ├── review_signal.py
│       │   └── audit_log.py
│       ├── schemas/           # Pydantic request/response schemas
│       ├── routers/           # FastAPI route handlers
│       │   ├── clinicians.py
│       │   ├── scores.py
│       │   ├── graph.py
│       │   └── exports.py
│       ├── ingestion/         # Module 1 — data harvesters
│       │   ├── pubmed.py
│       │   ├── crossref.py
│       │   ├── semantic_scholar.py
│       │   ├── anzctr.py
│       │   ├── nhmrc.py
│       │   ├── ranzcog.py
│       │   ├── hospitals.py
│       │   └── reviews.py
│       ├── resolution/        # Module 2 — entity matching
│       │   ├── normalise.py
│       │   ├── matcher.py
│       │   └── builder.py
│       ├── scoring/           # Module 3 — scoring engine
│       │   ├── influence.py
│       │   ├── early_adopter.py
│       │   └── tiers.py
│       ├── graph/             # Module 4 — network analysis
│       │   ├── builder.py
│       │   ├── centrality.py
│       │   ├── inference.py
│       │   └── export.py
│       ├── linkedin/          # Module 5 — LinkedIn enrichment
│       │   └── ingestor.py
│       ├── ai/                # Module 6 — Claude API integration
│       │   ├── profiles.py
│       │   └── classifier.py
│       ├── dashboard/         # Module 7 — Streamlit MVP
│       │   └── app.py
│       ├── exports/           # Module 7 — CSV/Excel/CRM output
│       │   ├── excel.py
│       │   └── crm.py
│       └── flows/             # Module 8 — Prefect flows
│           ├── ingestion_flow.py
│           └── rescore_flow.py
└── tests/
    ├── conftest.py
    ├── test_ingestion/
    ├── test_resolution/
    ├── test_scoring/
    └── test_graph/
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| API framework | FastAPI + Uvicorn |
| HTTP client | httpx (async throughout) |
| Scraping | BeautifulSoup4, Scrapy, Playwright (fallback) |
| ORM | SQLAlchemy 2.x async + Alembic |
| Database (dev) | SQLite |
| Database (prod) | PostgreSQL 16 (JSONB, full-text search) |
| Cache | Redis |
| Name matching | rapidfuzz, recordlinkage |
| Graph | NetworkX + pyvis |
| AI / NLP | Anthropic Claude API (`anthropic` SDK) |
| Orchestration | Prefect 3.x |
| Dashboard (MVP) | Streamlit + Plotly |
| Dashboard (prod) | React 18 + Vite + TailwindCSS |
| Export | pandas + openpyxl |
| Code quality | ruff, mypy, pytest + pytest-asyncio |
| Containerisation | Docker + docker-compose |

---

## Environment Variables

All secrets and config live in `.env` (never committed). See `.env.example`.

```
# Database
DATABASE_URL=sqlite+aiosqlite:///./gyn_kol.db          # dev
# DATABASE_URL=postgresql+asyncpg://user:pass@host/db  # prod

# Redis
REDIS_URL=redis://localhost:6379

# External APIs
NCBI_API_KEY=...          # NCBI Entrez — raises rate limit from 3 to 10 req/s
CROSSREF_EMAIL=...        # Polite pool access (required)
GOOGLE_MAPS_API_KEY=...   # Places API for review data

# AI
ANTHROPIC_API_KEY=...

# Prefect
PREFECT_API_KEY=...        # Only needed for Prefect Cloud
```

---

## AI Model Usage

Use the right model for the right job — cost matters at scale:

- **Profile synthesis (Module 6.1):** `claude-opus-4-6` — quality-critical, one-off per clinician
- **Bulk review classification (Module 6.2):** `claude-haiku-4-5-20251001` — high-volume, cost-sensitive

Always call the Anthropic API via the `anthropic` Python SDK, not raw `httpx`. Use async client (`AsyncAnthropic`) to keep ingestion pipelines non-blocking.

Prompts live in `src/gyn_kol/ai/` as Python constants or Jinja2 templates — **never inline prompts in business logic**.

---

## Database Conventions

- All primary keys are UUIDs (use `uuid.uuid4()`), never integer sequences
- `clinician_id` is the canonical foreign key across all tables
- Raw API responses stored as JSONB (`raw_payload` column) alongside parsed columns
- Table naming: `snake_case`, plural (e.g., `master_clinicians`, `review_signals`)
- All tables have `created_at` and `updated_at` timestamps (auto-managed)
- Separate `raw_*` tables from resolved/enriched tables — never overwrite raw data
- Alembic manages all schema changes — never modify tables manually in prod

---

## Async Patterns

This codebase is async-first. Follow these conventions:

- All DB access via `async with AsyncSession` — never use sync SQLAlchemy sessions
- All HTTP calls via `httpx.AsyncClient` — never `requests`
- Ingestion modules should implement rate limiting via `asyncio.Semaphore` and `tenacity` retry decorators
- Prefect tasks wrapping async functions: use `asyncio.run()` at the flow level only

---

## API Rate Limit Handling

Each data source has different limits — respect them:

| Source | Limit | Strategy |
|---|---|---|
| NCBI Entrez | 10 req/s (with API key) | `asyncio.Semaphore(8)` + `tenacity` |
| CrossRef | Polite pool, ~50 req/s | Include `mailto` header |
| Semantic Scholar | 100 req/5min (unauthenticated) | Semaphore + exponential backoff |
| Google Maps Places | Quota-based | Cache responses in Redis |
| ANZCTR | No formal limit — be polite | 1 req/s, `asyncio.sleep` |

---

## Scoring System Reference

### Influence Score (0–100)
| Dimension | Weight |
|---|---|
| Research Output | 30% |
| Clinical Leadership | 25% |
| Network Centrality | 20% |
| Digital Presence | 15% |
| Peer Nomination | 10% |

### Early Adopter Score (0–10)
Rule-based flag system — see `scoring/early_adopter.py`.

### Tier Thresholds
- Tier 1: 75–100
- Tier 2: 50–74
- Tier 3: 25–49
- Tier 4: High-centrality outlier (override, any score)

---

## Code Quality

Run before every commit:

```bash
ruff check . --fix       # lint + format
mypy src/                # type check
pytest tests/ -v         # full test suite
```

Pre-commit hooks should enforce these. Set up with:

```bash
pre-commit install
```

---

## Testing Conventions

- Unit tests for all scoring functions — scores must be deterministic given fixed inputs
- Use `pytest-asyncio` with `asyncio_mode = "auto"` in `pyproject.toml`
- Mock all external HTTP calls in tests — never hit live APIs in CI
- Use `pytest-httpx` for mocking `httpx` requests
- Fixtures for DB: use SQLite in-memory (`sqlite+aiosqlite:///:memory:`) for test isolation
- AI calls: mock Anthropic responses — never call the live API in tests

---

## Module Build Order

Build in this sequence (each module depends on the previous):

1. DB schema + FastAPI scaffold
2. Ingestion modules 1.1 → 1.7
3. Entity resolution (Module 2)
4. Scoring engine (Module 3) — network centrality dimension stubbed initially
5. Network graph (Module 4) — feed centrality back into scoring
6. AI profile synthesis (Module 6)
7. Dashboard + exports (Module 7)
8. LinkedIn enrichment (Module 5) — semi-manual, slot in during enrichment phase
9. Monitoring + scheduling (Module 8)

---

## Common Gotchas

- **Name matching is hard.** Australian clinicians often publish under different name formats (initials vs full first name, hyphenated surnames). Always normalise before matching; store the canonical form separately from display name.
- **RANZCOG scraping is fragile.** The directory structure changes. Add robust CSS selector fallbacks and log when extraction yields zero results.
- **PubMed affiliation parsing.** Australian affiliations are inconsistent strings — use keyword matching (`Australia`, state abbreviations, known institution names) rather than assuming structure.
- **Google Maps reviews.** Require a valid `place_id` per clinic. The mapping from clinician → clinic → place_id is a semi-manual enrichment step.
- **Playwright pages.** Only use Playwright as a last resort (slow, resource-heavy). Flag pages that require it so they can be reviewed for a more stable extraction approach.
