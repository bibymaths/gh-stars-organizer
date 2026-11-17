# Native Star Lists, dry runs, backups and recovery

## GitHub API semantics

GitHub GraphQL's `updateUserListsForItem(input:{itemId,listIds})` sets the repository's entire list membership set. **Passing only one list ID removes other memberships.** The original upstream called this once per list and was vulnerable to overwriting existing memberships. The rewritten flow reads all paginated lists and their repository items, then sends the **union** of current and proposed memberships in one operation per repository. We do not remove memberships, unstar repositories or delete lists.

## Preflight and application

1. `organize --dry-run --output plan.json` reads the current lists and memberships and writes a snapshot-bound plan. It does not call mutation APIs.
2. Inspect the categories and list creations. Optional `backup --output backup.json` creates a fresh read-only remote snapshot.
3. `organize --apply --plan plan.json` verifies the original snapshot, current GitHub login and rule fingerprint before writing.
4. The program stores a `.before.json` snapshot, creates missing lists (when allowed), and re-fetches remote state before every `updateUserListsForItem` mutation.
5. Each mutation checks the response's returned list IDs. After the last mutation, a fresh remote snapshot is compared with expected state.
6. A checkpoint retains every created list, completed mutation, and failure, including cases where the final verification fails.

GitHub account mutations cannot be made atomic by this tool. A process crash, network interruption or conflicting user action can leave partial changes. In that case, **do not blindly rerun the same plan**. Inspect `.gh-stars-organizer-plans/<plan_id>.checkpoint.json` and `<plan_id>.before.json`, use `verify --checkpoint ...` to compare, and generate a new plan after resolving discrepancies. Existing checkpoint files block automatic replay of the same plan. List creation is never rolled back automatically.

`backup.json`, plans and checkpoints may reveal the names of your private starred repositories; store them securely. A missing permission or unsupported GraphQL schema triggers an error or explicitly labeled local Markdown fallback; it does not silently claim a GitHub write succeeded.

## Unsupported operations

The following are intentionally not implemented: destructive reconciliation/removal, automatic rollback, list deletion, manual token acquisition, cookie-based private APIs, and committing changes to a GitHub repository. To confirm remote list writes, test against an account you control and examine results on the GitHub website. Tests in this snapshot use mocked data only.
