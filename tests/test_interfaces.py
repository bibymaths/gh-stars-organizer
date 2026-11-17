import json
from pathlib import Path
from typer.testing import CliRunner
from gh_stars_organizer.cli import app
from gh_stars_organizer.cache import SQLiteCache
from gh_stars_organizer.config import AppConfig, save_config
from gh_stars_organizer.github_client import GitHubClient
from gh_stars_organizer.organizer import StarsOrganizer
from gh_stars_organizer.reporting import metrics, render_markdown

runner = CliRunner()


def configured(tmp_path: Path, repo):
    cfg = AppConfig(cache={"db_path": tmp_path / "repos.sqlite"},
                    classification={"profile": "scientific"},
                    reporting={"output_path": tmp_path / "stars-insights.md"},
                    local_lists_path=tmp_path / "lists")
    file = tmp_path / "config.yaml"
    save_config(cfg, file)
    db = SQLiteCache(cfg.cache.db_path)
    db.upsert_repositories([repo], complete=True)
    db.close()
    return file


def test_cli_offline_workflow(tmp_path, repo):
    path = configured(tmp_path, repo)
    def cmd(*args):
        return runner.invoke(app, [*args, "--config", str(path)])
    assert cmd("config", "--validate").exit_code == 0
    assert "scientific" in cmd("config", "--show").stdout
    response = cmd("classify", "--explain", repo.full_name)
    assert response.exit_code == 0
    assert "matched_rules" in response.stdout
    response = cmd("preview", "--all")
    assert response.exit_code == 0 and repo.full_name in response.stdout
    response = cmd("search", "numerical", "--language", "Python")
    assert response.exit_code == 0 and repo.full_name in response.stdout
    response = cmd("insights")
    assert response.exit_code == 0
    assert (tmp_path / "stars-insights.md").exists()
    response = cmd("report", "--format", "csv", "--output", str(tmp_path / "report.csv"))
    assert response.exit_code == 0
    assert (tmp_path / "report.csv").exists()
    assert "last sync" in cmd("cache", "status").stdout


def test_cli_config_and_clear(tmp_path):
    conf = tmp_path / "fresh.yaml"
    resp = runner.invoke(app, ["config", "--init", "--config", str(conf)])
    assert resp.exit_code == 0 and conf.exists()
    resp = runner.invoke(app, ["cache", "status", "--config", str(conf)])
    assert resp.exit_code == 0


def test_reports_are_offline(repo):
    from gh_stars_organizer.models import ClassificationResult
    results = {repo.id: ClassificationResult(repo_id=repo.id, categories=["Science"])}
    summary = metrics([repo], results)
    assert summary["total_repositories"] == 1
    assert "Science" in render_markdown(summary)
    assert summary["multi_category"] == 0


def test_local_fallback(tmp_path, repo):
    cfg = AppConfig(cache={"db_path": tmp_path / "cache.db"},
                    classification={"profile": "scientific"},
                    local_lists_path=tmp_path / "output")
    org = StarsOrganizer(cfg)
    org.cache.upsert_repositories([repo], complete=True)
    directory = org.local_lists()
    assert (directory / "index.md").exists()
    assert "No remote GitHub lists were modified" in (directory / "index.md").read_text()
    org.close()


def test_organizer_sync_and_readme_cache(tmp_path, repo):
    class StubGitHub:
        def fetch_starred_repositories(self):
            return [repo]
    cfg = AppConfig(cache={"db_path": tmp_path / "cache.db"})
    org = StarsOrganizer(cfg, github=StubGitHub())
    assert len(org.sync(readme=False)) == 1
    assert len(org.repositories()) == 1
    org.close()


def test_cli_dry_run_nonmutating(tmp_path, repo, monkeypatch):
    path = configured(tmp_path, repo)
    invoked = {"mutation": 0}
    monkeypatch.setattr(GitHubClient, "viewer_login", lambda _: "fake-login")
    monkeypatch.setattr(GitHubClient, "remote_snapshot", lambda _: {"lists": {}, "memberships": {}})
    monkeypatch.setattr(GitHubClient, "create_starred_list", lambda *_: invoked.__setitem__("mutation", invoked["mutation"]+1))
    monkeypatch.setattr(GitHubClient, "set_repository_lists", lambda *_: invoked.__setitem__("mutation", invoked["mutation"]+1))
    output = tmp_path / "plan.json"
    result = runner.invoke(app, ["organize", "--dry-run", "--output", str(output), "--config", str(path)])
    assert result.exit_code == 0, result.stdout
    assert output.exists()
    assert invoked["mutation"] == 0
    assert json.loads(output.read_text())["account"] == "fake-login"


def test_cli_backup_and_verify(tmp_path, repo, monkeypatch):
    path = configured(tmp_path, repo)
    monkeypatch.setattr(GitHubClient, "remote_snapshot", lambda _: {"lists": {"My Lists": "L1"}, "memberships": {repo.id: ["L1"]}})
    backup = tmp_path / "backup.json"
    result = runner.invoke(app, ["backup", "--output", str(backup), "--config", str(path)])
    assert result.exit_code == 0
    assert json.loads(backup.read_text())["memberships"][repo.id] == ["L1"]
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps({"applied": [{"repo_id": repo.id, "repository": repo.full_name, "desired_ids": ["L1"]}]}))
    assert runner.invoke(app, ["verify", "--checkpoint", str(checkpoint), "--config", str(path)]).exit_code == 0


def test_cli_doctor_and_sync(tmp_path, repo, monkeypatch):
    path = configured(tmp_path, repo)
    monkeypatch.setattr(GitHubClient, "viewer_login", lambda _: "sample")
    monkeypatch.setattr(GitHubClient, "remote_snapshot", lambda _: {"lists": {}, "memberships": {}})
    monkeypatch.setattr(GitHubClient, "fetch_starred_repositories", lambda _: [repo])
    assert "sample" in runner.invoke(app, ["doctor", "--config", str(path)]).stdout
    assert runner.invoke(app, ["sync", "--no-readme", "--config", str(path)]).exit_code == 0


def test_cli_apply_with_mocked_remote_state(tmp_path, repo, monkeypatch):
    path = configured(tmp_path, repo)
    state = {"lists": {}, "memberships": {}}
    mutated = []
    monkeypatch.setattr(GitHubClient, "viewer_login", lambda _: "sample")
    monkeypatch.setattr(GitHubClient, "remote_snapshot", lambda _: json.loads(json.dumps(state)))
    def create_list(_, name):
        idx = f"L_{len(state['lists'])}"
        state["lists"][name] = idx
        return idx
    def set_lists(_, repo_id, ids):
        mutated.append(repo_id)
        state["memberships"][repo_id] = sorted(set(ids))
        return state["memberships"][repo_id]
    monkeypatch.setattr(GitHubClient, "create_starred_list", create_list)
    monkeypatch.setattr(GitHubClient, "set_repository_lists", set_lists)
    monkeypatch.chdir(tmp_path)
    plan_path = tmp_path / "plan.json"
    result = runner.invoke(app, ["organize", "--dry-run", "--output", str(plan_path), "--config", str(path)])
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["organize", "--apply", "--plan", str(plan_path), "--yes", "--config", str(path)])
    assert result.exit_code == 0, result.stdout
    assert "Verified" in result.stdout
    assert mutated == [repo.id]
    checkpoints = list((tmp_path / ".gh-stars-organizer-plans").glob("*.checkpoint.json"))
    assert len(checkpoints) == 1
    verified = runner.invoke(app, ["verify", "--checkpoint", str(checkpoints[0]), "--config", str(path)])
    assert verified.exit_code == 0


def test_cli_cache_clear_and_tui_exit(tmp_path, repo, monkeypatch):
    path = configured(tmp_path, repo)
    from rich.prompt import Prompt
    monkeypatch.setattr(Prompt, "ask", lambda *args, **kwargs: "q")
    assert runner.invoke(app, ["tui", "--config", str(path)]).exit_code == 0
    assert runner.invoke(app, ["cache", "clear", "--yes", "--config", str(path)]).exit_code == 0
    assert not (tmp_path / "repos.sqlite").exists()


def test_cli_preview_unclassified_and_bad_report(tmp_path, repo):
    path = configured(tmp_path, repo)
    assert runner.invoke(app, ["preview", "--unclassified", "--config", str(path)]).exit_code == 0
    assert runner.invoke(app, ["report", "--format", "unknown", "--config", str(path)]).exit_code != 0


def test_cli_error_and_validation_branches(tmp_path, repo, monkeypatch):
    path = configured(tmp_path, repo)
    from gh_stars_organizer.github_client import GitHubCLIError, UnsupportedStarLists
    monkeypatch.setattr(GitHubClient, "viewer_login", lambda _: (_ for _ in ()).throw(GitHubCLIError("auth expired")))
    response = runner.invoke(app, ["doctor", "--config", str(path)])
    assert response.exit_code == 1 and "auth expired" in response.stdout
    response = runner.invoke(app, ["classify", "--explain", "missing/repo", "--config", str(path)])
    assert response.exit_code != 0
    response = runner.invoke(app, ["organize", "--apply", "--dry-run", "--config", str(path)])
    assert response.exit_code != 0
    response = runner.invoke(app, ["organize", "--plan", "no.json", "--config", str(path)])
    assert response.exit_code != 0
    monkeypatch.setattr(GitHubClient, "remote_snapshot", lambda _: (_ for _ in ()).throw(UnsupportedStarLists("unsupported")))
    response = runner.invoke(app, ["organize", "--dry-run", "--config", str(path)])
    assert response.exit_code == 0 and "Local categorized lists" in response.stdout


def test_cli_tui_menu_actions(tmp_path, repo, monkeypatch):
    path = configured(tmp_path, repo)
    from rich.prompt import Prompt
    seq = iter(["1", "2", "3", "numerical", "4", "5", "", "q"])
    monkeypatch.setattr(Prompt, "ask", lambda *args, **kwargs: next(seq))
    monkeypatch.setattr(GitHubClient, "fetch_starred_repositories", lambda _: [repo])
    monkeypatch.setattr(GitHubClient, "viewer_login", lambda _: "test")
    monkeypatch.setattr(GitHubClient, "remote_snapshot", lambda _: {"lists": {}, "memberships": {}})
    response = runner.invoke(app, ["tui", "--config", str(path)])
    assert response.exit_code == 0, response.stdout
    assert "Plan:" in response.stdout


def test_cli_default_organize_not_applied(tmp_path, repo, monkeypatch):
    path = configured(tmp_path, repo)
    monkeypatch.setattr(GitHubClient, "viewer_login", lambda _: "sample")
    monkeypatch.setattr(GitHubClient, "remote_snapshot", lambda _: {"lists": {}, "memberships": {}})
    observed = []
    monkeypatch.setattr(GitHubClient, "create_starred_list", lambda *args: observed.append("created"))
    response = runner.invoke(app, ["organize", "--config", str(path)])
    assert response.exit_code == 0
    assert "Dry-run only" in response.stdout
    assert observed == []


def test_cli_migration_and_bad_verify(tmp_path, repo):
    old = tmp_path / "old.yaml"
    old.write_text("model: gpt-4o-mini\ncategories: [Custom]\n")
    response = runner.invoke(app, ["config", "--migrate", "--config", str(old)])
    assert response.exit_code == 0
    assert (tmp_path / "old.migrated.yaml").exists()
    path = configured(tmp_path, repo)
    checkpoint = tmp_path / "missing.json"
    response = runner.invoke(app, ["verify", "--checkpoint", str(checkpoint), "--config", str(path)])
    assert response.exit_code != 0
