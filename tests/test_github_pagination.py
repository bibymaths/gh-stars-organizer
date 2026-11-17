import json
import subprocess
import pytest
from gh_stars_organizer.github_client import GitHubClient, GitHubCLIError, UnsupportedStarLists


def test_stars_paginate_and_preserve_metadata(monkeypatch):
    client = GitHubClient(page_size=1)
    calls = []
    def graphql(query, variables=None):
        calls.append(variables)
        if variables["after"] is None:
            node = {"id": "R1", "name": "repo", "nameWithOwner": "test/repo",
                    "description": "desc", "url": "https://github.com/test/repo",
                    "stargazerCount": 3, "updatedAt": "2026-01-01T00:00:00Z",
                    "isArchived": False, "isFork": False, "isPrivate": True,
                    "owner": {"login": "test"}, "primaryLanguage": {"name": "Python"},
                    "languages": {"nodes": [{"name": "Python"}, {"name": "Rust"}]},
                    "repositoryTopics": {"nodes": [{"topic": {"name": "cli"}}]}}
            return {"viewer": {"starredRepositories": {"edges": [{"starredAt": "2026-02-01T00:00:00Z", "node": node}],
                "pageInfo": {"hasNextPage": True, "endCursor": "next"}}}}
        return {"viewer": {"starredRepositories": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
    monkeypatch.setattr(client, "_graphql", graphql)
    repos = client.fetch_starred_repositories()
    assert len(repos) == 1 and repos[0].private
    assert repos[0].languages == ["Python", "Rust"]
    assert repos[0].starred_at is not None
    assert len(calls) == 2


def test_lists_pagination(monkeypatch):
    client = GitHubClient()
    def graphql(query, variables=None):
        first = variables["after"] is None
        return {"viewer": {"lists": {"nodes": [{"id": "L1" if first else "L2", "name": "A" if first else "B"}],
                "pageInfo": {"hasNextPage": first, "endCursor": "next" if first else None}}}}
    monkeypatch.setattr(client, "_graphql", graphql)
    assert client.get_starred_lists() == {"A": "L1", "B": "L2"}


def test_graphql_reports_unsupported_schema(monkeypatch):
    client = GitHubClient()
    monkeypatch.setattr(GitHubClient, "_run", staticmethod(lambda *args, **kwargs: json.dumps({"errors": [{"message": "Cannot query field 'lists' on type 'User'"}]})))
    with pytest.raises(UnsupportedStarLists):
        client._graphql("query {}")


def test_missing_github_executable(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(GitHubCLIError, match="unavailable"):
        GitHubClient._run(["gh", "auth", "status"])


def test_github_failure_paths(monkeypatch):
    client = GitHubClient()
    monkeypatch.setattr(GitHubClient, "_run", staticmethod(lambda *args, **kwargs: "not JSON"))
    with pytest.raises(GitHubCLIError, match="non-JSON"):
        client._graphql("query {}")
    monkeypatch.setattr(GitHubClient, "_run", staticmethod(lambda *args, **kwargs: json.dumps({"data": None})))
    with pytest.raises(GitHubCLIError, match="no data"):
        client._graphql("query {}")
    monkeypatch.setattr(GitHubClient, "_run", staticmethod(lambda *args, **kwargs: json.dumps({"errors": [{"message": "INSUFFICIENT_SCOPES"}]})))
    with pytest.raises(GitHubCLIError, match="SCOPES"):
        client._graphql("query {}")


def test_create_list_and_mutation_verification(monkeypatch):
    client = GitHubClient()
    monkeypatch.setattr(client, "_graphql", lambda q, variables: {"createUserList": {"list": {"id": "L1", "name": "Wrong"}}})
    with pytest.raises(GitHubCLIError, match="name mismatch"):
        client.create_starred_list("Expected")
    monkeypatch.setattr(client, "_graphql", lambda q, variables: {"createUserList": {"list": {"id": "L1", "name": variables["name"]}}})
    assert client.create_starred_list("Expected") == "L1"


def test_list_duplicate_name_is_error(monkeypatch):
    client = GitHubClient()
    monkeypatch.setattr(client, "_graphql", lambda *_: {"viewer": {"lists": {
        "nodes": [{"name": "A", "id": "L1"}, {"name": "a", "id": "L2"}],
        "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
    with pytest.raises(GitHubCLIError, match="duplicate"):
        client.get_starred_lists()


def test_run_retries_reads_not_mutations(monkeypatch):
    calls = []
    class Proc:
        def __init__(self, code, err=""):
            self.returncode = code
            self.stderr = err
            self.stdout = json.dumps({"data": {"viewer": {"login": "ok"}}})
    def process(*args, **kwargs):
        calls.append(kwargs.get("input", ""))
        return Proc(503 if len(calls) == 1 else 0, "503 service unavailable" if len(calls) == 1 else "")
    monkeypatch.setattr(subprocess, "run", process)
    monkeypatch.setattr("gh_stars_organizer.github_client.time.sleep", lambda *_: None)
    assert GitHubClient().viewer_login() == "ok"
    assert len(calls) == 2
    calls.clear()
    with pytest.raises(GitHubCLIError):
        GitHubClient()._graphql("mutation {mock}")
    assert len(calls) == 1
