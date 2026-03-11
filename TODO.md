# TODO.md — GYN KOL Identification App

Track progress by checking off items as they are completed. Ordered by build sequence.

---

## Phase 0 — Project Scaffold

- [ ] Initialise repo with `uv init` or `pip` + `pyproject.toml`
- [ ] Set up `ruff`, `mypy`, `pytest`, `pre-commit` config in `pyproject.toml`
- [ ] Create `.env.example` with all required variable names (no values)
- [ ] Write `src/gyn_kol/config.py` using Pydantic `BaseSettings` to load env vars
- [ ] Set up Docker + `compose.yml` (FastAPI + PostgreSQL + Redis + Prefect agent)
- [ ] Write `src/gyn_kol/database.py` — async SQLAlchemy engine + `AsyncSession` factory
- [ ] Scaffold FastAPI app in `src/gyn_kol/main.py` with health-check route (`GET /health`)
- [ ] Configure Alembic (`alembic init alembic/`, update `env.py` for async engine)
- [ ] Confirm `uvicorn src.gyn_kol.main:app --reload` runs without errors

---

## Phase 1 — Database Schema

- [ ] **`authors` table** — `author_id` (UUID), `name_raw`, `name_normalised`, `affiliation_raw`, `state`, `created_at`
- [ ] **`papers` table** — `paper_id`, `pmid`, `doi`, `title`, `pub_date`, `journal`, `raw_payload` (JSONB)
- [ ] **`coauthorships` table** — `author_id`, `paper_id`, `author_position` (composite PK)
- [ ] **`trials` table** — `trial_id`, `anzctr_id`, `title`, `pi_name_raw`, `institution`, `status`, `conditions` (array)
- [ ] **`grants` table** — `grant_id`, `nhmrc_id`, `recipient_name_raw`, `institution`, `amount`, `year`, `keywords`
- [ ] **`college_profiles` table** — `profile_id`, `name_raw`, `source` (ranzcog/ages), `subspecialty`, `state`, `committee_roles`, `speaker_history`
- [ ] **`institutional_profiles` table** — `profile_id`, `name_raw`, `institution`, `title`, `department`, `research_interests`
- [ ] **`review_signals` table** — `signal_id`, `clinician_id` (FK, nullable until resolution), `source`, `place_id`, `rating`, `review_count`, `keyword_mentions` (JSONB)
- [ ] **`master_clinicians` table** — `clinician_id` (UUID), `name_display`, `name_normalised`, `primary_institution`, `state`, `subspecialty`, `source_flags` (array), `influence_score`, `early_adopter_score`, `tier`, `updated_at`
- [ ] **`clinician_profiles` table** — `clinician_id` (FK), `profile_summary`, `engagement_approach`, `generated_at`, `model_used`
- [ ] **`audit_log` table** — `log_id`, `clinician_id`, `field_changed`, `old_value`, `new_value`, `changed_by`, `changed_at`
- [ ] Generate and apply initial Alembic migration
- [ ] Write SQLAlchemy ORM models for all tables in `src/gyn_kol/models/`
- [ ] Write Pydantic schemas for API request/response in `src/gyn_kol/schemas/`

---

## Phase 2 — Ingestion Layer (Module 1)

### 1.1 PubMed Harvester
- [ ] Implement `fetch_pubmed_results(query, max_results)` using `httpx` async + NCBI eSearch/eFetch
- [ ] Define MeSH term query set: `gynaecology`, `laparoscopy`, `endometriosis`, `hysteroscopy`, `hysterectomy`, `ovarian cancer`, `fibroids`
- [ ] Add Australian affiliation filter (`Australia[Affiliation]`)
- [ ] Add 5-year date filter
- [ ] Parse XML response with `xmltodict` → extract author name, affiliation, PMID, pub date, co-authors, trial registration numbers
- [ ] Write parsed records to `authors`, `papers`, `coauthorships` tables
- [ ] Add `asyncio.Semaphore(8)` + `tenacity` retry decorator (exponential backoff, max 5 retries)
- [ ] Write unit tests with mocked HTTP responses

### 1.2 CrossRef / Semantic Scholar Enricher
- [ ] Implement `enrich_crossref(doi)` — citation count, journal metadata
- [ ] Add `mailto` header to all CrossRef requests (polite pool)
- [ ] Implement `enrich_semantic_scholar(author_name, affiliation)` — H-index proxy, paper list
- [ ] Add Semantic Scholar rate limiting (100 req/5min semaphore)
- [ ] Append enrichment data to author records in DB
- [ ] Write unit tests with mocked responses

### 1.3 ANZCTR Trial Scraper
- [ ] Inspect ANZCTR public search/API for GYN condition filters
- [ ] Implement `fetch_anzctr_trials(conditions)` — extract PI name, institution, trial status, sites
- [ ] Fuzzy match PI names to existing `authors` records (use Module 2 matcher, or stub initially)
- [ ] Store results in `trials` table
- [ ] Write unit tests

### 1.4 NHMRC Grants Scraper
- [ ] Identify NHMRC public grants data source (CSV download or web scrape)
- [ ] Implement `fetch_nhmrc_grants(keywords)` — recipient name, institution, amount, year
- [ ] Flag high-value recipients as research credibility signal
- [ ] Store in `grants` table
- [ ] Write unit tests

### 1.5 RANZCOG / AGES Directory Scraper
- [ ] Implement RANZCOG Fellow Directory scraper (BeautifulSoup4)
- [ ] Add robust selector fallbacks; log zero-result runs as warnings
- [ ] Implement AGES member/speaker page scraper
- [ ] Extract: name, subspecialty, state, committee roles, congress speaker history
- [ ] Store in `college_profiles` table
- [ ] Write unit tests against saved HTML fixtures

### 1.6 Hospital / University Page Scraper
- [ ] Define target institution list:
  - Royal Women's Hospital Melbourne
  - Mercy Hospital for Women
  - King Edward Memorial Hospital (WA)
  - Monash Medical Centre
  - Royal Brisbane and Women's Hospital
  - John Hunter Hospital
  - Go8 O&G department pages
- [ ] Implement per-institution scrapers (BeautifulSoup4; Playwright fallback for JS pages)
- [ ] Extract: name, title, research interests, appointment level
- [ ] Store in `institutional_profiles` table
- [ ] Log pages requiring Playwright for later review

### 1.7 Clinic / Review Data Collector
- [ ] Implement Google Maps Places API client — search by clinician name + suburb
- [ ] Extract `place_id`, rating, review count per clinic
- [ ] Implement review text fetcher (Places API details endpoint)
- [ ] Extract keyword mentions: `minimally invasive`, `robotic`, `laparoscopic`, `endometriosis`
- [ ] Cache Places API responses in Redis (avoid redundant quota spend)
- [ ] Store in `review_signals` table
- [ ] Write unit tests with mocked Places API responses

---

## Phase 3 — Identity Resolution (Module 2)

### 2.1 Entity Matching Pipeline
- [ ] Implement `normalise_name(raw_name)` — lowercase, strip titles (Dr, Prof, A/Prof), handle middle initials, strip punctuation
- [ ] Implement `match_across_sources()` — `rapidfuzz` token sort ratio across all `name_normalised` fields
- [ ] Add institution + state as secondary matching signals (boost match confidence)
- [ ] Set match threshold (start at 88, tune against known duplicates)
- [ ] Use `recordlinkage` for probabilistic deduplication on large cross-product comparisons
- [ ] Produce a `clinician_id` UUID for each resolved unique person
- [ ] Write edge-case tests: hyphenated names, maiden/married names, initials-only authors

### 2.2 Master Clinician Record Builder
- [ ] Implement `build_master_record(clinician_id)` — aggregate all matched source records
- [ ] Populate `source_flags` array (e.g., `['pubmed', 'ranzcog', 'anzctr']`)
- [ ] Populate raw signal counts (pub count, trial count, grant count, review count)
- [ ] Write to `master_clinicians` table
- [ ] Write unit tests for aggregation logic

---

## Phase 4 — Scoring Engine (Module 3)

### 3.1 Influence Score
- [ ] Implement `score_research_output(clinician_id)` → 0–30
  - Publication count (normalised against cohort percentile)
  - H-index proxy (from Semantic Scholar)
  - Trial PI roles (from ANZCTR)
- [ ] Implement `score_clinical_leadership(clinician_id)` → 0–25
  - College committee membership
  - Congress speaker history
  - Guideline panel involvement
- [ ] Stub `score_network_centrality(clinician_id)` → 0–20 (returns 0 until Module 4 complete)
- [ ] Implement `score_digital_presence(clinician_id)` → 0–15
  - LinkedIn activity flag
  - ResearchGate presence
  - Media mention signals
- [ ] Stub `score_peer_nomination(clinician_id)` → 0–10 (returns 0; populated via manual override)
- [ ] Implement `calculate_influence_score(clinician_id)` — composite weighted sum
- [ ] Write unit tests for each dimension; score must be deterministic

### 3.2 Early Adopter Score
- [ ] Implement flag-based `calculate_early_adopter_score(clinician_id)` → 0–10
  - MIS or oncology subspecialty: +2
  - Private or mixed practice: +2
  - Multiple hospital affiliations: +1
  - Technology-related publications: +2
  - Training / simulation role: +1
  - Prior new device adoption signal: +2
- [ ] Write unit tests — each flag in isolation and in combination

### 3.3 Tier Assignment
- [ ] Implement `assign_tier(influence_score, early_adopter_score, centrality_flag)` → Tier 1–4
- [ ] Write tier assignment to `master_clinicians`
- [ ] Write unit tests for boundary values and Tier 4 override logic

---

## Phase 5 — Network Graph (Module 4)

### 4.1 Co-authorship Graph
- [ ] Implement `build_coauthorship_graph()` — load `coauthorships` table into NetworkX undirected graph
- [ ] Compute per-node: degree centrality, betweenness centrality, clustering coefficient
- [ ] Write centrality scores back to `master_clinicians` (unblock `score_network_centrality`)
- [ ] Re-run scoring for all clinicians after centrality is available

### 4.2 Institutional Network Inference
- [ ] Add weighted edges for shared hospital affiliation
- [ ] Add weighted edges for shared ANZCTR trial site
- [ ] Add weighted edges for shared college committee

### 4.3 Training Network
- [ ] Infer fellowship director → trainee links from university/college data
- [ ] Model as directed graph layer on top of co-authorship graph

### 4.4 Graph Export
- [ ] Implement GraphML export (`networkx.write_graphml`)
- [ ] Implement JSON export for frontend graph component
- [ ] Generate per-state hub node and bridge connector summary report
- [ ] Generate `pyvis` HTML visualisation for Streamlit embed

---

## Phase 6 — AI Profile Synthesis (Module 6)

### 6.1 Claude Profile Generator
- [ ] Implement `AsyncAnthropic` client wrapper in `src/gyn_kol/ai/profiles.py`
- [ ] Write profile generation prompt template (Jinja2) — inputs: research focus, leadership roles, early adopter signals, scores
- [ ] Implement `generate_profile(clinician_id)` — call `claude-opus-4-6`, store output in `clinician_profiles`
- [ ] Limit to Tier 1 and Tier 2 clinicians only
- [ ] Implement async batch processing with concurrency limit (`asyncio.Semaphore(5)`)
- [ ] Write unit tests with mocked Anthropic responses

### 6.2 Review Text Classifier
- [ ] Write review classification prompt (procedure type, technology mention, sentiment)
- [ ] Implement `classify_reviews(clinician_id)` — batch review texts, call `claude-haiku-4-5-20251001`
- [ ] Aggregate topic frequencies per clinician, store in `review_signals`
- [ ] Write unit tests with mocked responses

---

## Phase 7 — Dashboard & Exports (Module 7)

### 7.1 Excel / CSV Export
- [ ] Implement `export_ranked_list()` — pandas DataFrame → Excel via openpyxl
  - Columns: rank, name, tier, influence score, early adopter score, state, subspecialty, source flags, profile summary, recommended contact pathway
- [ ] Add source attribution flags per record
- [ ] Implement CRM export mapper (Salesforce / HubSpot field mapping)

### 7.2 Streamlit MVP Dashboard
- [ ] Set up Streamlit app at `src/gyn_kol/dashboard/app.py`
- [ ] **Clinician Table View** — sortable/filterable by tier, state, subspecialty, score
- [ ] **Clinician Detail View** — all signals, scores, profile summary, source links
- [ ] **Network Graph View** — embed `pyvis` HTML output in Streamlit
- [ ] **Tier Summary View** — `plotly` bar/pie charts by tier and state
- [ ] **Manual Override Panel** — adjust score, add peer nomination, flag as contacted
- [ ] All overrides written to `audit_log` table

### FastAPI Routes
- [ ] `GET /clinicians` — paginated, filterable list
- [ ] `GET /clinicians/{clinician_id}` — full detail view
- [ ] `PATCH /clinicians/{clinician_id}/score` — manual score override
- [ ] `GET /graph` — return graph JSON for frontend
- [ ] `GET /exports/ranked-list` — trigger CSV/Excel export download
- [ ] `GET /exports/crm` — trigger CRM-formatted CSV export

---

## Phase 8 — LinkedIn Enrichment (Module 5)

- [ ] Implement `parse_sales_navigator_csv(filepath)` — normalise exported lead fields
- [ ] Match exported leads to `clinician_id` via entity resolution (Module 2 matcher)
- [ ] Extract and store LinkedIn signals: activity level, group memberships, shared connections
- [ ] Append `linkedin_signals` to master clinician records
- [ ] Write unit tests with sample CSV fixtures

---

## Phase 9 — Monitoring & Scheduling (Module 8)

### 8.1 Prefect Flows
- [ ] Define `ingestion_flow` — runs all Module 1 harvesters in sequence with dependency order
- [ ] Define `rescore_flow` — re-runs scoring and tier assignment for changed records
- [ ] Add Prefect retry decorators to all tasks wrapping external API calls
- [ ] Configure Prefect deployment with cron schedule (weekly re-score)
- [ ] Test flows locally with Prefect local server

### 8.2 Google Scholar Alert Generator
- [ ] Implement `generate_scholar_alert_urls(tier_filter=[1,2])` — output list of Scholar alert URLs
- [ ] Export as markdown/CSV with setup instructions

### 8.3 Audit Log
- [ ] Confirm all score changes write to `audit_log`
- [ ] Confirm all manual overrides write to `audit_log`
- [ ] Add `GET /audit/{clinician_id}` API route to view change history

---

## Phase 10 — Production Hardening

- [ ] Switch `DATABASE_URL` to PostgreSQL (Supabase or Railway)
- [ ] Run full Alembic migration against PostgreSQL
- [ ] Add JSONB indexes on `raw_payload` columns
- [ ] Add GIN index on `source_flags` array column
- [ ] Set up Redis for API response caching
- [ ] Configure environment-specific settings in `config.py` (dev/staging/prod)
- [ ] Set up CI pipeline (GitHub Actions) — runs ruff, mypy, pytest on every PR
- [ ] Write `README.md` with setup, env var, and run instructions
- [ ] Deploy FastAPI to Railway / Render via Docker

---

## Ongoing / Backlog

- [ ] Evaluate `pgvector` for embedding-based clinician similarity search
- [ ] Migrate Streamlit dashboard to React + Vite + TailwindCSS (when sharing more broadly)
- [ ] Implement `react-force-graph` or `sigma.js` WebGL network view in React frontend
- [ ] Add HotDoc scraper to `review_signals` pipeline (currently Google Maps only)
- [ ] Add ResearchGate profile presence check to digital presence scoring
- [ ] Evaluate Playwright-based NHMRC grants scraper if CSV download is unavailable
- [ ] Add `shadcn/ui` component library if/when React dashboard is built
- [ ] Investigate ORCID API as a stable author identity anchor for entity resolution
