"""Offline and deterministic summaries; generation timestamp is reporting metadata, not scoring."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .models import ClassificationResult, Repository


def metrics(repos: list[Repository], results: dict[str, ClassificationResult], inactive_months: int = 18) -> dict:
    counts = Counter(x for result in results.values() for x in result.categories)
    langs = Counter(r.primary_language for r in repos if r.primary_language)
    topics = Counter(x for r in repos for x in r.topics)
    cutoff = inactive_months * 30  # documented approximation; not a project-abandonment classifier
    now = datetime.now(UTC)
    return {
        "generated_at": now.isoformat(), "total_repositories": len(repos),
        "categories": dict(counts.most_common()),
        "category_count": len(counts),
        "multi_category": sum(len(results[r.id].categories) > 1 for r in repos),
        "top_languages": dict(langs.most_common(20)), "top_topics": dict(topics.most_common(20)),
        "recently_starred": [r.full_name for r in sorted(repos, key=lambda r: r.starred_at or r.updated_at, reverse=True)[:15]],
        "archived": [r.full_name for r in repos if r.archived],
        "potentially_inactive": [r.full_name for r in repos if (now - r.updated_at).days > cutoff],
        "inactive_threshold_months": inactive_months,
        "unclassified": [r.full_name for r in repos if not results[r.id].categories],
        "ambiguous": [r.full_name for r in repos if results[r.id].review_required],
        "classification_rule_coverage": round(sum(bool(results[r.id].matched_rules or results[r.id].override_used) for r in repos) / max(1, len(repos)), 4),
    }


def render_markdown(stats: dict) -> str:
    lines = ["# GitHub Stars Insights", "", f"Generated: {stats['generated_at']}",
             f"Starred repositories: {stats['total_repositories']}",
             f"Categories used: {stats['category_count']}",
             f"Multi-category repositories: {stats['multi_category']}",
             f"Unclassified: {len(stats['unclassified'])}",
             f"Ambiguous: {len(stats['ambiguous'])}",
             f"Rule coverage: {stats['classification_rule_coverage']:.1%}", ""]
    audit = stats.get("audit", {})
    if audit:
        last = audit.get("last_plan")
        lines.extend(["## Local organization audit", "",
                      f"Recorded applied repository assignments: {audit.get('recorded_applied_assignments', 0)}", ""])
        if last:
            lines += [f"Most recent plan: {last['plan_id']}",
                      f"Existing membership links at planning: {last['existing_memberships']}",
                      f"Proposed additional membership links: {last['proposed_additions']}",
                      f"Proposed list creations: {last['proposed_list_creations']}", ""]
        lines += ["Partial failures and verification results must be inspected in local plan checkpoints.", ""]
    for header, field in [("Categories", "categories"), ("Programming languages", "top_languages"),
                          ("GitHub topics", "top_topics")]:
        lines.extend([f"## {header}", ""])
        lines.extend(f"- {key}: {value}" for key, value in stats[field].items())
        lines.append("")
    for header, field in [("Recently starred", "recently_starred"), ("Archived", "archived"),
                          ("Potentially inactive (not abandoned)", "potentially_inactive"),
                          ("Unclassified", "unclassified"), ("Review required", "ambiguous")]:
        lines.extend([f"## {header}", ""])
        lines.extend(f"- {value}" for value in stats[field])
        lines.append("")
    lines.append(f"Inactivity is based on >{stats['inactive_threshold_months']} months since last GitHub update; this is not evidence of abandonment.")
    return "\n".join(lines) + "\n"


def write_report(path: Path, fmt: str, repos: list[Repository], results: dict[str, ClassificationResult],
                 inactive_months: int, audit: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = metrics(repos, results, inactive_months)
    stats["audit"] = audit or {}
    if fmt == "markdown":
        path.write_text(render_markdown(stats), encoding="utf-8")
    elif fmt == "json":
        payload = {"summary": stats, "repositories": [
            {"repository": r.full_name, "url": r.url, "classification": results[r.id].model_dump(mode="json")}
            for r in repos]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    elif fmt == "csv":
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["repository", "url", "primary_language", "categories", "review_required", "archived"])
            for r in repos:
                c = results[r.id]
                writer.writerow([r.full_name, r.url, r.primary_language, " | ".join(c.categories),
                                 c.review_required, r.archived])
    else:
        raise ValueError("format must be markdown, json or csv")
    return path
