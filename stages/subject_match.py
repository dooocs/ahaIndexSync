# stages/subject_match.py
"""
Catalog subject matching.

Stage A in the subject pipeline: conservatively link today's processed items to
already approved/public subjects. Unknown subjects still go through
subject_candidates; this stage never creates new subjects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from supabase import Client

from infra.db import enrich_table_names
from pipeline.config_loader import PipelineConfig
from stages.subject import SubjectRegistry


DETECTED_BY = "enrich.catalog_subject_match"

_STOP_TERMS = {
    "ai",
    "ml",
    "llm",
    "api",
    "app",
    "agent",
    "agents",
    "model",
    "models",
    "company",
    "person",
    "product",
    "project",
    "concept",
    "framework",
    "system",
    "research",
}

_FIELD_WEIGHTS = {
    "processed_title": 0.10,
    "raw_title": 0.08,
    "summary": 0.06,
    "expert_insight": 0.04,
    "tags": 0.05,
    "keywords": 0.05,
}

_STRATEGY_BASE = {
    "display_name": 0.82,
    "alias": 0.78,
    "slug": 0.70,
}


@dataclass(frozen=True)
class _Term:
    value: str
    strategy: str


@dataclass(frozen=True)
class _Match:
    subject: dict[str, Any]
    term: str
    field: str
    strategy: str
    confidence: float
    context: str


def _enabled(config: PipelineConfig) -> bool:
    value = config.get_param("subject_match_enabled", True)
    if isinstance(value, str):
        return value.lower() not in ("false", "0", "no", "off", "")
    return bool(value)


def _is_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _compact_ascii(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _term_allowed(term: str) -> bool:
    t = term.strip()
    if not t:
        return False
    lowered = t.lower()
    if lowered in _STOP_TERMS:
        return False

    if _is_cjk(t):
        cjk_count = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
        return cjk_count >= 2 or len(_compact_ascii(t)) >= 4

    return len(_compact_ascii(t)) >= 3


def _slug_terms(slug: str) -> list[str]:
    if not slug or ":" not in slug:
        return []
    raw = slug.split(":", 1)[1].strip()
    if not raw:
        return []
    variants = {raw, raw.replace("-", " "), raw.replace("_", " ")}
    if "/" in raw:
        variants.add(raw.rsplit("/", 1)[-1])
    return [v for v in variants if _term_allowed(v)]


def _subject_terms(subject: dict[str, Any]) -> list[_Term]:
    seen: set[str] = set()
    terms: list[_Term] = []

    def add(value: Any, strategy: str) -> None:
        if not isinstance(value, str):
            return
        v = value.strip()
        key = v.lower()
        if not _term_allowed(v) or key in seen:
            return
        seen.add(key)
        terms.append(_Term(v, strategy))

    add(subject.get("display_name"), "display_name")
    for alias in subject.get("aliases") or []:
        add(alias, "alias")
    for term in _slug_terms(subject.get("slug") or ""):
        add(term, "slug")

    metadata = subject.get("metadata") or {}
    if isinstance(metadata, dict):
        for key in ("canonical_name", "name", "ticker", "repo_full_name"):
            add(metadata.get(key), "alias")

    return terms


def _iter_item_fields(item: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for key in ("processed_title", "raw_title", "summary", "expert_insight"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            fields.append((key, value.strip()))

    for key in ("tags", "keywords"):
        value = item.get(key)
        if isinstance(value, list):
            text = " ".join(str(v) for v in value if v)
            if text.strip():
                fields.append((key, text.strip()))

    return fields


def _contains_term(text: str, term: str) -> bool:
    if not text or not term:
        return False

    if _is_cjk(term):
        return term.lower() in text.lower()

    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
    return bool(pattern.search(text))


def _snippet(text: str, term: str, max_len: int = 240) -> str:
    if len(text) <= max_len:
        return text
    idx = text.lower().find(term.lower())
    if idx < 0:
        return text[:max_len]
    start = max(0, idx - 80)
    end = min(len(text), idx + len(term) + 120)
    return text[start:end]


def _confidence(term: _Term, field: str, subject_type: str) -> float:
    score = _STRATEGY_BASE.get(term.strategy, 0.70) + _FIELD_WEIGHTS.get(field, 0.0)
    if field in ("tags", "keywords") and subject_type in ("concept", "agent", "task", "model"):
        score += 0.03
    if subject_type in ("company", "person") and term.strategy == "slug":
        score -= 0.08
    return round(max(0.0, min(0.98, score)), 2)


def _load_visible_subjects(sb: Client, table_suffix: str, limit: int) -> list[dict[str, Any]]:
    _, subjects_table, _, _ = enrich_table_names(table_suffix)
    try:
        rows = (
            sb.table(subjects_table)
            .select(
                "id, slug, type, display_name, aliases, description, definition, homepage_url, "
                "metadata, status, directory_visible, section_slug, curation_priority"
            )
            .eq("status", "active")
            .eq("directory_visible", True)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as e:
        print(f"  ⚠️ catalog subject 加载失败: {e}")
        return []

    subjects = []
    for row in rows:
        terms = _subject_terms(row)
        if not terms:
            continue
        row["_match_terms"] = terms
        subjects.append(row)
    return subjects


def _find_subject_matches(
    item: dict[str, Any],
    subjects: list[dict[str, Any]],
    min_confidence: float,
) -> list[_Match]:
    fields = _iter_item_fields(item)
    if not fields:
        return []

    matches: list[_Match] = []
    for subject in subjects:
        best: _Match | None = None
        subject_type = subject.get("type") or ""
        for term in subject.get("_match_terms") or []:
            for field, text in fields:
                if not _contains_term(text, term.value):
                    continue
                confidence = _confidence(term, field, subject_type)
                if confidence < min_confidence:
                    continue
                candidate = _Match(
                    subject=subject,
                    term=term.value,
                    field=field,
                    strategy=term.strategy,
                    confidence=confidence,
                    context=_snippet(text, term.value),
                )
                if best is None or candidate.confidence > best.confidence:
                    best = candidate
        if best:
            matches.append(best)
    return matches


def run_catalog_subject_match(
    sb: Client,
    config: PipelineConfig,
    items: list[dict[str, Any]],
    registry: SubjectRegistry,
    snapshot_date: str,
    table_suffix: str = "",
) -> dict[str, Any]:
    if not _enabled(config):
        print("⏭️  subject_match_enabled=false，跳过 catalog subject 匹配")
        return {"skipped": True, "mentions": 0, "matches": 0, "subjects_loaded": 0}

    if not items:
        return {"skipped": True, "mentions": 0, "matches": 0, "subjects_loaded": 0}

    min_confidence = float(config.get_param("subject_match_min_confidence", 0.65))
    max_subjects = int(config.get_param("subject_match_max_subjects", 500))

    subjects = _load_visible_subjects(sb, table_suffix, max_subjects)
    if not subjects:
        print("✅ 无可匹配 catalog subject，跳过")
        return {"skipped": True, "mentions": 0, "matches": 0, "subjects_loaded": 0}

    matches_total = 0
    mentions = 0
    for item in items:
        item_id = item.get("item_id")
        if not item_id:
            continue
        item_matches = _find_subject_matches(item, subjects, min_confidence)
        matches_total += len(item_matches)
        seen_subjects: set[str] = set()
        for match in item_matches:
            subject_id = match.subject.get("id")
            if not subject_id or subject_id in seen_subjects:
                continue
            seen_subjects.add(subject_id)
            if registry.record_mention(
                subject_id=subject_id,
                item_id=item_id,
                snapshot_date=snapshot_date,
                role="mentioned",
                source_name=item.get("source_name"),
                score=item.get("aha_index"),
                context=match.context,
                detected_by=DETECTED_BY,
                confidence=match.confidence,
                evidence={
                    "subject_slug": match.subject.get("slug"),
                    "subject_type": match.subject.get("type"),
                    "matched_term": match.term,
                    "matched_field": match.field,
                    "match_strategy": match.strategy,
                    "source_url": item.get("original_url"),
                    "item_title": item.get("processed_title") or item.get("raw_title"),
                },
            ):
                mentions += 1

    print(
        f"🔗 Catalog Subject 匹配完成: subjects={len(subjects)} "
        f"matches={matches_total} mentions={mentions}"
    )
    return {
        "skipped": False,
        "mentions": mentions,
        "matches": matches_total,
        "subjects_loaded": len(subjects),
    }
