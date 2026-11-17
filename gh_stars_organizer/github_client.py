"""GitHub CLI transport and GraphQL Star List snapshots. Never uses browser cookies/PAT prompts."""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime
from typing import Any

from .models import Repository

def safe_error(message: str) -> str:
    message = re.sub(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]+\b|\bgithub_pat_[A-Za-z0-9_]+\b", "[REDACTED]", message)
    return re.sub(r"(?i)Bearer\s+[^\s,]+", "Bearer [REDACTED]", message)

class GitHubCLIError(RuntimeError):
    pass

class UnsupportedStarLists(GitHubCLIError):
    pass

class GitHubClient:
    def __init__(self, page_size: int = 100):
        self.page_size = max(1, min(100, page_size))

    @staticmethod
    def _run(args: list[str], stdin: str | None = None, retries: int = 2) -> str:
        for attempt in range(retries + 1):
            try:
                proc = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=60, check=False)
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                raise GitHubCLIError("GitHub CLI is unavailable or timed out; install `gh` and authenticate") from exc
            if proc.returncode == 0:
                return proc.stdout
            error = safe_error(proc.stderr.strip() or "gh command failed")
            retryable = any(x in error.casefold() for x in ("rate limit", "timeout", "secondary rate", "502", "503"))
            if not retryable or attempt == retries:
                raise GitHubCLIError(error)
            time.sleep(min(2 ** attempt, 4))
        raise AssertionError("unreachable")

    def auth_status(self) -> str:
        return self._run(["gh", "auth", "status"], retries=0)

    def viewer_login(self) -> str:
        data = self._graphql("query { viewer { login } }")
        return data["viewer"]["login"]

    def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        payload = {"query": query, "variables": variables or {}}
        output = self._run(["gh", "api", "graphql", "--input", "-"], json.dumps(payload),
                           retries=0 if query.lstrip().startswith("mutation") else 2)
        try:
            response = json.loads(output)
        except json.JSONDecodeError as exc:
            raise GitHubCLIError("non-JSON response from GitHub GraphQL") from exc
        if response.get("errors"):
            message = str(response["errors"])
            if any(x in message.lower() for x in ("cannot query field 'lists'", "unknown type 'userlist'", "doesn't exist on type 'user'")):
                raise UnsupportedStarLists(message)
            raise GitHubCLIError(safe_error(message))
        if not isinstance(response.get("data"), dict):
            raise GitHubCLIError("GitHub GraphQL returned no data")
        return response["data"]

    def fetch_starred_repositories(self) -> list[Repository]:
        query = '''query($first:Int!,$after:String){viewer{starredRepositories(first:$first,after:$after,orderBy:{field:STARRED_AT,direction:DESC}){
          edges {starredAt node {id name nameWithOwner description url stargazerCount updatedAt isArchived isFork isPrivate
          owner{login} primaryLanguage{name} languages(first:10){nodes{name}}
          repositoryTopics(first:50){nodes{topic{name}}}}}
          pageInfo{hasNextPage endCursor}}}}'''
        cursor = None
        result: list[Repository] = []
        while True:
            data = self._graphql(query, {"first": self.page_size, "after": cursor})
            connection = data["viewer"]["starredRepositories"]
            for edge in connection["edges"]:
                node = edge["node"]
                if not node:
                    continue
                result.append(Repository(
                    id=node["id"], name=node["name"], owner=node["owner"]["login"],
                    full_name=node["nameWithOwner"], description=node.get("description") or "",
                    url=node["url"], topics=[x["topic"]["name"] for x in node["repositoryTopics"]["nodes"]],
                    primary_language=(node.get("primaryLanguage") or {}).get("name") or "",
                    languages=[x["name"] for x in (node.get("languages") or {}).get("nodes", [])],
                    stargazer_count=node["stargazerCount"], updated_at=datetime.fromisoformat(node["updatedAt"].replace("Z", "+00:00")),
                    starred_at=datetime.fromisoformat(edge["starredAt"].replace("Z", "+00:00")) if edge.get("starredAt") else None,
                    archived=node["isArchived"], is_fork=node["isFork"], private=node.get("isPrivate", False)))
            info = connection["pageInfo"]
            if not info["hasNextPage"]:
                return result
            cursor = info.get("endCursor")
            if not cursor:
                raise GitHubCLIError("star pagination incomplete: missing cursor")

    def get_starred_lists(self) -> dict[str, str]:
        query = '''query($after:String){viewer{lists(first:100,after:$after){nodes{id name}pageInfo{hasNextPage endCursor}}}}'''
        cursor = None
        found: dict[str, str] = {}
        while True:
            connection = self._graphql(query, {"after": cursor})["viewer"]["lists"]
            for item in connection["nodes"]:
                if item["name"].casefold() in {x.casefold() for x in found}:
                    raise GitHubCLIError("duplicate remote list names (case-insensitive)")
                found[item["name"]] = item["id"]
            info = connection["pageInfo"]
            if not info["hasNextPage"]:
                return found
            cursor = info.get("endCursor")
            if not cursor:
                raise GitHubCLIError("list pagination incomplete")

    def get_memberships(self, list_ids: list[str]) -> dict[str, list[str]]:
        """Map repo node ID to list IDs; exhaust every list's items pages before any write."""
        query = '''query($listId:ID!,$after:String){node(id:$listId){...on UserList{
          items(first:100,after:$after){nodes{...on Repository{id}}pageInfo{hasNextPage endCursor}}}}}'''
        memberships: dict[str, set[str]] = {}
        for list_id in list_ids:
            cursor = None
            while True:
                node = self._graphql(query, {"listId": list_id, "after": cursor}).get("node")
                if not node or not node.get("items"):
                    raise GitHubCLIError(f"list {list_id} cannot be fully inspected; stopping")
                items = node["items"]
                for entry in items["nodes"]:
                    if entry and entry.get("id"):
                        memberships.setdefault(entry["id"], set()).add(list_id)
                info = items["pageInfo"]
                if not info["hasNextPage"]:
                    break
                cursor = info.get("endCursor")
                if not cursor:
                    raise GitHubCLIError("list membership pagination incomplete")
        return {repo: sorted(ids) for repo, ids in memberships.items()}

    def remote_snapshot(self) -> dict[str, Any]:
        lists = self.get_starred_lists()
        return {"lists": lists, "memberships": self.get_memberships(list(lists.values()))}

    def create_starred_list(self, name: str) -> str:
        mutation = '''mutation($name:String!){createUserList(input:{name:$name,isPrivate:true}){list{id name}}}'''
        result = self._graphql(mutation, {"name": name})["createUserList"]["list"]
        if result["name"] != name:
            raise GitHubCLIError("created list name mismatch")
        return result["id"]

    def set_repository_lists(self, repo_id: str, ids: list[str]) -> list[str]:
        """SET (not ADD) semantics: caller MUST supply existing memberships in `ids`."""
        mutation = '''mutation($repoId:ID!,$listIds:[ID!]!){updateUserListsForItem(input:{itemId:$repoId,listIds:$listIds}){
          lists{id} }}'''
        payload = self._graphql(mutation, {"repoId": repo_id, "listIds": ids})["updateUserListsForItem"]
        if payload.get("lists") is None:
            raise GitHubCLIError("mutation returned no membership verification data")
        observed = sorted(x["id"] for x in payload["lists"])
        if observed != sorted(set(ids)):
            raise GitHubCLIError(f"mutation returned unexpected memberships for {repo_id}")
        return observed
