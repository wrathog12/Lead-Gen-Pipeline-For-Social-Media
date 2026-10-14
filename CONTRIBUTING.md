# Contributing to Lead-Gen Pipeline

Thanks for your interest in contributing! This document outlines the workflow
and conventions we follow so that the codebase stays consistent and easy to
navigate.

---

## Getting Started

1. **Fork & clone** the repository.
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` → `.env` and fill in your API keys.

## Branch Naming

| Type     | Pattern                | Example                      |
|----------|------------------------|------------------------------|
| Feature  | `feat/<short-desc>`    | `feat/youtube-comment-depth` |
| Bug fix  | `fix/<short-desc>`     | `fix/quora-429-retry`        |
| Docs     | `docs/<short-desc>`    | `docs/api-readme`            |
| Refactor | `refactor/<short-desc>`| `refactor/tier2-prompt`      |

## Commit Messages

We loosely follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scraper): add pagination support for Reddit search
fix(pipeline): handle empty LLM response in tier-2 validator
docs: update architecture diagram in README
test: add thread-safety tests for rate limiter
```

## Code Style

- **Python 3.10+** — use type hints wherever practical.
- Run `black .` before committing (line length 88).
- Prefer `dataclasses` / `Pydantic` models over raw dicts for structured data.
- Keep modules focused: one scraper per file, one pipeline stage per file.

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_rate_limiter.py -v

# Live integration tests (requires valid API keys in .env)
pytest tests/ -v -m "live"
```

> **Note:** Tests prefixed with `test_*_live.py` hit real APIs and are skipped
> in CI by default. Run them locally when working on a specific scraper.

## Adding a New Platform Scraper

1. Create `src/ingestion/<platform>_client.py` implementing the `BaseClient` interface.
2. Register default rate-limit values in `src/utils/rate_limiter.py`.
3. Add a live test under `tests/test_<platform>_live.py`.
4. Update `README.md` with the new platform badge.

## Pull Request Checklist

- [ ] Tests pass locally (`pytest tests/ -v`).
- [ ] No new lint warnings (`black --check .`).
- [ ] Commit messages follow the convention above.
- [ ] Any new env vars are documented in `.env.example`.

---

## Questions?

Open an issue or reach out to the maintainers — happy to help!
