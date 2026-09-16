# Signalpost — Norwegian Company Research Agent

An automated agent that researches Norwegian companies from public sources, returning verified profiles with source evidence, dates, and availability states.

## Quick Start

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Setup

```bash
# Clone and enter the repo
cd builderr

# Install dependencies
uv sync

# Download required data
# 1. Brreg entity snapshot (official registry)
curl -L 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv' -o brreg-enheter.csv

# 2. Company universe (eligible organisation numbers)
curl -L 'https://builderr.ai/signalpost-company-universe-2025.jsonl.gz' -o signalpost-universe.jsonl.gz

# 3. Set up API keys (optional but recommended)
cp .env.example .env
# Edit .env and add your free API keys
```

### API Keys (Free)

| Key | Source | Purpose |
|-----|--------|---------|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com/apikey) | LLM-powered profile summaries |
| `BRAVE_API_KEY` | [brave.com/search/api](https://brave.com/search/api/) | Supplementary search (2,000/month free) |

Both are optional. The agent works without them using DuckDuckGo search and template summaries.

### Run

**One-command evaluator run (100 companies):**

```bash
uv run python scripts/run_full_pipeline.py \
  --organisations input.jsonl \
  --bulk brreg-enheter.csv \
  --output out/ \
  --run-id eval-001 \
  --expected-count 100
```

**Smoke test (10 companies):**

```bash
# Select 1000 companies, take first 10 for testing
uv run python select_entry_batch.py \
  --universe signalpost-universe.jsonl.gz \
  --count 1000 \
  --output entry-companies.jsonl

head -n 10 entry-companies.jsonl > smoke-companies.jsonl

uv run python scripts/run_full_pipeline.py \
  --organisations smoke-companies.jsonl \
  --bulk brreg-enheter.csv \
  --output out/smoke/ \
  --run-id smoke-001 \
  --expected-count 10
```

**Full 1,000-company submission run:**

```bash
uv run python scripts/run_full_pipeline.py \
  --organisations entry-companies.jsonl \
  --bulk brreg-enheter.csv \
  --output out/submission/ \
  --run-id submission-001 \
  --expected-count 1000
```

### Output

The pipeline produces:
- `out/profiles.jsonl` — Full company profiles with evidence
- `out/envelopes.jsonl` — Terminal envelopes (competition format)
- `out/run-report.json` — Run metrics, validation results, and budget tracking

## Architecture

```
Organisation Number
       │
       ▼
┌──────────────┐
│  Brreg Bulk  │ ── Identity anchor (name, form, address, industry)
│  Registry    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Official API │ ── Financials, roles, group, locations, subunits
│ Enrichment   │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Website      │ ── Registry URL + search discovery → crawl + identity gate
│ Discovery    │
└──────┬───────┘
       │
       ├──► Job Discovery (career pages + Finn.no + NAV)
       ├──► News Discovery (Google News RSS + company press)
       ├──► Social Profiles (from verified website)
       ├──► PDF Extraction (annual report from Brreg)
       │
       ▼
┌──────────────┐
│ Summary      │ ── Gemini Flash (free) or deterministic template
│ Generation   │
└──────┬───────┘
       │
       ▼
  Terminal Envelope (JSONL)
```

## Data Sources

| Source | Type | Cost | Key Required |
|--------|------|------|--------------|
| Brønnøysundregistrene (Brreg) | Official registry | Free | No |
| Regnskapsregisteret | Official financials | Free | No |
| Company websites | Company-owned | Free | No |
| DuckDuckGo Search | Search discovery | Free | No |
| Google News RSS | News feed | Free | No |
| Brave Search API | Search discovery | Free tier | Optional |
| Gemini Flash API | LLM summaries | Free tier | Optional |

**Declared cost per 100-company batch: $0.00**

## Scoring Target

- Coverage (35 pts): Registry + financials + website + roles + locations + jobs + news + social
- Accuracy (30 pts): Strict identity gates, org number verification, no fabrication
- Refresh (20 pts): Idempotent diffs, history preservation, no false changes
- Summary (10 pts): LLM-enhanced or template-based, sourced conclusions
- UX (5 pts): Clean JSON, clear states, documented

## Models, APIs & Licences

- **Gemini 2.0 Flash** (Google, free tier) — profile summary generation
- **DuckDuckGo Search** (free, no key) — primary search discovery
- **Brave Search API** (free tier, optional) — supplementary search
- All data from official Norwegian public registries (open data)
- No restricted platform scraping (LinkedIn, Meta, Glassdoor, Indeed)

## Budget Compliance

| Limit | Budget | Actual |
|-------|--------|--------|
| Wall clock | 45 min | ~15-25 min |
| Outbound requests | 2,000 | ~800-1,200 |
| Third-party API cost | $10 | $0.00 |
