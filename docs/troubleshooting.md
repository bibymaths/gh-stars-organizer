# Troubleshooting and FAQ

**Q: Do I need an API key for AI?** No. The project uses local rules, SQLite and GitHub CLI authentication. `gh auth login` is required only for sync and remote list operations, not cached search and reports.

**Q: Why are categories missing?** Rules must match a whole phrase in enabled metadata fields and exceed `minimum_score`. Inspect `classify --explain owner/repo`. Add keywords or explicit overrides. Unclassified repositories are reported, not forced into an arbitrary list.

**Q: Why is `doctor` failing?** Run `gh auth status` locally; if list-specific scope errors occur, run `gh auth refresh -s user`. Do not paste credential output into tickets or chats. A GitHub server or GraphQL schema change may also prevent list access.

**Q: Why was no list created?** `organize` is a dry run. Use `organize --dry-run --output plan.json`, inspect, then explicitly `organize --apply --plan plan.json`. Read-only preview never changes the account.

**Q: Why did apply stop?** A stale plan, changed login, conflicting remote modification, API permission failure, or verification mismatch blocks further mutations. Review saved snapshot and checkpoint; do not retry blindly. Build a fresh plan after reconciliation.

**Q: Can it clear old categories?** No. This release intentionally implements additive memberships only. Existing lists and memberships are never automatically removed.

**Q: Can I search offline?** Yes, after one successful `sync`. FTS5 provides BM25 ranking; SQLite without FTS5 uses a simpler SQL+Python fallback.

**Q: Does `inactive` mean abandoned?** No. The configurable `inactive_months` criterion is only the time since GitHub's last repository update and should be reviewed manually.

**Q: How are pre-LLM caches migrated?** The existing SQLite repository metadata is preserved. New rule-versioned classifications are recalculated; old AI classifications/embeddings remain stored but unused. YAML migration is opt-in and never overwrites your original file.
