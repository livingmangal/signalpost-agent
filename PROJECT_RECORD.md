# Signalpost Agent: Development & Activity Record

**Repository:** Signalpost Norwegian Company Research Agent  
**Goal:** Build an autonomous agent that researches Norwegian companies from permitted public sources and returns fact-rich, verified profiles with source evidence and dates.  
**Budget Constraint:** **$0.00 USD / 0 NOK** (strictly zero-cost, utilizing free-tier APIs and open government registries).  
**Last Updated:** 2026-09-16  

---

## 1. Executive Summary

We developed, configured, and verified a production-ready research agent tailored for the Builderr Signalpost challenge. The system is designed to maximize scoring across all 5 evaluation dimensions:
- **Coverage (35 pts):** Extracted across 14 comprehensive modules (Registry, Financials, Roles, Subunits, Websites, Career/Jobs, News RSS, Social Links, Annual Report PDFs, AI Summaries).
- **Accuracy (30 pts):** Identity gates with strict organization number verification to prevent false domain attribution and hallucination.
- **Refresh & Change Detection (20 pts):** Deterministic SHA-256 claim tracking and diff engine preserving snapshot history across repeated runs.
- **Useful Summaries (10 pts):** Natural language synthesis via Google Gemini 2.0 Flash / Groq free tier with strict deterministic template fallback.
- **UX & Contract Compliance (5 pts):** Strict adherence to `OUTPUT_CONTRACT.md` (terminal envelopes, valid lifecycle states, zero silent drops).

---

## 2. Zero-Cost Infrastructure & Free API Architecture

The entire stack is configured to run at **$0.00 run cost**.

### Free API Integrations
1. **Google Gemini API** (`GEMINI_API_KEY`):
   - **Provider:** Google AI Studio ([aistudio.google.com/apikey](https://aistudio.google.com/apikey))
   - **Free Quota:** 1,500 requests/day, 15 requests/min.
   - **Role:** Generates synthesized professional company profiles from verified evidence.
2. **Brave Search API** (`BRAVE_API_KEY`):
   - **Provider:** Brave Software ([brave.com/search/api](https://brave.com/search/api/))
   - **Free Quota:** 2,000 queries/month.
   - **Role:** Supplementary search discovery for unlisted websites and corporate mentions.
3. **Tavily Search API** (`TAVILY_API_KEY`):
   - **Provider:** Tavily ([tavily.com](https://tavily.com))
   - **Free Quota:** 1,000 queries/month.
   - **Role:** Clean web content extraction and agentic search.
4. **Groq API** (`GROQ_API_KEY`):
   - **Provider:** Groq Console ([console.groq.com](https://console.groq.com))
   - **Free Quota:** 30 requests/min.
   - **Role:** Ultra-fast free backup LLM inference (Llama 3.3 70B).
5. **SerpAPI** (`SERPAPI_API_KEY`):
   - **Provider:** SerpAPI ([serpapi.com](https://serpapi.com))
   - **Free Quota:** 100 queries/month.

### 100% Free Public Open Data (Zero Keys Required)
- **Brønnøysundregistrene (Brreg) Enhetsregisteret:** Open official REST API for Norwegian enterprise registry.
- **Brreg Regnskapsregisteret:** Open financial statements API (operating income, balance sheet, net profits, debt, equity).
- **Brreg Roller:** Official register of board members, CEOs (*daglig leder*), chairpersons, and auditors.
- **Brreg Underenheter:** Official subunit and branch location registry.
- **Google News RSS:** Public RSS feed for live news monitoring (`news.google.com/rss/search?q="..."`).
- **Norwegian Wikipedia API:** Open MediaWiki REST API for corporate background and Wikipedia articles.
- **Direct Website Crawling:** In-house HTTP extraction with identity gate verification.

---

## 3. Key Components Built & Enhanced

### `src/norway_company_agent/`
- **[__init__.py](file:///c:/Users/hiima/Desktop/builderr/src/norway_company_agent/__init__.py):** Automatic `.env` environment variable loader that loads local free API keys into `os.environ` without requiring third-party libraries.
- **[search_api.py](file:///c:/Users/hiima/Desktop/builderr/src/norway_company_agent/search_api.py):** Unified multi-provider search client cascading through Brave, Tavily, SerpAPI, DuckDuckGo, and Norwegian Wikipedia with strict query budget tracking.
- **[summary.py](file:///c:/Users/hiima/Desktop/builderr/src/norway_company_agent/summary.py):** Profile summary generator supporting Gemini 2.0 Flash and Groq Llama 3.3 70B free tiers, falling back to a deterministic structured markdown template.
- **[jobs.py](file:///c:/Users/hiima/Desktop/builderr/src/norway_company_agent/jobs.py):** Career page parser and Norwegian job board search (Finn.no / Arbeidsplassen).
- **[news.py](file:///c:/Users/hiima/Desktop/builderr/src/norway_company_agent/news.py):** Google News RSS aggregator and company website press extractor.
- **[social.py](file:///c:/Users/hiima/Desktop/builderr/src/norway_company_agent/social.py):** Social media profile verification (LinkedIn, Facebook, YouTube, X) confirming links against verified company websites.
- **[pdf_extract.py](file:///c:/Users/hiima/Desktop/builderr/src/norway_company_agent/pdf_extract.py):** Brreg annual account PDF downloader and text extractor using `pypdf`.
- **[refresh.py](file:///c:/Users/hiima/Desktop/builderr/src/norway_company_agent/refresh.py):** Change detection and diff engine tracking 14 modules with immutable SHA-256 evidence hashing.

### `scripts/`
- **[run_full_pipeline.py](file:///c:/Users/hiima/Desktop/builderr/scripts/run_full_pipeline.py):** Main one-command batch orchestrator supporting multi-threaded processing, checkpointing, resume capability, and terminal envelope emission.
- **[select_entry_batch.py](file:///c:/Users/hiima/Desktop/builderr/select_entry_batch.py):** Reproducible company selector that samples from `signalpost-universe.jsonl.gz` and validates existence in the Brreg snapshot using automatic delimiter and gzip sniffing.

### Configuration & Dependencies
- **[pyproject.toml](file:///c:/Users/hiima/Desktop/builderr/pyproject.toml):** Managed project dependencies pinned for compatibility (pinned `primp<0.14` to resolve DDGS impersonation conflicts).
- **[.env.example](file:///c:/Users/hiima/Desktop/builderr/.env.example):** Ready-to-use template documenting every free API key with direct registration links.
- **[.env](file:///c:/Users/hiima/Desktop/builderr/.env):** Local environment file populated for pasting keys.

---

## 4. Datasets Acquired & Validated

1. **`brreg-enheter.csv` (154.6 MB):**
   - Downloaded from: `https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv`
   - Format: Gzipped CSV containing all registered Norwegian enterprises.
2. **`signalpost-universe.jsonl.gz` (12.6 MB):**
   - Downloaded from: `https://builderr.ai/signalpost-company-universe-2025.jsonl.gz`
   - Contains all eligible organisations for the competition.
3. **`data/entry-batch-1000.jsonl`:**
   - Sampled 1,000 companies directly from the universe.
   - **Verification:** 1,000 / 1,000 (100%) confirmed present in the `brreg-enheter.csv` snapshot.

---

## 5. Verification & Test Logs

### Test 1: First Run Sanity Check
- Command: `uv run python first_run.py`
- Result: **Passed** (verified starter kit baseline and imports).

### Test 2: Multi-Provider Search Test
- Command: `search_company('Equinor ASA', '923609016')`
- Result: Returned 7 verified corporate URLs across search and Norwegian Wikipedia.

### Test 3: Google News RSS Discovery
- Command: `fetch_google_news_rss('Equinor ASA')`
- Result: Returned 10 recent news articles with publication dates and sources.

### Test 4: Pipeline Smoke Test (`smoke-002`)
- Input: 3 Norwegian companies ([smoke-companies.jsonl](file:///c:/Users/hiima/Desktop/builderr/smoke-companies.jsonl))
- Command:
  ```powershell
  uv run python scripts/run_full_pipeline.py `
    --organisations smoke-companies.jsonl `
    --bulk brreg-enheter.csv `
    --output out/smoke `
    --run-id smoke-002 `
    --expected-count 3 `
    --workers 2
  ```
- Output Results:
  - **Emitted Envelopes:** 3 / 3
  - **Outbound Requests:** 18
  - **Search Queries Used:** 15 / 500
  - **API Cost:** **$0.00**
  - **Validation:** **PASSED** (All entity states terminal, zero silent drops).

---

## 6. Submission Details

| Field | Submission Value |
| :--- | :--- |
| **Batch Size** | 1,000 companies ([data/entry-batch-1000.jsonl](file:///c:/Users/hiima/Desktop/builderr/data/entry-batch-1000.jsonl)) |
| **One Command to Run** | `uv run python scripts/run_full_pipeline.py --organisations data/entry-batch-1000.jsonl --bulk brreg-enheter.csv --output out/production --run-id entry-1000 --expected-count 1000 --workers 8` |
| **Model / APIs** | Gemini 2.0 Flash (free tier) / Groq Llama 3.3 70B (free tier) / Brave Search (free tier) / Brreg Open APIs / Google News RSS / Wikipedia |
| **Expected Run Cost** | **$0.00 USD (0 NOK)** |
| **Expected Runtime** | ~15–25 minutes for 100 companies; ~1.5–2 hours for 1,000 companies with 8 concurrent workers |
