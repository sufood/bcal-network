# GYN KOL Identification App

Aggregate public clinician data, resolve identities, score by influence and early-adopter signals, map professional networks, and output a prioritised KOL outreach list with an interactive dashboard.

## How It Works

The application runs a multi-stage pipeline to identify and rank Key Opinion Leaders (KOLs) in gynaecological oncology across Australia.

**1. Data Ingestion** — Harvests clinician data from multiple public sources:
- **PubMed / CrossRef / Semantic Scholar** — Research publications and citation metrics
- **ANZCTR** — Australian/NZ clinical trial registrations
- **NHMRC** — National grant funding records
- **RANZCOG** — Royal Australian and NZ College of Obstetricians and Gynaecologists directory
- **Canrefer** — Cancer Institute NSW specialist referral directory
- **AHPRA** — Australian Health Practitioner Regulation Agency register (Playwright-based, extracts specialty/registration data from div-based DOM)
- **MBS** — Medicare Benefits Schedule item definitions (XML from mbsonline.gov.au). Tracks gynaecology-relevant items (35723, 35724, 104) and cross-references them with clinicians by AHPRA specialty. Practitioner-level claims data is not publicly available (restricted under Health Insurance Act s130).
- **Google Maps** — Clinic review signals
- **LinkedIn** — Sales Navigator CSV import (semi-manual)

**2. Entity Resolution** — Matches records across sources into a single `MasterClinician` identity per person using fuzzy name matching (rapidfuzz), name normalisation, and state/institution co-occurrence. Populates subspecialty from AHPRA specialty and RANZCOG college profile data.

**3. Scoring** — Computes an Influence Score (0–100) and Early Adopter Score (0–10), then assigns clinicians to tiers for outreach prioritisation.

**4. Network Analysis** — Builds a co-authorship graph (NetworkX), computes centrality metrics, and feeds them back into the influence score.

**5. AI Profiles** — Uses Claude API to synthesise narrative clinician profiles and classify review sentiment.

**6. Dashboard & Exports** — Streamlit dashboard for interactive exploration; Excel and CRM-formatted CSV exports for outreach teams.

## Scoring System

### Influence Score (0–100)

A weighted composite across five dimensions:

| Dimension | Weight | Sources |
|-----------|--------|---------|
| Research Output | 30% | Publication count, citation metrics, h-index |
| Clinical Leadership | 25% | Trial PI roles, grant funding, college positions |
| Network Centrality | 20% | Co-authorship graph degree/betweenness centrality |
| Digital Presence | 15% | Google Maps review volume/rating, LinkedIn activity |
| Peer Nomination | 10% | Canrefer listing, cross-referral mentions |

### Early Adopter Score (0–10)

Rule-based flag system that identifies clinicians likely to adopt new treatments early, based on signals like trial participation in novel therapies, recent publication topics, and conference presentation patterns.

### Tier Assignment

| Tier | Score Range | Description |
|------|-------------|-------------|
| Tier 1 | 75–100 | Top KOLs — primary outreach targets |
| Tier 2 | 50–74 | Strong KOLs — secondary targets |
| Tier 3 | 25–49 | Emerging KOLs — monitor and nurture |
| Tier 4 | Any score | High-centrality outlier override — well-connected clinicians who may score lower overall but are network hubs |

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker & Docker Compose (optional, for PostgreSQL + Redis)

## Quick Start (Local Development)

Use **either** local dev **or** Docker — not both at the same time. Local dev uses SQLite on port 8000; Docker uses PostgreSQL on port 8001.

```bash
make install       # install deps, Playwright browsers, copy .env
# Edit .env with your API keys
make migrate       # apply database migrations (SQLite by default)
make run           # start API server on port 8000 with hot reload
make ingest        # run full pipeline (scrape all sources + resolve + score)
```

Or without Make:

```bash
uv sync --all-extras
uv run playwright install chromium
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn gyn_kol.main:app --reload
```

The API is now running at `http://127.0.0.1:8000`. Check `http://127.0.0.1:8000/health` to verify.

> **Note:** If Docker containers are running (`make up`), stop them first with `make down` to avoid port conflicts.

## Running with Docker

Docker exposes the API on **port 8001** (not 8000) to avoid conflicts with local development.

```bash
make build         # build Docker image (includes Playwright)
make up            # start PostgreSQL + Redis + migrations + API on port 8001
make logs          # tail app logs
make down          # stop all services
make clean         # stop and remove volumes
```

Or without Make:

```bash
docker compose -f docker/compose.yml build
docker compose -f docker/compose.yml up -d
```

The compose stack runs migrations automatically before starting the app. Database URL and Redis URL are set to the internal service hostnames — no `.env` changes needed for Docker. The API is available at `http://localhost:8001`.

## Dashboard

```bash
uv run streamlit run src/gyn_kol/dashboard/app.py
```

Opens at `http://localhost:8501`. Requires the API server to be running.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/clinicians` | Paginated clinician list (filter by tier, state, subspecialty) |
| `GET` | `/clinicians/{id}` | Clinician detail with profile |
| `PATCH` | `/clinicians/{id}/score` | Manual score/tier override |
| `POST` | `/scores/recalculate` | Re-run scoring and tier assignment |
| `GET` | `/graph` | Co-authorship network as JSON |
| `GET` | `/exports/ranked-list` | Download Excel ranked list |
| `GET` | `/exports/crm` | Download CRM-formatted CSV |
| `POST` | `/ingestion/canrefer?state=NSW` | Scrape Canrefer gynaecological oncologists (optional state filter) |
| `POST` | `/ingestion/ahpra?states=NSW&search_terms=Gynaecologist` | Scrape AHPRA register via Playwright (optional state/profession filters) |
| `POST` | `/ingestion/verify` | Cross-reference Canrefer specialists against AHPRA registrations |
| `POST` | `/mbs/ingest` | Download MBS XML and store target item definitions |
| `POST` | `/mbs/link` | Link MBS items to clinicians by AHPRA specialty |
| `GET` | `/mbs/items` | List stored MBS items (paginated) |
| `GET` | `/mbs/items/{item_number}` | Get a single MBS item by number |
| `GET` | `/mbs/mappings` | List clinician–MBS mappings (filter by `clinician_id`, `item_number`) |
| `GET` | `/ingestion/canrefer/profiles?state=NSW&page=1&page_size=50` | List stored Canrefer profiles |
| `GET` | `/ingestion/ahpra/registrations?state=NSW&profession=&page=1&page_size=50` | List stored AHPRA registrations |
| `GET` | `/ingestion/verifications?status=verified&page=1&page_size=50` | List verification results |

## Specialist Extraction (Canrefer + AHPRA)

Identifies practicing Gynaecological Oncologists in Australia from two sources:

- **Canrefer** — Cancer Institute NSW referral directory. ~45 specialists nationally, organized by state. Scraped via httpx + BeautifulSoup (static HTML with JSON-LD structured data).
- **AHPRA** — Australian Health Practitioner Regulation Agency register. Comprehensive list of all practitioners. Scraped via Playwright browser automation (JavaScript-rendered).

### Setup

```bash
# Install Playwright browsers (required for AHPRA scraping)
uv run playwright install chromium
```

### Workflow

Run the three steps in order:

```bash
# 1. Scrape Canrefer specialists (all states, or filter to one)
curl -X POST "http://localhost:8000/ingestion/canrefer"
curl -X POST "http://localhost:8000/ingestion/canrefer?state=NSW"

# 2. Scrape AHPRA registrations (defaults: Gynaecologist + Oncologist in NSW)
curl -X POST "http://localhost:8000/ingestion/ahpra"
curl -X POST "http://localhost:8000/ingestion/ahpra?states=NSW&states=VIC&search_terms=Gynaecologist"

# 3. Verify Canrefer specialists against AHPRA register
curl -X POST "http://localhost:8000/ingestion/verify"
```

### Query Results

```bash
# List Canrefer profiles (default: NSW)
curl "http://localhost:8000/ingestion/canrefer/profiles?state=NSW"

# List AHPRA registrations (filter by state and/or profession)
curl "http://localhost:8000/ingestion/ahpra/registrations?state=NSW"
curl "http://localhost:8000/ingestion/ahpra/registrations?profession=Gynaecologist"

# List verification results (filter by status: verified, unmatched_canrefer, unmatched_ahpra)
curl "http://localhost:8000/ingestion/verifications?status=verified"
```

### Verification Logic

- Uses `rapidfuzz` fuzzy name matching (token sort ratio)
- Match threshold: 88 (lowered to 82 when both records share the same state)
- Creates three types of verification records:
  - `verified` — Canrefer specialist found in AHPRA register
  - `unmatched_canrefer` — Canrefer specialist not found in AHPRA
  - `unmatched_ahpra` — AHPRA registration not matched to any Canrefer specialist

## Running the Full Ingestion Pipeline

```python
# Via Prefect (recommended) — includes Canrefer, AHPRA, verification, and all other sources
uv run python -c "
import asyncio
from gyn_kol.flows.ingestion_flow import ingestion_flow
asyncio.run(ingestion_flow())
"

# Re-score after ingestion
uv run python -c "
import asyncio
from gyn_kol.flows.rescore_flow import rescore_flow
asyncio.run(rescore_flow())
"
```

## Code Quality

```bash
make test          # run test suite
make lint          # ruff lint + autofix
make typecheck     # mypy strict mode
```

## Project Structure

```
src/gyn_kol/
├── main.py              # FastAPI entrypoint
├── config.py            # Pydantic BaseSettings
├── database.py          # Async SQLAlchemy engine
├── models/              # ORM models (14 tables, incl. canrefer/ahpra/verification)
├── schemas/             # Pydantic request/response schemas
├── routers/             # FastAPI route handlers
├── ingestion/           # Data harvesters (PubMed, CrossRef, ANZCTR, NHMRC, RANZCOG, Canrefer, AHPRA, MBS, hospitals, reviews)
├── resolution/          # Entity matching (rapidfuzz + name normalisation)
├── scoring/             # Influence score, early adopter score, tier assignment
├── graph/               # NetworkX co-authorship graph + centrality
├── ai/                  # Claude API profile synthesis + review classification
├── linkedin/            # Sales Navigator CSV ingestion
├── dashboard/           # Streamlit MVP
├── exports/             # Excel + CRM CSV export
└── flows/               # Prefect orchestration flows
```

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make install` | Install all deps + Playwright Chromium + copy `.env` |
| `make test` | Run pytest |
| `make lint` | Ruff lint + autofix |
| `make typecheck` | Mypy strict |
| `make migrate` | Alembic upgrade head |
| `make run` | Uvicorn with hot reload |
| `make ingest` | Run full ingestion pipeline (scrape + resolve + score). Safe to re-run — raw data deduplicates, master records are rebuilt from scratch. |
| `make reset-db` | Stop server, delete SQLite database, re-run migrations (clean slate) |
| `make stop` | Kill local uvicorn + docker compose down |
| `make build` | Docker image build |
| `make up` | Docker Compose up (postgres + redis + migrate + app) |
| `make down` | Docker Compose down |
| `make logs` | Tail app container logs |
| `make clean` | Down + remove volumes |

## Environment Variables

See `.env.example` for the full list. Key variables:

- `DATABASE_URL` — SQLite (dev) or PostgreSQL (prod)
- `NCBI_API_KEY` — raises PubMed rate limit to 10 req/s
- `CROSSREF_EMAIL` — required for CrossRef polite pool
- `ANTHROPIC_API_KEY` — for Claude profile generation
- `GOOGLE_MAPS_API_KEY` — for clinic review data

## Reset / Clean Start

To wipe all data and start fresh:

### Local (SQLite)

```bash
make reset-db      # stops server, deletes gyn_kol.db, re-runs migrations
make run           # restart the API
```

### Docker (PostgreSQL + Redis)

```bash
# Stop containers and delete volumes (database + Redis data)
make clean

# Rebuild and start fresh
make build
make up
```

### Re-run the full pipeline after reset

```bash
# Ingest all sources, resolve entities, and score
make ingest

# Or step by step via API:
curl -X POST http://localhost:8000/ingestion/canrefer
curl -X POST http://localhost:8000/ingestion/ahpra
curl -X POST http://localhost:8000/ingestion/verify
curl -X POST http://localhost:8000/mbs/ingest
curl -X POST http://localhost:8000/mbs/link
curl -X POST http://localhost:8000/scores/recalculate
```
