# Implementation and validation report — 17 November 2026

## Provenance and access

Target: https://github.com/vins13pattar/gh-stars-organizer
Observed upstream `main` head: `5666ec824cfed1557a88b0119306cb9c01ff0406`.
Connected account: `bibymaths`; upstream permissions `pull=true`, `push=false`.
This is a locally authored **replacement snapshot** based on source inspection, not a byte-for-byte clone and not a commit to the upstream GitHub repository. Network access from the container was unavailable for `git clone` and downloading package dependencies.

## Initial source audit

Inspected upstream root tree, README, packaging, original `github_client.py`, `classifier.py`, `embeddings.py`, `cache.py`, `config.py`, `models.py`, `cli.py`, `organizer.py`, `insights.py`, `utils.py`, TUI, tests, example configuration and CI workflow. The baseline test suite could not run because the original repository could not be cloned in the execution container. Source tests were inspected. The original app had no dedicated regression assertion that existing list memberships must survive adding a second list.

The highest-impact defect: original `GitHubClient.add_repository_to_list()` called `updateUserListsForItem` with `[list_id]`, followed by per-category calls in `StarsOrganizer.organize()`. This GraphQL mutation sets the **complete** list membership, potentially removing earlier manual and newly added memberships. The old application also depended on OpenAI-compatible HTTP chat and embedding APIs, local embedding fallback, FAISS, model-versioned SQLite caches, and defaults customized to AI-related repositories.

## Architecture, dependencies and implementation

New code: `models.py`, `config.py`, `profiles.py`, `classifier.py`, `github_client.py`, `cache.py`, `organization.py`, `organizer.py`, `reporting.py`, `cli.py`. Old `embeddings.py` and `tui_app.py` are absent; features use local SQLite FTS5 and a Rich terminal menu instead. `httpx`, `faiss-cpu`, and Textual are not required by the replacement distribution. `pyproject.toml` uses Typer, Rich, PyYAML and Pydantic 2; no AI API key or embedding service required.

Classification: normalized token/whole-phrase matching; field evidence weights and per-field provenance; opt-in README; negative exclusion evidence; aliases, synonyms, category thresholds, priorities and score margins; multi-label top-k categories; explicit overrides and exclusions; unclassified review status. Rules and per-repository metadata are hash-versioned, preventing AI-era cache reuse.

GitHub API: all operations through authenticated GitHub CLI; paginated stars and user lists; full paginated list-membership snapshot; read-only plans and back-ups; additive membership union and one SET mutation per repository; fresh remote-state check before each change; response and final snapshot verification; checkpoints after each operation; complete fail-safe rejection of stale remote state, configuration, account or repository cache. No unstar or deletion code. Non-retry mutation transport to avoid unsafe replay.

Commands: `doctor`, `config`, `sync`, `classify`, `preview`, `organize`, `search`, `insights`, `report`, `backup`, `verify`, `cache status`, `cache clear`, `tui`. Run `python -m gh_stars_organizer.cli --help` for validated CLI inventory. Configuration example in `examples/config.yaml`, documentation in `docs/`, GitHub Actions in `.github/workflows/ci.yml`.

## Tests and measurable validation

- Python 3.13.5: **48 tests passed**, no failed or skipped tests in the local final test suite.
- Coverage: **90% overall** for `gh_stars_organizer` in the measured local run; classifier 97%, organization 92%, GitHub client 94% (may vary slightly as files change).
- Compiled modules and executed CLI help and config validation successfully.
- Mocked GraphQL request/response, listing pagination, classification, legacy SQLite migration, offline FTS and fallback search, Typer workflows, additive apply, backup/verification, stale rules/repo/remote state, and partial-application checkpoint behavior.
- No live authenticated GitHub mutation was executed; no claim of real-world Star List assignment correctness or actual scope compatibility.
- Dependency installation, `uv.lock` generation, Ruff formatting, strict mypy gate and wheel/sdist package builds could not be validated in this environment because package indexes were unreachable and required tools not installed.

## Limitations and unfinished requirements

1. No direct upstream commit or PR: connected GitHub account has no upstream push permission, and no fork/write-capable repository was available.
2. GitHub GraphQL list mutations have been validated only with mocks; real account read/write testing and provider-side permissions must be verified separately before production use.
3. The original public GitHub Pages static site was not reconstructed or redeployed. This snapshot uses Markdown documentation instead.
4. No full cross-platform Python 3.11–3.13 CI results were available; Python 3.13 local tests passed.
5. No `uv.lock` because online dependency resolution is unavailable; pip editable install and building are documented but not verified in this session.
6. Cache uses full pagination of stars each sync; README fetches are incremental with configurable age. A server-side delta-sync API is not implemented.
7. There is no automatic rollback or destructive synchronization; these operations are deliberately excluded from the safe-by-default release.
8. GitHub account rate limits are handled through read-only retry/backoff and actionable failures, but advanced throughput control and request-budget estimation are not implemented.
9. Exports summarize plans and recorded completed assignments; partial-failure details remain in per-run JSON checkpoints rather than a consolidated database failures table.
10. The terminal menu is a compact Rich TUI, not a full-screen Textual interface. It deliberately does not allow applying remote mutations.

## Exact local usage

```bash
cd gh-stars-organizer-deterministic
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
gh auth login
gh-stars-organizer doctor
gh-stars-organizer config --init
gh-stars-organizer sync
gh-stars-organizer classify
gh-stars-organizer preview --all
gh-stars-organizer organize --dry-run --output plan.json
gh-stars-organizer backup --output backup.json
# Examine plan and backup. Only then, if authorized:
gh-stars-organizer organize --apply --plan plan.json
gh-stars-organizer verify --checkpoint .gh-stars-organizer-plans/<PLAN_ID>.checkpoint.json
gh-stars-organizer report --format json
```

No credentials are required in application YAML, and no personal account mutation is needed for setup, sync, search or reporting.
