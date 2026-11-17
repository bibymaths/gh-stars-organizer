"""Snapshot-based additive plan, stale-state guard, checkpointing and verification."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .github_client import GitHubCLIError, GitHubClient
from .models import ClassificationResult, Repository

class StalePlanError(RuntimeError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def create_plan(repos: list[Repository], results: dict[str, ClassificationResult], snapshot: dict,
                rule_hash: str, account: str) -> dict:
    """No GitHub write; current list memberships included in every intended assignment."""
    existing = snapshot["lists"]
    current = snapshot["memberships"]
    casefold = {name.casefold(): name for name in existing}
    required: set[str] = set()
    changes: list[dict] = []
    for repo in sorted(repos, key=lambda r: r.full_name.casefold()):
        classification = results[repo.id]
        if classification.excluded or not classification.categories:
            continue
        proposed = classification.categories
        target_names = sorted((casefold.get(name.casefold(), name) for name in proposed), key=str.casefold)
        required.update(target_names)
        current_ids = sorted(set(current.get(repo.id, [])))
        current_names = sorted((name for name, list_id in existing.items() if list_id in current_ids), key=str.casefold)
        missing = sorted(set(target_names) - set(current_names), key=str.casefold)
        if missing:
            changes.append({"repo_id": repo.id, "repository": repo.full_name,
                            "current_ids": current_ids, "current_names": current_names,
                            "add_names": missing, "desired_names": sorted(set(current_names) | set(target_names), key=str.casefold)})
    creates = sorted((name for name in required if name.casefold() not in casefold), key=str.casefold)
    plan = {"schema": 1, "account": account, "created_at": datetime.now(UTC).isoformat(),
            "rule_hash": rule_hash, "repository_hash": digest([r.model_dump(mode="json") for r in sorted(repos, key=lambda r: r.full_name.casefold())]),
            "snapshot": snapshot, "snapshot_hash": digest(snapshot),
            "create_lists": creates, "changes": changes}
    plan["plan_id"] = digest({k: v for k, v in plan.items() if k != "created_at"})
    return plan


def write_plan(plan: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"will not overwrite plan: {path}")
    path.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(path, 0o600)


def load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("schema") != 1 or plan.get("snapshot_hash") != digest(plan.get("snapshot")):
        raise ValueError("invalid, corrupted or unsupported plan")
    expected = digest({k: v for k, v in plan.items() if k not in {"plan_id", "created_at"}})
    if plan.get("plan_id") != expected:
        raise ValueError("plan identity mismatch")
    return plan


def apply_plan(plan: dict, client: GitHubClient, output_dir: Path, *, expected_rule_hash: str,
               expected_repository_hash: str | None = None,
               on_applied: Callable[[str, list[str]], None] | None = None) -> dict:
    """Conservative single-session apply; checkpoint partial operations, never delete lists."""
    if plan["rule_hash"] != expected_rule_hash:
        raise StalePlanError("rules changed since plan creation; generate a new plan")
    if expected_repository_hash is not None and plan["repository_hash"] != expected_repository_hash:
        raise StalePlanError("repository cache changed since plan creation; refresh plan")
    if client.viewer_login() != plan["account"]:
        raise StalePlanError("GitHub account differs from the account in the plan")
    output_dir.mkdir(parents=True, exist_ok=True)
    backup = output_dir / f"{plan['plan_id']}.before.json"
    checkpoint = output_dir / f"{plan['plan_id']}.checkpoint.json"
    if backup.exists() or checkpoint.exists():
        raise StalePlanError("existing checkpoint for this plan; inspect recovery file before retrying")
    remote = client.remote_snapshot()
    if digest(remote) != plan["snapshot_hash"]:
        raise StalePlanError("remote memberships/lists changed since preview; generate a new plan")
    backup.write_text(json.dumps(remote, indent=2, sort_keys=True))
    os.chmod(backup, 0o600)
    state = {"plan_id": plan["plan_id"], "created_lists": {}, "applied": [], "failures": []}

    def save():
        checkpoint.write_text(json.dumps(state, indent=2, sort_keys=True))
        os.chmod(checkpoint, 0o600)

    save()
    try:
        names = dict(remote["lists"])
        casefold = {k.casefold(): k for k in names}
        for name in plan["create_lists"]:
            if name.casefold() in casefold:
                raise StalePlanError("planned list now exists; refusing to continue")
            list_id = client.create_starred_list(name)
            names[name] = list_id
            casefold[name.casefold()] = name
            state["created_lists"][name] = list_id
            save()
        # Re-fetch after creation to ensure no unexpected divergence before mutations.
        revised = client.remote_snapshot()
        expected = {"lists": names, "memberships": remote["memberships"]}
        if digest(revised) != digest(expected):
            raise StalePlanError("remote state changed during list creation")
        for change in plan["changes"]:
            # A remote read before *every* set operation prevents overwriting
            # memberships added manually or by another process mid-run.
            live = client.remote_snapshot()
            if digest(live) != digest(revised):
                raise StalePlanError("remote state changed during application; refusing to overwrite memberships")
            repo_id = change["repo_id"]
            current_set = set(live["memberships"].get(repo_id, []))
            if current_set != set(change["current_ids"]):
                raise StalePlanError("membership drift detected before mutation")
            desired = sorted(current_set | {names[casefold[name.casefold()]] for name in change["add_names"]})
            observed = client.set_repository_lists(repo_id, desired)
            if sorted(observed) != desired:
                raise GitHubCLIError(f"postmutation state unexpected for {change['repository']}")
            revised["memberships"][repo_id] = desired
            state["applied"].append({"repo_id": repo_id, "repository": change["repository"], "desired_ids": desired})
            save()
            if on_applied is not None:
                on_applied(repo_id, desired)
        verified = client.remote_snapshot()
        if digest(verified) != digest(revised):
            raise GitHubCLIError("final remote snapshot differs from intended state; see checkpoint")
        state["verified"] = True
        save()
        return state
    except Exception as exc:
        state["failures"].append(str(exc))
        state["verified"] = False
        save()
        raise
