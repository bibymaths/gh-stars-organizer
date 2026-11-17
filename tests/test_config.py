from pathlib import Path
import pytest
from gh_stars_organizer.config import AppConfig, load_config, save_config, migrate_config


def test_default_no_write(tmp_path: Path):
    target = tmp_path / "config.yaml"
    assert load_config(target).classification.profile == "general"
    assert not target.exists()
    save_config(AppConfig(), target)
    assert load_config(target).classification.minimum_score == 5
    with pytest.raises(FileExistsError):
        save_config(AppConfig(), target)


def test_validation():
    with pytest.raises(ValueError):
        AppConfig.model_validate({"classification": {"weights": {"topics": 1}}})
    with pytest.raises(ValueError):
        AppConfig.model_validate({"categories": [{"name": "Duplicate"}, {"name": "duplicate"}]})
    with pytest.raises(ValueError):
        AppConfig.model_validate({"overrides": {"owner/repo": {"categories": ["UNKNOWN"]}}})
    with pytest.raises(ValueError):
        AppConfig.model_validate({"organization": {"remove_obsolete_memberships": True}})
    with pytest.raises(ValueError):
        AppConfig.model_validate({"secret_unknown": "value"})


def test_migrate_ai_config(tmp_path):
    old = tmp_path / "config.yaml"
    old.write_text("model: gpt-4o-mini\napi_key_env: OPENAI_API_KEY\ncategories: [x, y]\n")
    with pytest.raises(ValueError, match="legacy"):
        load_config(old)
    destination = migrate_config(old)
    assert destination.exists()
    assert old.read_text().startswith("model:")
    new = load_config(destination)
    assert [x.name for x in new.categories] == ["x", "y"]
    assert new.classification.profile == "custom"
