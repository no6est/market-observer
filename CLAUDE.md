# Market Observability (Structure-first) - Project Rules

## Mission
Build an internal "market observability" system that detects anomalies, discovers related context, and reports emerging themes/hypotheses.
This is NOT an investment advisory tool.

## Output Contract (must)
Generate Markdown reports with:
- Top anomalies (scored)
- Emerging themes/keywords (novelty + momentum)
- Facts (price/volume/mentions/news)
- Hypotheses (with evidence links + confidence)
- Propagation candidates (related tickers / adjacent categories / substitute tech)
- Tracking queries for follow-up

## Fact vs Hypothesis
- Facts: measurable signals + source links
- Hypotheses: explicitly labeled, include supporting evidence, include confidence score, list counterpoints if available

## Scope for PoC
- Minimal sources: price/volume + 2-5 RSS feeds + 1-2 public community sources
- Storage: SQLite (swap-friendly design)
- Schedules: hourly + daily

## Engineering Constraints
- Python 3.11+
- CLI entrypoints: `run_hourly`, `run_daily`
- Config driven (YAML or TOML)
- Deterministic output as much as possible; keep raw inputs for audit
- Logging and error handling required
- Rate limit & backoff for any HTTP calls

## Repository Structure
- app/
  - collectors/   # price, RSS, Reddit, HackerNews
  - detectors/    # price_anomaly, volume_anomaly, mention_anomaly, combined
  - enrichers/    # hypothesis, shock_classifier, impact_scorer, causal_chain, propagation, theme_extractor, structural_questions, ticker_aliases
  - reporter/     # daily_report + Jinja2 templates
  - llm/          # Gemini client
  - utils/        # http_client
- configs/
- reports/
- tests/

## Git Workflow
- **Never push directly to main.** Always use feature branches and pull requests.
- Branch naming: `feature/<topic>`, `fix/<topic>`, `refactor/<topic>`
- Run `pytest` and confirm all tests pass before committing.
- PR description should summarize what changed and why.
- Never commit secrets (.env, API keys, credentials, DB files).
- `reports/` directory: only commit representative samples, not every daily output.

## Security
- API keys must be managed via environment variables (.env), never hardcoded.
- .env is in .gitignore. Only .env.example (with placeholder values) is committed.
- Data files (*.db) are in .gitignore.

## Quality Bar
- Unit tests for anomaly scoring & report rendering
- Clear docstrings & type hints
- Sample report checked into `reports/`
