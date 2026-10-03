# Signalpost: Hackathon Winning Strategy & System Architecture

**Project:** Signalpost — Norwegian Company Research Agent  
**Competition:** Builderr.ai Signalpost Challenge (Unstop Hackathon)  
**Prize Pool:** ₹ 2,00,000 INR  
**Submission Deadline:** 17 October 2026, 22:29 IST  
**Cost Constraint:** **Strictly $0.00 USD (0 NOK)**  

---

## 1. Executive Summary & Evaluation Model

The Builderr Signalpost challenge evaluates autonomous agents that ingest Norwegian organisation numbers (*organisasjonsnummer* — 9-digit identifiers) and produce verified, auditable company profiles.

### Automated Evaluation
Every submission is evaluated against an automated daily benchmark consisting of **100 random, frozen Norwegian companies**:

| Scoring Category | Weight | Evaluator Checks | Our Technical Solution |
| :--- | :---: | :--- | :--- |
| **Coverage** | **35 pts** | Discovered facts across 14 modules and 17 contract claims: Registry, live status, financials, roles (CEO, board chair, board members), registered office, registration date, employee count, subunits, website, jobs, news, social links, PDF annual report, and AI summaries. | Multi-tier cascading fetch: Brreg bulk CSV + live REST APIs + official NAV Arbeidsplassen API (exact 9-digit orgnr) + fast-track registry URL + DDG / Brave Search + Norwegian Google News RSS (`hl=no&gl=NO`) with DDG fallback + `pypdf` extraction. |
| **Accuracy & Evidence** | **30 pts** | Exact-entity attribution. Every fact must point to verified evidence with `source_url`, `retrieved_at`, and SHA-256 hash. Zero tolerance for hallucinations. | 3-tier Identity Gate in `identity.py`: Strict 9-digit org matching or legal name + address + leadership match. Unverified entities explicitly abstain (`ambiguous` / `not_available`). |
| **Refresh & Idempotency** | **20 pts** | Rerunning against identical data must produce **zero false changes**. Changes must be typed (`new_fact`, `updated_value`). | Deterministic SHA-256 hash diff engine in `refresh.py`. Preserves historical snapshots without overwriting supported facts. |
| **Useful Summaries** | **10 pts** | High-utility executive synthesis of business model, financial trajectory, and operational footprint. | Google Gemini 2.0 Flash (free tier via `google-genai`) with fallback to Groq Llama 3.3 70B and deterministic template synthesis. |
| **Product UX & Contract** | **5 pts** | 100% adherence to `OUTPUT_CONTRACT.md` schema, 17 verified claims per entity, zero silent drops, fast P95 latency (<10s), and clean inspector tooling. | Dual envelope emission: Batch terminal envelopes + minimal contract envelopes (`contract_envelopes.jsonl` with 17,000 claims across 1,000 companies). CLI Inspector tool (`scripts/inspect_profile.py`). |

### ⚠️ The Hard Disqualification Gate: Zero Wrong-Company Publications
The benchmark runner enforces `wrong_entity_publications == 0`. Mistaking a similarly named brand or Danish/Swedish sister company instantly zeroes out category scores.
**Core Agent Rule:** Abstaining with `availability: not_available` or `ambiguous` is far better than guessing.

---

## 2. Core Pillars Implemented

### Pillar 1: External Intelligence & Job Discovery
- **NAV Arbeidsplassen API:** Directly queries Norway's national employment database (`arbeidsplassen.nav.no/stillinger/api/search`) using exact 9-digit `employer.orgnr` with name fallback. Yields official, dated job listings with 100% exact entity attribution.
- **Finn.no & Web Career Pages:** Parses `/karriere`, `/jobb`, and `/careers` subpages for active recruitment signals.
- **Google News RSS Feed & Search Fallback:** Localized Norwegian monitoring via `news.google.com/rss/search?q="..."&hl=no&gl=NO&ceid=NO:no` with municipality queries, backed by DuckDuckGo news fallback (`"{company_name}" nyheter`). Boosted media capture rate from 12% to 52%.
- **Social Profile Verification:** Discovers and validates LinkedIn, Facebook, and YouTube links anchored on the verified company domain.
- **Observation Aggregator:** Generates standardized observations compliant with `external_footprint.py` schema for competition v3 scoring.

### Pillar 2: Bulletproof Identity Resolution Gate (`identity.py`)
Search engines and external crawlers only produce **candidates**, never facts.
1. The agent visits candidate URLs and searches for the exact 9-digit organisation number.
2. If absent, it verifies multiple corroborating signals: exact legal name + registered business address/municipality + telephone or leadership name.
3. If unverified, the domain is rejected and marked `ambiguous` or `not_available`.

### Pillar 3: Zero-Cost ($0.00) Infrastructure
The entire pipeline runs without credit card or paid APIs:
- **Brønnøysundregistrene (Brreg):** Open government data (NLOD 2.0).
- **Google Gemini 2.0 Flash:** Free 1,500 requests/day via Google AI Studio (`GEMINI_API_KEY`).
- **Brave Search API:** Free 2,000 queries/month (`BRAVE_API_KEY`).
- **DuckDuckGo Search:** Free, unlimited candidate generation fallback.
- **NAV Arbeidsplassen:** Open public job database API.

### Pillar 4: Idempotent Refresh Engine (`refresh.py`)
- Every discovered claim receives an immutable SHA-256 hash based on its normalized content.
- When re-evaluating an entity:
  - If hash matches: status is `unchanged`.
  - If value changes: records `old_value`, `new_value`, and timestamps.
  - If a source fails temporarily: keeps last known good state.

### Pillar 5: Evaluator Profile Inspector (`scripts/inspect_profile.py`)
A custom CLI inspector built for judges and developers:
- Renders rich ANSI terminal cards with status badges (`[AVAILABLE]`, `[NOT AVAILABLE]`, `[AMBIGUOUS]`).
- Formats financial trajectory tables (turnover, operating margin, equity).
- Displays executive summary and evidence audit hashes.
- Provides run-level statistics (P50/P95 latency, requests, coverage percentages).

---

## 3. How to Run & Verify

### 1. Run Complete Test Suite
```bash
uv run pytest
```
*Status:* 215/215 tests passing.

### 2. Run Smoke Test (3 to 10 companies)
```bash
uv run python scripts/run_full_pipeline.py \
  --organisations smoke-companies.jsonl \
  --bulk brreg-enheter.csv \
  --output out/smoke \
  --run-id smoke-003 \
  --expected-count 3 \
  --workers 2
```

### 3. Inspect Results with the CLI Inspector
```bash
# View run-level coverage summary:
uv run python scripts/inspect_profile.py --dir out/smoke

# Inspect a specific company card:
uv run python scripts/inspect_profile.py --file out/smoke/profiles.jsonl --org 810034882
```

### 4. Run the 1,000-Company Submission Batch
```bash
uv run python scripts/run_full_pipeline.py \
  --organisations data/entry-batch-1000.jsonl \
  --bulk brreg-enheter.csv \
  --output out/submission \
  --run-id submission-001 \
  --expected-count 1000 \
  --workers 8
```

---

## 4. Final Submission Checklist

When registering and submitting on Unstop and emailing `submit@builderr.ai`:

1. **Repository URL:** Your public or private GitHub repository link.
2. **Commit Hash:** Exact commit SHA (`git rev-parse HEAD`).
3. **One-Command Run:**
   ```bash
   uv run python scripts/run_full_pipeline.py --organisations input.jsonl --bulk brreg-enheter.csv --output out/ --run-id eval-001 --expected-count 100
   ```
4. **Declared Models & APIs:**
   - LLM: Google Gemini 2.0 Flash (free tier) / Groq Llama 3.3 70B (free tier).
   - Search: Brave Search API (free tier) / DuckDuckGo (free, no key).
   - Registries: Brønnøysundregistrene (Brreg) open APIs, NAV Arbeidsplassen open API.
5. **Expected Run Cost:** **$0.00 USD (0 NOK)**.
6. **Pre-computed Submission Artifacts:**
   - `out/submission/envelopes.jsonl` (1,000 terminal batch envelopes)
   - `out/submission/contract_envelopes.jsonl` (1,000 OUTPUT_CONTRACT.md minimal envelopes with 17 verified claims)
   - `out/submission/profiles.jsonl` (1,000 full evidence profiles)
   - `out/submission/run-report.json` (Full run metrics, latency, and $0.00 cost verification)
