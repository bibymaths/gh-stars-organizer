# Architecture and reproducibility

`cli.py` is a Typer-only interface; `organizer.py` composes the offline cache, rule engine, reports and GitHub client; `github_client.py` invokes authenticated `gh api graphql --input -`, passing GraphQL variables as JSON on stdin; `models.py` contains typed entities. `config.py` enforces non-destructive settings and migration. `classifier.py` implements normalized whole-phrase matches and evidence scoring; `profiles.py` provides cross-domain category seeds. `organization.py` creates content-addressed plans, compares complete remote snapshots and checkpoints applied operations. `cache.py` preserves existing SQLite tables and adds `classification_v2` and an FTS5 index. `reporting.py` writes Markdown, JSON and CSV artifacts.

Data flow:

```text
gh auth --> gh GraphQL stars --> SQLite repository cache --> deterministic rule scorer
                                                           |                 |
                                                           v                 v
                                                     FTS5 search        previews/reports
                                                                             |
                       local backup <-- paginated list snapshot <-- plan generator
                                                         |
                                         explicit --apply + confirmation
                                                         |
                                    reread remote -> union -> SET mutation -> verify
```

All scoring, offline search, report and plan-analysis tests can run without authentication or network. The user may opt into README fetching; large collections incur more API requests. Per-repository remote rechecks in apply are deliberate to detect concurrent modifications. A full star snapshot is fetched on each sync so removed stars can be recognized only after complete retrieval; `cache.incremental_sync` and `cache.stale_days` govern README reuse and refreshing. The most recent remote organization plan is summarized in local cache metadata for offline reporting.
