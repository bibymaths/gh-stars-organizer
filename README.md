# gh-stars-organizer — deterministic edition

Local-first, multi-label organization of GitHub starred repositories. **No OpenAI account, LLMs, embedding APIs, local models, FAISS, browser cookies or manually created PAT required.** Authentication uses [GitHub CLI](https://cli.github.com/) (`gh`).

> Implementation snapshot based on inspection of the MIT-licensed upstream project [vins13pattar/gh-stars-organizer](https://github.com/vins13pattar/gh-stars-organizer). **This downloadable implementation is not an upstream release or an upstream commit.** GitHub list-write support has been tested against mocked GraphQL replies, **not** a real authorized account. Exercise `--apply` only after examining the plan and backup.

## What it does

- Retrieve the authenticated account's stars through paginated GitHub GraphQL; preserve inaccessible/legacy data until a complete sync succeeds.
- Classify them offline using field-weighted exact keywords and phrases, multi-label scoring, negative rules, synonyms, category profiles, overrides and transparent evidence.
- Keep metadata in SQLite, migrate old cache tables non-destructively and search offline using SQLite FTS5/BM25 (LIKE fallback when FTS5 is unavailable).
- Preview a **read-only** plan, fetch *all* list memberships, reconcile additively, save a pre-write snapshot, reject stale plans, checkpoint partial failures and verify a remote readback.
- Export Markdown/JSON/CSV reports, including recorded application counts and most recent plan summaries, and local Markdown category lists.
- Provide a lightweight interactive terminal menu usable over SSH.

## Important safety constraints

`organize` and `organize --dry-run` never mutate remote account data. Only `organize --apply` can create a list or change memberships. `updateUserListsForItem` **replaces** all memberships; the implementation always supplies the complete union of existing and new memberships, and re-reads remote state before each repository update. Never unstars, deletes a list, or removes existing memberships. If the API is unsupported, `organize` provides an explicitly labeled local Markdown fallback. If a run fails after starting, GitHub is **not atomic**; the checkpoint documents what was applied and requires inspection before retrying.

## Requirements and installation

Python 3.11+, GitHub CLI, and an ordinary terminal. To install this downloadable replacement project:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
gh auth login
gh auth status
gh-stars-organizer --help
```

If using `uv`, run `uv sync` (when a lockfile is generated on your machine) or `uv run gh-stars-organizer --help`. When GitHub user-list reads fail due to permissions, run `gh auth refresh -s user` locally and check `gh auth status`. No credentials should be pasted into chats or configuration.

## Quickstart: first sync through verified planning

```bash
gh-stars-organizer doctor                     # read-only connectivity/permission diagnosis
gh-stars-organizer config --init              # writes local YAML, never remote
gh-stars-organizer config --validate
gh-stars-organizer sync                        # fetches all stars into SQLite
gh-stars-organizer classify                    # offline rule scoring
gh-stars-organizer preview --all               # inspect multi-label suggestions
gh-stars-organizer preview --unclassified
gh-stars-organizer organize --dry-run --output plan.json
gh-stars-organizer backup --output backup.json # remote snapshot, no changes
# Carefully inspect the saved plan before the next command:
gh-stars-organizer organize --apply --plan plan.json
gh-stars-organizer verify --checkpoint .gh-stars-organizer-plans/<PLAN_ID>.checkpoint.json
gh-stars-organizer insights
gh-stars-organizer search "differential equations" --language Python
gh-stars-organizer report --format csv --output stars.csv
```

`--apply` requires terminal confirmation by default. The explicit `--yes` flag bypasses the interactive prompt, but does **not** bypass stale-plan checks. The plan is tied to an authenticated account, a full remote snapshot and a classification-rule fingerprint.

## User-oriented workflows

`config --show`, `config --validate`, `config --migrate` (write a separately named copy of old AI configuration), `sync --refresh`, `sync --no-readme`, `classify --profile scientific`, `classify --explain owner/repo`, `preview --category "Developer Tools"`, `search "workflow" --category "Developer Tools"`, `search "graph" --topic graph`, `report --format json`, `cache status`, `cache clear`, and `tui`.

Profiles are `general`, `data`, `scientific`, `minimal`, and `custom`. `general` is the default. Custom rules can be appended in YAML, and `custom` disables all built-in categories. Manual overrides always win. Repositories without sufficient evidence stay **Unclassified - Review**, not assigned to arbitrary categories.

Configuration: [`examples/config.yaml`](examples/config.yaml). Documentation: [`docs/index.md`](docs/index.md), [`docs/safety.md`](docs/safety.md), [`docs/architecture.md`](docs/architecture.md), [`docs/cli.md`](docs/cli.md), [`docs/testing.md`](docs/testing.md).

## Development and audit status

```bash
python -m pytest -q
python -m pytest --cov=gh_stars_organizer --cov-report=term-missing
python -m compileall -q gh_stars_organizer
```

Tests are entirely offline and mocked. The release source carries no provider API client dependencies. A live-authorized GitHub GraphQL smoke test and publishing verification are **not claimed**.

## Limitations

A local YAML category schema is not a language model: rule coverage varies and must be tuned to the user's collection. README retrieval is opt-in. Unavailable README content preserves any older cached copy; it does not cause remote writes. GitHub Star List requests may require a `user` scope, and actual provider behavior can change. Full remote snapshot reads before each write prioritize safety over speed. No automated rollback, deletion of obsolete memberships, or unstar features are included. The old FAISS and model tables remain in existing SQLite databases for non-destructive migration; they are not consulted.

License: MIT; upstream license attribution retained in `LICENSE`.


### Accounts with 32 existing Star Lists

New list creation is disabled by default. The organizer will reuse lists whose names
match classification categories, and skip unmatched categories with a clear count.
To organize all classified repositories, map **every relevant category** to an actual
existing Star List under `organization.category_to_list` in your YAML configuration.
Several categories may share one list. Preview with `organize --dry-run --output plan.json`;
review `skipped_categories` in the plan before applying.
