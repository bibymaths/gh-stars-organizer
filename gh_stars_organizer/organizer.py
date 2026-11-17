"""Composition layer with offline-first commands and conservative remote-change planning."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from .cache import SQLiteCache
from .classifier import RepositoryClassifier
from .config import AppConfig
from .github_client import GitHubClient, GitHubCLIError
from .models import ClassificationResult, Repository, SearchResult
from .organization import apply_plan, create_plan, digest
from .reporting import write_report

class StarsOrganizer:
    def __init__(self, config: AppConfig, github: GitHubClient | None = None):
        self.config = config
        self.cache = SQLiteCache(config.cache.db_path)
        self.github = github or GitHubClient(config.github.page_size)
        self.classifier = RepositoryClassifier(config)

    def sync(self, *, refresh: bool = False, readme: bool | None = None) -> list[Repository]:
        repos = self.github.fetch_starred_repositories()  # no local deletion if network failed
        if not self.config.github.include_private:
            repos = [repo for repo in repos if not repo.private]
        get_readme = self.config.classification.use_readme if readme is None else readme
        if get_readme:
            old = {r.id: r for r in self.cache.list_repositories()}
            for repo in repos:
                previous = old.get(repo.id)
                seen = self.cache.last_seen(repo.id)
                fresh = seen is not None and (datetime.now(UTC) - seen).days < self.config.cache.stale_days
                if (not refresh and self.config.cache.incremental_sync and previous and fresh
                        and previous.updated_at == repo.updated_at and previous.readme):
                    repo.readme = previous.readme
                else:
                    # GitHub CLI raw response remains local; failures do not turn into empty cached README data.
                    endpoint = f"repos/{quote(repo.owner, safe='')}/{quote(repo.name, safe='')}/readme"
                    try:
                        repo.readme = self.github._run([
                            "gh", "api", endpoint, "-H", "Accept: application/vnd.github.raw+json"], retries=1)
                    except GitHubCLIError:
                        repo.readme = previous.readme if previous else ""
        self.cache.upsert_repositories(repos, complete=True)
        return repos

    def repositories(self) -> list[Repository]:
        return self.cache.list_repositories()

    def classify(self, *, refresh: bool = False) -> dict[str, ClassificationResult]:
        fingerprint = self.classifier.fingerprint()
        results = {}
        for repo in self.repositories():
            result = None if refresh else self.cache.get_classification(repo, fingerprint)
            if result is None:
                result = self.classifier.classify(repo)
                self.cache.set_classification(repo, fingerprint, result)
            results[repo.id] = result
        return results

    def preview(self, *, limit: int | None = 100, category: str | None = None,
                unclassified: bool = False) -> list[tuple[Repository, ClassificationResult]]:
        results = self.classify()
        rows = [(r, results[r.id]) for r in self.repositories() if
                (not category or category in results[r.id].categories) and
                (not unclassified or not results[r.id].categories)]
        return rows[:limit] if limit is not None else rows

    def search(self, text: str, *, top_k: int = 10, category: str | None = None,
               language: str | None = None, topic: str | None = None,
               archived: bool | None = None) -> list[SearchResult]:
        return self.cache.search(text, top_k, category=category, language=language, topic=topic,
                                 archived=archived, results=self.classify())

    def local_lists(self) -> Path:
        categorized: dict[str, list[Repository]] = defaultdict(list)
        classifications = self.classify()
        for repo in self.repositories():
            labels = classifications[repo.id].categories or ["Unclassified - Review"]
            for label in labels:
                categorized[label].append(repo)
        output = self.config.local_lists_path.expanduser()
        output.mkdir(parents=True, exist_ok=True)
        index = ["# Local categorized GitHub stars", "", "No remote GitHub lists were modified.", ""]
        for category, repos in sorted(categorized.items()):
            slug = re.sub(r"[^a-z0-9-]", "-", category.casefold()).strip("-") or "review"
            fname = f"{slug}.md"
            lines = [f"# {category}", "", f"Repositories: {len(repos)}", ""]
            lines += [f"- [{r.full_name}]({r.url})" for r in sorted(repos, key=lambda r: r.full_name.casefold())]
            (output / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")
            index.append(f"- [{category}]({fname}) ({len(repos)})")
        (output / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
        return output

    def make_plan(self) -> dict:
        repo_list = self.repositories()
        if not repo_list:
            raise ValueError("No local starred repositories. Run `sync` first; refusing an empty plan.")
        remote = self.github.remote_snapshot()
        account = self.github.viewer_login()
        if self.config.github.username != "auto" and account.casefold() != self.config.github.username.casefold():
            raise GitHubCLIError("authenticated GitHub user does not match configured username")
        plan = create_plan(repo_list, self.classify(), remote, self.classifier.fingerprint(), account)
        # GitHub currently caps Star Lists at 32. Fail before creating any list.
        if len(remote["lists"]) + len(plan["create_lists"]) > 32:
            raise ValueError("planned list creation exceeds GitHub's 32-list account limit")
        if not self.config.organization.create_missing_lists and plan["create_lists"]:
            raise ValueError("plan requires missing list creation but config prohibits it")
        self.cache.set_metadata("last_plan_summary", json.dumps({
            "plan_id": plan["plan_id"], "existing_memberships": sum(len(v) for v in remote["memberships"].values()),
            "proposed_additions": sum(len(x["add_names"]) for x in plan["changes"]),
            "proposed_list_creations": len(plan["create_lists"]),
        }))
        return plan

    def apply(self, plan: dict, state_path: Path) -> dict:
        return apply_plan(plan, self.github, state_path, expected_rule_hash=self.classifier.fingerprint(),
                          expected_repository_hash=digest([r.model_dump(mode="json") for r in sorted(self.repositories(), key=lambda r: r.full_name.casefold())]),
                          on_applied=lambda repo_id, desired: self.cache.record_applied(plan["plan_id"], repo_id, desired))

    def report(self, fmt: str = "markdown", path: Path | None = None) -> Path:
        ext = {"markdown": ".md", "json": ".json", "csv": ".csv"}[fmt]
        if not {"markdown": self.config.reporting.markdown,
                "json": self.config.reporting.json_export, "csv": self.config.reporting.csv}[fmt]:
            raise ValueError(f"{fmt} reporting disabled by configuration")
        target = path or self.config.reporting.output_path.with_suffix(ext)
        last_plan = self.cache.get_metadata("last_plan_summary")
        applied = self.cache.conn.execute("SELECT count(*) FROM applied_operations").fetchone()[0]
        audit = {"last_plan": json.loads(last_plan) if last_plan else None, "recorded_applied_assignments": applied}
        return write_report(target, fmt, self.repositories(), self.classify(), self.config.reporting.inactive_months,
                            audit=audit)

    def close(self):
        self.cache.close()
