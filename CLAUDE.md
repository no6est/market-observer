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

## Quality Checks

After implementing any new feature or bug fix, run a verification pass before committing:

1. **Edge cases & boundary conditions**: Check for off-by-one errors, empty data handling, None/null propagation, division by zero
2. **Data pipeline verification**: Trace data flow from DB query → computation → template rendering. Verify field names match between dict keys and Jinja2 template variables
3. **Fallback paths**: Confirm `{% if %}` guards in templates handle missing/empty data gracefully
4. **LLM-dependent code**: Verify degraded mode works (`llm_client=None`). Test both success and failure (parse error, timeout) paths
5. **Test coverage**: Run `pytest tests/ -x -q` — all tests must pass. New features require new tests
6. **Report rendering**: Generate actual report (`python -m app run-monthly` or `run-daily`) and visually inspect new/changed sections
7. **Existing feature non-breakage**: Confirm unchanged sections produce identical output

### Data Pipeline Checklist
- DB query returns expected columns (check SELECT field list matches code expectations)
- Aggregation/grouping keys are consistent (e.g., Japanese vs English regime names)
- Statistics denominators exclude appropriate categories (e.g., "unknown" excluded from alignment rate)
- Date ranges and reference_date logic handle month boundaries correctly

## Test-Driven Workflow

For non-trivial changes, prefer test-first iteration:
1. Write failing tests that capture expected behavior
2. Run tests to confirm they fail
3. Implement minimal code to pass
4. Run full test suite for regressions
5. Iterate until all tests pass — do not present partial implementations
