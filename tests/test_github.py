import json
import pytest
from gh_stars_organizer.github_client import GitHubClient, GitHubCLIError


def test_graphql_request_stdin(monkeypatch):
    captured = {}
    def fake_run(cmd, stdin=None, retries=2):
        captured.update({"cmd": cmd, "stdin": json.loads(stdin)})
        return json.dumps({"data": {"viewer": {"login": "example"}}})
    monkeypatch.setattr(GitHubClient, "_run", staticmethod(fake_run))
    client = GitHubClient()
    assert client.viewer_login() == "example"
    assert captured["cmd"] == ["gh", "api", "graphql", "--input", "-"]
    assert "query" in captured["stdin"]


def test_membership_pagination(monkeypatch):
    client = GitHubClient()
    calls = []
    def mock(query, variables=None):
        calls.append(variables)
        if variables["after"] is None:
            return {"node": {"items": {"nodes": [{"id": "R_1"}], "pageInfo": {"hasNextPage": True, "endCursor": "a"}}}}
        return {"node": {"items": {"nodes": [{"id": "R_2"}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
    monkeypatch.setattr(client, "_graphql", mock)
    found = client.get_memberships(["L_1"])
    assert found == {"R_1": ["L_1"], "R_2": ["L_1"]}
    assert len(calls) == 2


def test_membership_incomplete_refused(monkeypatch):
    client = GitHubClient()
    monkeypatch.setattr(client, "_graphql", lambda *args: {"node": {"items": {
        "nodes": [{"id": "R_1"}], "pageInfo": {"hasNextPage": True, "endCursor": None}}}})
    with pytest.raises(GitHubCLIError, match="pagination"):
        client.get_memberships(["L_1"])


def test_mutation_verifies_full_id_set(monkeypatch):
    client = GitHubClient()
    captured = {}
    def mock(query, variables):
        captured["query"] = query
        captured["variables"] = variables
        return {"updateUserListsForItem": {"lists": [{"id": "L_2"}, {"id": "L_1"}]}}
    monkeypatch.setattr(client, "_graphql", mock)
    assert client.set_repository_lists("R_1", ["L_1", "L_2"]) == ["L_1", "L_2"]
    assert captured["variables"]["listIds"] == ["L_1", "L_2"]
    with pytest.raises(GitHubCLIError):
        client.set_repository_lists("R_1", ["L_1"])
