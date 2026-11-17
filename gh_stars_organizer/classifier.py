"""Explainable, multi-label rule scorer with exact phrase boundaries and no inference calls."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from .config import AppConfig, Category
from .models import ClassificationResult, Evidence, Repository
from .profiles import ALIASES

def normalize(value: str) -> str:
    # Preserve word boundaries, including across dots, hyphens, underscores and slashes.
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", value, re.UNICODE))

def whole_phrase(text: str, phrase: str) -> bool:
    normalized = normalize(phrase)
    return bool(normalized and re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", text))

class RepositoryClassifier:
    def __init__(self, config: AppConfig):
        self.config = config
        self.categories: list[Category] = config.resolved_categories()

    def fingerprint(self) -> str:
        payload = {
            "engine": 2, "classification": self.config.classification.model_dump(mode="json"),
            "categories": [x.model_dump(mode="json") for x in self.categories],
            "overrides": {k: v.model_dump(mode="json") for k, v in self.config.overrides.items()},
            "aliases": ALIASES,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def classify(self, repo: Repository) -> ClassificationResult:
        result = ClassificationResult(repo_id=repo.id)
        override = next((v for k, v in self.config.overrides.items() if k.casefold() == repo.full_name.casefold()), None)
        if override is not None:
            result.override_used = True
            result.excluded = override.exclude
            result.categories = [] if override.exclude else list(dict.fromkeys(override.categories))
            result.review_required = False
            return result
        settings = self.config.classification
        heading_text = "\n".join(line.lstrip("# ") for line in repo.readme.splitlines() if line.lstrip().startswith("#"))
        fields = {
            "topics": " ".join(repo.topics),
            "name": f"{repo.owner} {repo.name}",
            "description": repo.description,
            "readme_headings": heading_text if settings.use_readme else "",
            "readme_body": repo.readme if settings.use_readme else "",
            "languages": " ".join([repo.primary_language, *repo.languages]),
        }
        tokens = {key: normalize(text) for key, text in fields.items()}
        candidates: list[tuple[int, int, str]] = []
        for category in self.categories:
            score = 0
            matches: list[Evidence] = []
            # Negation cancels eligibility; negative evidence is recorded for explanation.
            negative = [(field, word) for field in tokens for word in category.exclude_keywords
                        if whole_phrase(tokens[field], word)]
            if negative:
                result.scores[category.name] = 0
                result.matched_rules.extend(Evidence(category=category.name, term=word, field=field,
                                                     weight=0, negative=True) for field, word in negative)
                continue
            seen: set[tuple[str, str]] = set()
            for term, topic_only in [*((x, False) for x in category.keywords),
                                     *((x, True) for x in category.topics)]:
                variants = [term, *ALIASES.get(normalize(term), []), *category.synonyms.get(term, [])]
                for field in tokens:
                    if topic_only and field != "topics":
                        continue
                    weight = settings.weights[field]
                    identity = (normalize(term), field)
                    if identity in seen or not weight:
                        continue
                    if any(whole_phrase(tokens[field], variant) for variant in variants):
                        seen.add(identity)
                        score += weight
                        matches.append(Evidence(category=category.name, term=term, field=field, weight=weight))
            result.scores[category.name] = score
            result.matched_rules.extend(matches)
            minimum = category.minimum_score if category.minimum_score is not None else settings.minimum_score
            if score >= minimum and (score > 0 or minimum > 0):
                candidates.append((score, category.priority, category.name))
        candidates.sort(key=lambda row: (-row[0], -row[1], row[2].casefold()))
        if candidates:
            high = candidates[0][0]
            valid = [x[2] for x in candidates if high - x[0] <= settings.score_margin] if settings.score_margin else [x[2] for x in candidates]
            max_count = settings.max_categories_per_repository if settings.allow_multiple_categories else 1
            result.categories = valid[:max_count]
            result.review_required = bool(settings.review_ambiguous and len(valid) > max_count)
        else:
            result.review_required = True
        return result
