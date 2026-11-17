# Installation, Quickstart, CLI reference

Requirements: Python >=3.11, a working `gh` installation, and permission to read your own Star Lists. For remote list writes, your account must have appropriate scope, commonly `user` (`gh auth refresh -s user`).

Install and authenticate:

```bash
python -m pip install -e '.[dev]'
gh auth login
gh auth status
gh-stars-organizer doctor
gh-stars-organizer config --init
```

All commands below are implemented:

| Command | Purpose | GitHub mutation? |
|---|---|---|
| `doctor` | Check viewer and readable lists | No |
| `config --init/--show/--validate/--migrate` | Local YAML | No |
| `sync [--refresh] [--no-readme]` | Refresh SQLite stars | No |
| `classify [--profile scientific] [--explain owner/repo] [--refresh]` | Offline scoring | No |
| `preview [--all] [--limit N] [--category NAME] [--unclassified]` | Offline labels | No |
| `organize` / `organize --dry-run --output plan.json` | Compute change plan | No |
| `organize --apply [--plan plan.json] [--yes]` | Validate/add missing lists/memberships | **Yes** |
| `search QUERY [--top-k N] [--language NAME] [--topic NAME] [--category NAME] [--archived/--active]` | Offline search | No |
| `insights` | Write Markdown report | No |
| `report --format markdown\|json\|csv [--output FILE]` | Export metadata | No |
| `backup [--output FILE]` | Save remote snapshot | No |
| `verify [--checkpoint FILE]` | Check remote state | No |
| `cache status` / `cache clear [--yes]` | Local database maintenance | No |
| `tui` | Simple terminal menu; does not itself apply mutations | No |

Any command using the cache accepts `--config path/to/config.yaml` (usually `-c`). `--yes` affects user confirmation only, and does not suppress remote-state, rule-hash, or account validation. `--apply` without `--plan` builds and saves a new plan before confirmation. `--apply --plan` validates the previously saved plan. Inspect `plan.json` first.

**Example output (illustrative, not a real GitHub operation):**

```text
Plan <sha256>: 1 new lists; 4 repository changes
  example/project: add Developer Tools
Dry-run only. Save with --output plan.json; apply using --apply --plan plan.json
```

Do not use `--apply` on unreviewed categories; start with `preview --all`, inspect evidence using `classify --explain`, then adjust `categories` or `overrides`.
