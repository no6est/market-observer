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

## Repository Structure (suggested)
- src/
  - collectors/
  - detectors/
  - enrichers/
  - reporter/
  - storage/
  - utils/
- configs/
- reports/
- tests/

## Quality Bar
- Unit tests for anomaly scoring & report rendering
- Clear docstrings & type hints
- Sample report checked into `reports/sample_*.md`
