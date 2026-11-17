# Classification and configuration

Default YAML location: `~/.gh-stars-organizer/config.yaml`. `config --init` creates but never overwrites a file. An example, showing all major configuration groups, is in [`examples/config.yaml`](../examples/config.yaml).

## Profiles

- `general`: programming languages, frameworks, development, web, mobile, infrastructure, security, testing, docs and learning.
- `data`: engineering, statistics, ML, deep learning, visualization, AI tools, deployment and research resources.
- `scientific`: bioinformatics, numerical methods, optimization, ODEs, Bayesian inference, graph science, HPC and related areas.
- `minimal`: broad development/data/infrastructure/resource buckets.
- `custom`: no default categories; only the categories explicitly present in the YAML file.

Profiles are user-agnostic and can be extended with `categories:`. Categories cannot be duplicated (case-insensitively). `categories` entries accept `name`, `description`, `keywords`, `topics`, `exclude_keywords`, `synonyms`, `minimum_score`, `priority`. Matching normalizes case and punctuation, uses whole-word or whole-phrase boundaries, and counts each rule at most once per field. `exclude_keywords` blocks a category if found in any enabled field.

Field weights are `topics`, `name`, `description`, `readme_headings`, `readme_body`, `languages`; default weights: 5, 4, 3, 2, 1, 1 respectively. A matched rule in each field contributes its corresponding integer weight. Scores are **not probabilities**. Categories meeting `minimum_score` are ordered by score, category priority, and lexicographic tie break. `score_margin > 0` restricts selected categories to that distance from the highest score. `allow_multiple_categories` and `max_categories_per_repository` limit output. Insufficient evidence remains unclassified. If too many categories qualify, `review_required` is true.

`overrides:` uses exact `owner/repo` keys, case-insensitively. An override can set `categories: [Known Name]` or `exclude: true`; overrides precede all automatic rules. A manual exclusion means no *new* list assignment, never removal from existing lists. When a repository is renamed, its full-name override must be updated manually.

## Other configuration keys

`github.username`: expected authenticated account or `auto`; `github.authentication` only `gh`; `github.page_size` 1..100; `github.include_private` controls local inclusion. `classification.use_readme` opt-in (extra API calls); `classification.review_ambiguous` controls review marking. `cache.db_path` local database location. `cache.enabled` must remain true because all workflows depend on SQLite. `cache.incremental_sync` skips fetching unchanged README content when true; `cache.stale_days` determines when a cached README becomes eligible for refresh. `organization.preserve_existing_lists` and `preserve_existing_memberships` must be true; `remove_obsolete_memberships` must be false because destructive synchronization is intentionally unsupported; `create_missing_lists` enables absent category lists; `require_confirmation` enables an interactive approval prompt. `organization.skip_unchanged` must remain true to ensure idempotence. `reporting.inactive_months` controls approximate inactivity review; `reporting.output_path` controls the Markdown default output. `reporting.markdown`, `reporting.json`, and `reporting.csv` enable or prohibit the corresponding `--format` export. The CLI flag selects the requested enabled format. `local_lists_path` is the local Markdown fallback directory.

## Migration

Old YAML files containing `model`, `api_key_env`, `embedding_model` and related AI options are **rejected explicitly**. Run `config --migrate --config old.yaml`. It writes `old.migrated.yaml` without overwriting the original. Legacy category names are preserved but their keywords are left empty; review them before use. Existing SQLite `repositories`, `classifications` and `embeddings` data is retained; versioned rules are stored separately in `classification_v2`.
