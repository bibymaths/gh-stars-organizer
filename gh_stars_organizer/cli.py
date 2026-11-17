"""Thin Typer interface; all GitHub changes require an explicit --apply invocation."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import AppConfig, default_config_path, load_config, migrate_config, save_config
from .github_client import GitHubCLIError, UnsupportedStarLists
from .organization import StalePlanError, load_plan, write_plan
from .organizer import StarsOrganizer

app = typer.Typer(help="Deterministic local GitHub stars manager; organization is read-only by default.", no_args_is_help=True)
cache_app = typer.Typer(help="SQLite cache maintenance")
app.add_typer(cache_app, name="cache")
console = Console()


def _load(path: Optional[Path]) -> AppConfig:
    return load_config(path)


def _organization(path: Optional[Path]) -> StarsOrganizer:
    return StarsOrganizer(_load(path))


@app.command()
def doctor(config_path: Optional[Path] = typer.Option(None, "--config", "-c")):
    """Read-only authentication and schema diagnosis."""
    org = _organization(config_path)
    try:
        console.print(f"Authenticated viewer: {org.github.viewer_login()}")
        snapshot = org.github.remote_snapshot()
        console.print(f"GitHub Star Lists readable: {len(snapshot['lists'])} lists")
        console.print(f"Cached repositories: {len(org.repositories())}")
    except (GitHubCLIError, OSError) as exc:
        console.print(f"[red]GitHub doctor failed:[/red] {exc}")
        console.print("Run `gh auth login` and `gh auth status`; list APIs may require `gh auth refresh -s user`.")
        raise typer.Exit(1) from exc
    finally:
        org.close()


@app.command("config")
def config_command(
    init: bool = typer.Option(False, "--init"),
    show: bool = typer.Option(False, "--show"),
    validate: bool = typer.Option(False, "--validate"),
    migrate: bool = typer.Option(False, "--migrate"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """Initialize, display, validate, or explicitly migrate YAML configuration."""
    path = config_path or default_config_path()
    if init:
        console.print(f"Created: {save_config(AppConfig(), path)}")
    elif migrate:
        console.print(f"Migrated copy (review before using): {migrate_config(path)}")
    elif show:
        console.print(json.dumps(load_config(path).model_dump(mode="json", by_alias=True), indent=2))
    elif validate:
        load_config(path)
        console.print(f"Valid: {path if path.exists() else 'built-in defaults'}")
    else:
        console.print(f"Config path: {path}")


@app.command()
def sync(
    refresh: bool = typer.Option(False, "--refresh"),
    no_readme: bool = typer.Option(False, "--no-readme"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """Fetch starred repositories and update local cache; never mutate GitHub account data."""
    org = _organization(config_path)
    try:
        repos = org.sync(refresh=refresh, readme=False if no_readme else None)
        console.print(f"Synchronized {len(repos)} starred repositories into {org.cache.db_path}")
    finally:
        org.close()


@app.command()
def classify(
    profile: Optional[str] = typer.Option(None, "--profile"),
    explain: Optional[str] = typer.Option(None, "--explain"),
    refresh: bool = typer.Option(False, "--refresh"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """Classify offline, explain matched evidence, and cache results by rule fingerprint."""
    cfg = _load(config_path)
    if profile is not None:
        cfg.classification.profile = profile  # validated via next line
        cfg = AppConfig.model_validate(cfg.model_dump())
    org = StarsOrganizer(cfg)
    try:
        results = org.classify(refresh=refresh)
        if explain:
            repo = next((r for r in org.repositories() if r.full_name.casefold() == explain.casefold()), None)
            if repo is None:
                raise typer.BadParameter(f"repository not in cache: {explain}")
            console.print_json(results[repo.id].model_dump_json(indent=2))
        else:
            console.print(f"Classified {len(results)} repositories; {sum(not x.categories for x in results.values())} unclassified")
    finally:
        org.close()


@app.command()
def preview(
    all_repos: bool = typer.Option(False, "--all"),
    limit: int = typer.Option(100, "--limit", "-n", min=1),
    category: Optional[str] = typer.Option(None, "--category"),
    unclassified: bool = typer.Option(False, "--unclassified"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """Print classifications offline, without creating or changing GitHub Star Lists."""
    org = _organization(config_path)
    try:
        rows = org.preview(limit=None if all_repos else limit, category=category, unclassified=unclassified)
        table = Table("Repository", "Categories", "Review")
        for r, c in rows:
            table.add_row(r.full_name, ", ".join(c.categories) or "Unclassified - Review", "yes" if c.review_required else "")
        console.print(table)
        console.print(f"Displayed {len(rows)} rows")
    finally:
        org.close()


@app.command()
def organize(
    apply: bool = typer.Option(False, "--apply", help="Explicitly execute validated, additive changes"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    plan: Optional[Path] = typer.Option(None, "--plan"),
    output: Optional[Path] = typer.Option(None, "--output"),
    yes: bool = typer.Option(False, "--yes", help="Acknowledge additive writes without an interactive prompt"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """Dry-run by default. --apply checks complete remote membership state and requires approval."""
    if apply and dry_run:
        raise typer.BadParameter("choose --apply OR --dry-run")
    if plan and not apply:
        raise typer.BadParameter("--plan is only valid together with --apply")
    org = _organization(config_path)
    try:
        if apply and plan:
            current_plan = load_plan(plan)
        else:
            try:
                current_plan = org.make_plan()
            except UnsupportedStarLists as exc:
                path = org.local_lists()
                console.print(f"GitHub list schema unsupported: {exc}. Local categorized lists: {path}; no account changes.")
                return
            except GitHubCLIError as exc:
                if "scope" in str(exc).lower():
                    path = org.local_lists()
                    console.print(f"List authorization unavailable; run `gh auth refresh -s user`. Local lists: {path}")
                    return
                raise
        console.print(f"Plan {current_plan['plan_id']}: {len(current_plan['create_lists'])} new lists; {len(current_plan['changes'])} repository changes")
        for change in current_plan["changes"][:20]:
            console.print(f"  {change['repository']}: add {', '.join(change['add_names'])}")
        if not apply:
            if output:
                write_plan(current_plan, output)
                console.print(f"Saved plan: {output}")
            else:
                console.print("Dry-run only. Save with --output plan.json; apply using --apply --plan plan.json")
            return
        if not plan:
            default = Path(".gh-stars-organizer-plans") / f"{current_plan['plan_id']}.json"
            write_plan(current_plan, default)
            console.print(f"Saved automatically generated plan: {default}")
        if org.config.organization.require_confirmation and not yes:
            if not typer.confirm("Apply additive changes to your GitHub Star Lists?", default=False):
                console.print("Cancelled without remote modifications.")
                return
        result = org.apply(current_plan, Path(".gh-stars-organizer-plans"))
        console.print(f"Verified {len(result['applied'])} repository mutations. Checkpoint retained.")
    except (GitHubCLIError, StalePlanError, ValueError) as exc:
        console.print(f"[red]Organization stopped:[/red] {exc}")
        raise typer.Exit(1) from exc
    finally:
        org.close()


@app.command()
def search(
    query: str = typer.Argument("", help="Offline full-text query"),
    top_k: int = typer.Option(10, "--top-k", "-k", min=1),
    category: Optional[str] = typer.Option(None, "--category"),
    language: Optional[str] = typer.Option(None, "--language"),
    topic: Optional[str] = typer.Option(None, "--topic"),
    archived: Optional[bool] = typer.Option(None, "--archived/--active"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """Search cached stars entirely offline using FTS5/BM25, with structured filters."""
    org = _organization(config_path)
    try:
        results = org.search(query, top_k=top_k, category=category, language=language, topic=topic, archived=archived)
        table = Table("Repository", "Categories", "Language", "URL")
        for item in results:
            table.add_row(item.repository.full_name, ", ".join(item.categories), item.repository.primary_language,
                          item.repository.url)
        console.print(table)
        if not org.repositories():
            console.print("Cache empty. Run `sync` first.")
    finally:
        org.close()


@app.command()
def insights(config_path: Optional[Path] = typer.Option(None, "--config", "-c")):
    """Write Markdown analysis using cached metadata only."""
    org = _organization(config_path)
    try:
        console.print(f"Wrote {org.report('markdown')}")
    finally:
        org.close()


@app.command()
def report(
    format: str = typer.Option("markdown", "--format"),
    output: Optional[Path] = typer.Option(None, "--output"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """Export deterministic Markdown, JSON or CSV."""
    if format not in {"markdown", "json", "csv"}:
        raise typer.BadParameter("format must be markdown, json or csv")
    org = _organization(config_path)
    try:
        console.print(f"Wrote {org.report(format, output)}")
    finally:
        org.close()


@app.command()
def backup(
    output: Optional[Path] = typer.Option(None, "--output"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """Capture current remote list membership snapshot without changing GitHub."""
    org = _organization(config_path)
    try:
        filename = f"stars-backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        destination = output or Path(".gh-stars-organizer-plans") / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        snapshot = org.github.remote_snapshot()
        destination.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(destination, 0o600)
        console.print(f"Wrote read-only backup: {destination}")
    finally:
        org.close()


@app.command()
def verify(
    checkpoint: Optional[Path] = typer.Option(None, "--checkpoint"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """Read remote state, optionally compare a prior apply checkpoint."""
    org = _organization(config_path)
    try:
        snapshot = org.github.remote_snapshot()
        if checkpoint:
            state = json.loads(checkpoint.read_text(encoding="utf-8"))
            for item in state["applied"]:
                actual = sorted(snapshot["memberships"].get(item["repo_id"], []))
                if actual != item["desired_ids"]:
                    raise StalePlanError(f"mismatch for {item['repository']}: {actual}")
            console.print(f"Verified checkpoint: {len(state['applied'])} assignments")
        else:
            console.print(f"Read {len(snapshot['lists'])} GitHub Star Lists; {len(snapshot['memberships'])} listed repositories.")
            console.print("For planned-state verification, supply --checkpoint <file>.")
    finally:
        org.close()


@cache_app.command("status")
def cache_status(config_path: Optional[Path] = typer.Option(None, "--config", "-c")):
    org = _organization(config_path)
    try:
        console.print(f"Database: {org.cache.db_path}; stars: {len(org.repositories())}; last sync: {org.cache.get_metadata('last_sync') or 'never'}; FTS5: {org.cache.fts_enabled}")
    finally:
        org.close()


@cache_app.command("clear")
def cache_clear(
    yes: bool = typer.Option(False, "--yes"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    org = _organization(config_path)
    path = org.cache.db_path
    org.close()
    if not yes and not typer.confirm(f"Permanently remove local cache {path}?", default=False):
        return
    if path.exists():
        path.unlink()
    console.print(f"Cleared local database {path} (remote GitHub unchanged)")


@app.command()
def tui(config_path: Optional[Path] = typer.Option(None, "--config", "-c")):
    """Simple SSH-compatible interactive terminal menu without Textual/FAISS dependencies."""
    from rich.prompt import Prompt

    org = _organization(config_path)
    try:
        console.print("GitHub Stars Organizer — terminal menu (all GitHub writes require a separate --apply)")
        while True:
            choice = Prompt.ask("1 Sync · 2 Preview · 3 Search · 4 Insights · 5 Plan · q Quit", default="q")
            if choice == "q":
                break
            if choice == "1":
                console.print(f"Synchronized {len(org.sync())} stars")
            elif choice == "2":
                for repo, c in org.preview(limit=20):
                    console.print(f"{repo.full_name}: {', '.join(c.categories) or 'Review'}")
            elif choice == "3":
                for item in org.search(Prompt.ask("Search")):
                    console.print(f"{item.repository.full_name} ({', '.join(item.categories)})")
            elif choice == "4":
                console.print(org.report())
            elif choice == "5":
                try:
                    plan = org.make_plan()
                    console.print(f"Plan: {len(plan['changes'])} changes, {len(plan['create_lists'])} new lists")
                    destination = Prompt.ask("Save plan (path; blank to skip)", default="").strip()
                    if destination:
                        write_plan(plan, Path(destination))
                except UnsupportedStarLists:
                    console.print(f"Local categorized lists: {org.local_lists()}")
    finally:
        org.close()

if __name__ == "__main__":
    app()
