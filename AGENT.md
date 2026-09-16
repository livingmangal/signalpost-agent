# Agent Research Policy

## Identity Resolution

The organisation number is the stable key. Every fact must resolve to the exact legal entity before publication.

### Publication Gates

1. **Organisation number match**: The org number appears on the source page or in structured data.
2. **Strong name + address match**: The legal name, address, and at least one additional signal (phone, industry, leadership name) match.
3. **Registry-linked website**: The domain is listed in the Brønnøysund entity record.

When the match is uncertain, the agent returns `ambiguous` or `not_available` instead of publishing under the wrong company.

### Not Exact Matches

- Parent companies, subsidiaries, and sister entities are labelled, not collapsed
- Franchise brands and portfolio companies are not treated as the same entity
- Search results are candidates, never evidence

## Abstention Policy

The agent abstains when:
- No permitted source confirms the exact company match
- Financial data is absent (never replaced with zero)
- A platform blocks automated access (returns `blocked`)
- Source reliability is uncertain (returns `ambiguous`)

Abstention is reported explicitly and cannot hide low coverage.

## Source Handling

### Permitted Sources (Used)
- Brønnøysundregistrene bulk CSV and live API
- Regnskapsregisteret financial API and PDF copies
- Official roles and subunit endpoints
- Verified company-owned websites
- DuckDuckGo text search (candidate generation only)
- Google News RSS (public news feed)
- Brave Search API free tier (candidate generation only)

### Restricted Sources (Not Used)
- LinkedIn (no direct scraping)
- Meta/Facebook (no direct scraping)
- Glassdoor (no direct scraping)
- Indeed (no direct scraping)
- Any source whose robots.txt or terms prohibit the access pattern

### Evidence Requirements
Every published claim includes:
- Source URL or source identifier
- Retrieval timestamp
- Content hash (SHA-256)
- Source class (official_registry, company_owned, search_candidate, etc.)
- Effective/reporting date where relevant

## LLM Usage

- **Model**: Gemini 2.0 Flash (Google, free tier)
- **Purpose**: Natural language profile summaries only
- **Constraints**: The LLM never decides entity identity, invents missing fields, or overrides deterministic evidence
- **Fallback**: Deterministic template summaries when the API is unavailable

## Refresh Behaviour

- Stable claim keys ensure idempotent upserts
- Previous evidence is preserved, never deleted
- Changes are typed (new_fact, updated_value, removed, unchanged)
- Failed refreshes keep the last known supported value
- Re-running on the same source produces no false changes
