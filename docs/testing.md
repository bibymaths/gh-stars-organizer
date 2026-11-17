# Development, tests and validation status

From the project root:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m pytest --cov=gh_stars_organizer --cov-report=term-missing
python -m compileall -q gh_stars_organizer
ruff check gh_stars_organizer tests
ruff format --check gh_stars_organizer tests
mypy gh_stars_organizer
python -m build
```

Tests use local SQLite, fake GitHub clients and mocked GraphQL responses. Safety checks include complete membership union, state drift, plan tampering, pagination errors, rule fingerprints and no unintended removal. There is **no authenticated mutation integration test**. The CI matrix targets 3.11, 3.12 and 3.13 and runs tests, Ruff and build. Static typing currently remains informational in CI; address type debt before enforcing a strict gate. Do not interpret simulated GraphQL success as confirmation against a user's live account.
