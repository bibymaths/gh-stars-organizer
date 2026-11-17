"""Plain, serializable domain entities independent of GitHub and CLI layers."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field

class Repository(BaseModel):
    id: str
    name: str
    owner: str
    full_name: str
    description: str = ""
    topics: list[str] = Field(default_factory=list)
    primary_language: str = ""
    languages: list[str] = Field(default_factory=list)
    readme: str = ""
    stargazer_count: int = 0
    url: str
    updated_at: datetime
    starred_at: datetime | None = None
    archived: bool = False
    is_fork: bool = False
    private: bool = False

class Evidence(BaseModel):
    category: str
    term: str
    field: str
    weight: int
    negative: bool = False

class ClassificationResult(BaseModel):
    repo_id: str
    categories: list[str] = Field(default_factory=list)
    scores: dict[str, int] = Field(default_factory=dict)
    matched_rules: list[Evidence] = Field(default_factory=list)
    override_used: bool = False
    excluded: bool = False
    review_required: bool = False

class SearchResult(BaseModel):
    repository: Repository
    score: float
    categories: list[str] = Field(default_factory=list)
