from copy import deepcopy
import pytest
from gh_stars_organizer.models import ClassificationResult
from gh_stars_organizer.organization import create_plan, apply_plan, StalePlanError, write_plan, load_plan


def fixture_plan(repo):
    state = {"lists": {"Manual": "L_m", "Existing": "L_e"},
             "memberships": {repo.id: ["L_m"]}}
    result = {repo.id: ClassificationResult(repo_id=repo.id, categories=["Existing", "NewCategory"])}
    return create_plan([repo], result, state, "hash", "account"), state


def test_plan_additive_multilabel(repo):
    plan, state = fixture_plan(repo)
    assert plan["create_lists"] == ["NewCategory"]
    assert plan["changes"][0]["current_ids"] == ["L_m"]
    assert sorted(plan["changes"][0]["add_names"]) == ["Existing", "NewCategory"]
    assert state["memberships"][repo.id] == ["L_m"]


def test_save_load_tamper(tmp_path, repo):
    plan, state = fixture_plan(repo)
    path = tmp_path / "plan.json"
    write_plan(plan, path)
    assert load_plan(path)["plan_id"] == plan["plan_id"]
    with pytest.raises(FileExistsError):
        write_plan(plan, path)
    plan["changes"] = []
    path.write_text(__import__("json").dumps(plan))
    with pytest.raises(ValueError, match="identity"):
        load_plan(path)


class FakeGitHub:
    def __init__(self, state):
        self.state = deepcopy(state)
        self.mutations = []
    def viewer_login(self):
        return "account"
    def remote_snapshot(self):
        return deepcopy(self.state)
    def create_starred_list(self, name):
        value = "L_new"
        self.state["lists"][name] = value
        return value
    def set_repository_lists(self, repo_id, ids):
        self.mutations.append((repo_id, ids))
        self.state["memberships"][repo_id] = ids
        return ids


def test_apply_preserves_manual_and_verifies(tmp_path, repo):
    plan, state = fixture_plan(repo)
    client = FakeGitHub(state)
    result = apply_plan(plan, client, tmp_path, expected_rule_hash="hash")
    assert result["verified"]
    assert client.mutations == [(repo.id, ["L_e", "L_m", "L_new"])]
    assert client.state["memberships"][repo.id] == ["L_e", "L_m", "L_new"]
    assert list(tmp_path.glob("*.checkpoint.json"))


def test_reject_stale_without_mutation(tmp_path, repo):
    plan, state = fixture_plan(repo)
    client = FakeGitHub(state)
    client.state["memberships"][repo.id] = ["L_another"]
    with pytest.raises(StalePlanError, match="changed"):
        apply_plan(plan, client, tmp_path, expected_rule_hash="hash")
    assert client.mutations == []


def test_reject_changed_rules_without_mutation(tmp_path, repo):
    plan, state = fixture_plan(repo)
    client = FakeGitHub(state)
    with pytest.raises(StalePlanError, match="rules"):
        apply_plan(plan, client, tmp_path, expected_rule_hash="other")
    assert client.mutations == []


def test_fails_safely_with_checkpoint_on_mutation_error(tmp_path, repo):
    plan, state = fixture_plan(repo)
    client = FakeGitHub(state)
    def fail(repo_id, ids):
        raise RuntimeError("simulated failure")
    client.set_repository_lists = fail
    with pytest.raises(RuntimeError, match="simulated failure"):
        apply_plan(plan, client, tmp_path, expected_rule_hash="hash")
    checkpoint = list(tmp_path.glob("*.checkpoint.json"))[0]
    contents = __import__("json").loads(checkpoint.read_text())
    assert contents["verified"] is False
    assert contents["created_lists"] == {"NewCategory": "L_new"}
    with pytest.raises(StalePlanError, match="checkpoint"):
        apply_plan(plan, client, tmp_path, expected_rule_hash="hash")


def test_cache_fingerprint_stale(tmp_path, repo):
    plan, state = fixture_plan(repo)
    client = FakeGitHub(state)
    with pytest.raises(StalePlanError, match="repository cache"):
        apply_plan(plan, client, tmp_path, expected_rule_hash="hash", expected_repository_hash="changed")


def test_full_account_reuses_existing_lists_without_creation(repo):
    state = {"lists": {f"List {i}": f"L_{i}" for i in range(32)},
             "memberships": {repo.id: ["L_0"]}}
    result = {repo.id: ClassificationResult(repo_id=repo.id,
              categories=["Scientific Computing", "Numerical Methods", "Missing"])}
    plan = create_plan([repo], result, state, "hash", "account",
                       category_to_list={"Scientific Computing": "List 1",
                                         "Numerical Methods": "List 1"},
                       create_missing_lists=False)
    assert plan["create_lists"] == []
    assert plan["changes"][0]["add_names"] == ["List 1"]
    assert [item["category"] for item in plan["skipped_categories"]] == ["Missing"]
    client = FakeGitHub(state)
    assert client.state["memberships"][repo.id] == ["L_0"]

def test_no_mapping_does_not_create_33rd_list(repo):
    state = {"lists": {f"List {i}": f"L_{i}" for i in range(32)}, "memberships": {}}
    result = {repo.id: ClassificationResult(repo_id=repo.id, categories=["NewCategory"])}
    plan = create_plan([repo], result, state, "hash", "account", create_missing_lists=False)
    assert plan["changes"] == []
    assert plan["create_lists"] == []
    assert len(plan["skipped_categories"]) == 1


def test_unclassified_uses_existing_list_and_preserves_memberships(repo):
    state = {"lists": {"unclassified": "L_u", "Manual": "L_m"},
             "memberships": {repo.id: ["L_m"]}}
    result = {repo.id: ClassificationResult(repo_id=repo.id, categories=[], review_required=True)}
    plan = create_plan([repo], result, state, "hash", "account",
                       create_missing_lists=False, unclassified_list="unclassified")
    assert plan["create_lists"] == []
    assert plan["changes"][0]["add_names"] == ["unclassified"]
    assert plan["changes"][0]["desired_names"] == ["Manual", "unclassified"]


def test_excluded_repository_not_sent_to_fallback(repo):
    state = {"lists": {"unclassified": "L_u"}, "memberships": {}}
    result = {repo.id: ClassificationResult(repo_id=repo.id, excluded=True, categories=[])}
    plan = create_plan([repo], result, state, "hash", "account",
                       create_missing_lists=False, unclassified_list="unclassified")
    assert plan["changes"] == []
