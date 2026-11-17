"""Strict, human-editable configuration and guarded migration of obsolete settings."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .profiles import PROFILES

BASE = Path("~/.gh-stars-organizer").expanduser()

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GithubSettings(StrictModel):
    username: str = "auto"
    authentication: Literal["gh"] = "gh"
    page_size: int = Field(default=100, ge=1, le=100)
    include_private: bool = True

class ClassificationSettings(StrictModel):
    profile: Literal["general", "data", "scientific", "minimal", "custom"] = "general"
    allow_multiple_categories: bool = True
    max_categories_per_repository: int = Field(default=3, ge=1, le=32)
    minimum_score: int = Field(default=5, ge=0)
    score_margin: int = Field(default=0, ge=0)
    review_ambiguous: bool = True
    use_readme: bool = False
    weights: dict[str, int] = Field(default_factory=lambda: {
        "topics": 5, "name": 4, "description": 3,
        "readme_headings": 2, "readme_body": 1, "languages": 1})

    @field_validator("weights")
    @classmethod
    def check_weights(cls, weights: dict[str, int]) -> dict[str, int]:
        allowed = {"topics", "name", "description", "readme_headings", "readme_body", "languages"}
        if set(weights) != allowed or any(isinstance(v, bool) or v < 0 for v in weights.values()):
            raise ValueError("weights must contain all supported fields with nonnegative integers")
        return weights

class Category(StrictModel):
    name: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    synonyms: dict[str, list[str]] = Field(default_factory=dict)
    minimum_score: int | None = Field(default=None, ge=0)
    priority: int = 0

    @field_validator("name")
    @classmethod
    def valid_name(cls, name: str) -> str:
        if not name.strip() or len(name) > 100:
            raise ValueError("category names must be 1-100 characters")
        return name.strip()

class Override(StrictModel):
    categories: list[str] = Field(default_factory=list)
    exclude: bool = False

class OrganizationSettings(StrictModel):
    preserve_existing_lists: bool = True
    preserve_existing_memberships: bool = True
    create_missing_lists: bool = False
    category_to_list: dict[str, str] = Field(default_factory=dict)
    unclassified_list: str | None = None
    remove_obsolete_memberships: bool = False  # reserved; deletion not implemented
    skip_unchanged: bool = True
    require_confirmation: bool = True

    @field_validator("category_to_list")
    @classmethod
    def check_mappings(cls, mapping: dict[str, str]) -> dict[str, str]:
        if any(not k.strip() or not v.strip() for k, v in mapping.items()):
            raise ValueError("category_to_list keys and values cannot be empty")
        return mapping

    @model_validator(mode="after")
    def require_additive(self):
        if (not self.preserve_existing_lists or not self.preserve_existing_memberships
                or self.remove_obsolete_memberships or not self.skip_unchanged):
            raise ValueError("this release supports additive, idempotent, non-destructive organization only")
        return self

class CacheSettings(StrictModel):
    db_path: Path = BASE / "cache.db"
    enabled: bool = True
    incremental_sync: bool = True
    stale_days: int = Field(default=7, ge=0)

    @model_validator(mode="after")
    def require_cache(self):
        if not self.enabled:
            raise ValueError("this offline-first release requires SQLite cache enabled")
        return self

class ReportingSettings(StrictModel):
    markdown: bool = True
    json_export: bool = Field(default=True, alias="json")
    csv: bool = True
    inactive_months: int = Field(default=18, ge=1)
    output_path: Path = Path("stars-insights.md")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

class AppConfig(StrictModel):
    github: GithubSettings = Field(default_factory=GithubSettings)
    classification: ClassificationSettings = Field(default_factory=ClassificationSettings)
    categories: list[Category] = Field(default_factory=list)
    overrides: dict[str, Override] = Field(default_factory=dict)
    organization: OrganizationSettings = Field(default_factory=OrganizationSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)
    local_lists_path: Path = BASE / "lists"

    @model_validator(mode="after")
    def validate_categories(self):
        names = [c.name.casefold() for c in self.resolved_categories()]
        if len(names) != len(set(names)):
            raise ValueError("duplicate category names; profile and custom rules must not conflict")
        for repo, override in self.overrides.items():
            if "/" not in repo or len(repo.split("/")) != 2:
                raise ValueError(f"invalid repository override: {repo}")
            if any(x.casefold() not in names for x in override.categories):
                raise ValueError(f"override references unknown category: {repo}")
        names_by_case = {name.casefold() for name in names}
        unknown = sorted(key for key in self.organization.category_to_list if key.casefold() not in names_by_case)
        if unknown:
            raise ValueError(f"category_to_list references unknown classification categories: {unknown}")
        return self

    def resolved_categories(self) -> list[Category]:
        builtins = [Category(name=name, keywords=terms) for name, terms in PROFILES[self.classification.profile].items()]
        return builtins + self.categories

def default_config_path() -> Path:
    return BASE / "config.yaml"

def load_config(path: Path | None = None, *, create: bool = False) -> AppConfig:
    path = path or default_config_path()
    if not path.exists():
        config = AppConfig()
        if create:
            save_config(config, path)
        return config
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("configuration must be a YAML mapping")
    old = {"model", "embedding_model", "api_base_url", "api_key_env", "faiss_index_path",
           "llm_requests_per_minute", "github_requests_per_minute", "github_page_size",
           "cache_db_path", "insights_report_path", "inactive_months"}
    if set(raw) & old:
        raise ValueError("legacy AI configuration detected; run `config --migrate` to write an explicit migrated copy")
    return AppConfig.model_validate(raw)

def migrate_config(path: Path) -> Path:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("legacy config must be a YAML mapping")
    config = AppConfig()
    if "github_page_size" in raw:
        config.github.page_size = int(raw["github_page_size"])
    if "cache_db_path" in raw:
        config.cache.db_path = Path(raw["cache_db_path"]).expanduser()
    if "insights_report_path" in raw:
        config.reporting.output_path = Path(raw["insights_report_path"]).expanduser()
    if "inactive_months" in raw:
        config.reporting.inactive_months = int(raw["inactive_months"])
    if "local_lists_path" in raw:
        config.local_lists_path = Path(raw["local_lists_path"]).expanduser()
    if "categories" in raw and raw["categories"] and isinstance(raw["categories"][0], str):
        config.classification.profile = "custom"
        # Preserve names; terms need human review rather than infer meanings from category labels.
        config.categories = [Category(name=name) for name in raw["categories"]]
    config = AppConfig.model_validate(config.model_dump())
    destination = path.with_name(path.stem + ".migrated.yaml")
    if destination.exists():
        raise FileExistsError(destination)
    save_config(config, destination)
    return destination

def save_config(config: AppConfig, path: Path | None = None) -> Path:
    path = path or default_config_path()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing config: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config.model_dump(mode="json", by_alias=True), sort_keys=False), encoding="utf-8")
    return path
