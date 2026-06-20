# stages/subject_insights.py
"""
Subject insight generation.

Stage B in the subject pipeline: turn subject_mentions plus display evidence into
the public read model consumed by ahaIndex2 subject detail pages.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from supabase import Client

from infra.db import enrich_table_names, table_names
from pipeline.config_loader import PipelineConfig


GENERATOR_VERSION = "subject_insights.v1"
LLM_PROMPT_NAME = "subject_insights_generate"


def call_llm(*args, **kwargs):
    from infra.llm import call_llm as _call_llm

    return _call_llm(*args, **kwargs)


def _param_bool(config: PipelineConfig, key: str, default: bool) -> bool:
    value = config.get_param(key, default)
    if isinstance(value, str):
        return value.lower() not in ("false", "0", "no", "off", "")
    return bool(value)


def _chunks(values: list[str], size: int = 500):
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _load_visible_subjects(sb: Client, limit: int) -> list[dict[str, Any]]:
    try:
        rows = (
            sb.table("subjects")
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
        print(f"  ⚠️ subject_insights 加载 subjects 失败: {e}")
        return []
    return rows


def _load_mentions(
    sb: Client,
    subject_ids: list[str],
    start_date: str,
    end_date: str,
    table_suffix: str,
) -> list[dict[str, Any]]:
    if not subject_ids:
        return []
    _, _, subject_mentions_table, _ = enrich_table_names(table_suffix)
    rows: list[dict[str, Any]] = []
    try:
        for batch in _chunks(subject_ids):
            batch_rows = (
                sb.table(subject_mentions_table)
                .select("subject_id, item_id, snapshot_date, role, source_name, score, context, detected_by, confidence, evidence")
                .in_("subject_id", batch)
                .gte("snapshot_date", start_date)
                .lte("snapshot_date", end_date)
                .execute()
                .data
                or []
            )
            rows.extend(batch_rows)
    except Exception as e:
        print(f"  ⚠️ subject_insights 加载 mentions 失败: {e}")
        return []
    return rows


def _load_display_items(sb: Client, item_ids: list[str], table_suffix: str) -> dict[tuple[str, str], dict[str, Any]]:
    if not item_ids:
        return {}
    _, _, display_table, _ = table_names(table_suffix)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        for batch in _chunks(item_ids):
            data = (
                sb.table(display_table)
                .select(
                    "processed_item_id, snapshot_date, rank, processed_title, summary, expert_insight, "
                    "source_name, content_type, original_url, tags, aha_index, extra"
                )
                .in_("processed_item_id", batch)
                .execute()
                .data
                or []
            )
            for row in data:
                rows[(row["processed_item_id"], str(row["snapshot_date"]))] = row
    except Exception as e:
        print(f"  ⚠️ subject_insights 加载 display_items 失败: {e}")
    return rows


def _load_processed_items(sb: Client, item_ids: list[str], table_suffix: str) -> dict[tuple[str, str], dict[str, Any]]:
    if not item_ids:
        return {}
    _, processed_table, _, _ = table_names(table_suffix)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        for batch in _chunks(item_ids):
            data = (
                sb.table(processed_table)
                .select(
                    "item_id, snapshot_date, processed_title, raw_title, summary, expert_insight, "
                    "source_name, content_type, original_url, tags, keywords, aha_index, extra"
                )
                .in_("item_id", batch)
                .execute()
                .data
                or []
            )
            for row in data:
                rows[(row["item_id"], str(row["snapshot_date"]))] = row
    except Exception as e:
        print(f"  ⚠️ subject_insights 加载 processed_items 失败: {e}")
    return rows


def _evidence_records(
    mentions: list[dict[str, Any]],
    display_by_key: dict[tuple[str, str], dict[str, Any]],
    processed_by_key: dict[tuple[str, str], dict[str, Any]],
    max_items_per_subject: int,
) -> dict[str, list[dict[str, Any]]]:
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mention in mentions:
        item_id = mention.get("item_id")
        snapshot_date = str(mention.get("snapshot_date") or "")
        if not item_id or not snapshot_date:
            continue
        key = (item_id, snapshot_date)
        item = display_by_key.get(key) or processed_by_key.get(key)
        if not item:
            continue
        title = item.get("processed_title") or item.get("raw_title") or ""
        if not title:
            continue
        is_display = key in display_by_key
        by_subject[mention["subject_id"]].append({
            "mention": mention,
            "item": item,
            "item_id": item_id,
            "snapshot_date": snapshot_date,
            "title": title,
            "summary": item.get("summary") or "",
            "analysis": item.get("expert_insight") or "",
            "source_name": item.get("source_name") or mention.get("source_name"),
            "original_url": item.get("original_url"),
            "score": item.get("aha_index") if item.get("aha_index") is not None else mention.get("score"),
            "rank": item.get("rank"),
            "is_display": is_display,
        })

    for subject_id, rows in by_subject.items():
        rows.sort(key=_record_sort_key, reverse=True)
        by_subject[subject_id] = rows[:max_items_per_subject]
    return by_subject


def _record_sort_key(row: dict[str, Any]) -> tuple:
    rank = row.get("rank")
    rank_value = int(rank) if isinstance(rank, int) else 10_000
    score = float(row.get("score") or 0)
    return (
        str(row.get("snapshot_date") or ""),
        1 if row.get("is_display") else 0,
        score,
        -rank_value,
    )


def _published_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _importance(record: dict[str, Any]) -> float:
    score = float(record.get("score") or 0)
    if record.get("rank"):
        rank_boost = max(0.0, 0.12 - (int(record["rank"]) * 0.01))
    else:
        rank_boost = 0.0
    return round(max(0.0, min(1.0, score + rank_boost)), 2)


def _evidence_refs(record: dict[str, Any]) -> dict[str, Any]:
    return _evidence_refs_many([record])


def _evidence_refs_many(records: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for record in records:
        mention = record.get("mention") or {}
        items.append({
            "item_id": record.get("item_id"),
            "snapshot_date": record.get("snapshot_date"),
            "source_name": record.get("source_name"),
            "source_url": record.get("original_url"),
            "score": record.get("score"),
            "rank": record.get("rank"),
            "detected_by": mention.get("detected_by"),
            "confidence": mention.get("confidence"),
            "evidence": mention.get("evidence") or {},
        })
    return {"items": items}


def _max_importance(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.5
    return max(_importance(record) for record in records)


def _max_confidence(records: list[dict[str, Any]]) -> float | None:
    values = []
    for record in records:
        value = record.get("mention", {}).get("confidence")
        if value is not None:
            values.append(float(value))
    return max(values) if values else None


def _clamp_score(value: Any, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return round(max(0.0, min(1.0, score)), 2)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _text(value: Any, max_len: int, fallback: str = "") -> str:
    text = str(value or fallback or "").strip()
    return text[:max_len]


def _records_for_indexes(records: list[dict[str, Any]], indexes: Any) -> list[dict[str, Any]]:
    selected = []
    seen: set[str] = set()
    for index in _as_list(indexes):
        try:
            pos = int(index) - 1
        except (TypeError, ValueError):
            continue
        if pos < 0 or pos >= len(records):
            continue
        record = records[pos]
        key = f"{record.get('item_id')}:{record.get('snapshot_date')}"
        if key in seen:
            continue
        seen.add(key)
        selected.append(record)
    return selected


def _subject_brief(subject: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": subject.get("id"),
        "slug": subject.get("slug"),
        "type": subject.get("type"),
        "display_name": subject.get("display_name"),
        "aliases": subject.get("aliases") or [],
        "description": subject.get("description") or "",
        "definition": subject.get("definition") or "",
    }


def _record_brief(record: dict[str, Any], index: int) -> dict[str, Any]:
    mention = record.get("mention") or {}
    return {
        "index": index,
        "item_id": record.get("item_id"),
        "snapshot_date": record.get("snapshot_date"),
        "title": _text(record.get("title"), 180),
        "summary": _text(record.get("summary"), 400),
        "analysis": _text(record.get("analysis"), 600),
        "source_name": record.get("source_name"),
        "source_url": record.get("original_url"),
        "score": record.get("score"),
        "rank": record.get("rank"),
        "confidence": mention.get("confidence"),
        "match_evidence": mention.get("evidence") or {},
    }


def _item_subject_index(
    mentions: list[dict[str, Any]],
    subject_map: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], set[str]]:
    item_subjects: dict[tuple[str, str], set[str]] = defaultdict(set)
    for mention in mentions:
        item_id = mention.get("item_id")
        snapshot_date = str(mention.get("snapshot_date") or "")
        subject_id = mention.get("subject_id")
        if item_id and snapshot_date and subject_id in subject_map:
            item_subjects[(item_id, snapshot_date)].add(subject_id)
    return item_subjects


def _related_subjects_for_prompt(
    subject: dict[str, Any],
    records: list[dict[str, Any]],
    subject_map: dict[str, dict[str, Any]],
    item_subjects: dict[tuple[str, str], set[str]],
) -> list[dict[str, Any]]:
    sid = subject["id"]
    co_counter: Counter[str] = Counter()
    evidence_by_subject: dict[str, list[str]] = defaultdict(list)
    for record in records:
        key = (record["item_id"], record["snapshot_date"])
        for other_id in item_subjects.get(key, set()) - {sid}:
            co_counter[other_id] += 1
            evidence_by_subject[other_id].append(record["item_id"])

    related = []
    for other_id, count in co_counter.most_common(8):
        other = subject_map.get(other_id)
        if not other:
            continue
        related.append({
            "subject_id": other_id,
            "display_name": other.get("display_name"),
            "slug": other.get("slug"),
            "type": other.get("type"),
            "co_mention_count": count,
            "evidence_item_ids": list(dict.fromkeys(evidence_by_subject[other_id]))[:5],
        })
    return related


def _resolve_related_ids(value: Any, related_subjects: list[dict[str, Any]]) -> list[str]:
    if not value:
        return []
    by_id = {r["subject_id"]: r["subject_id"] for r in related_subjects if r.get("subject_id")}
    by_name = {
        str(r.get("display_name") or "").strip().lower(): r["subject_id"]
        for r in related_subjects
        if r.get("display_name") and r.get("subject_id")
    }
    out = []
    for raw in _as_list(value):
        key = str(raw or "").strip()
        if not key:
            continue
        subject_id = by_id.get(key) or by_name.get(key.lower())
        if subject_id and subject_id not in out:
            out.append(subject_id)
    return out


def _llm_highlight_row(
    subject: dict[str, Any],
    payload: dict[str, Any],
    records: list[dict[str, Any]],
    snapshot_date: str,
) -> dict[str, Any] | None:
    evidence = _records_for_indexes(records, payload.get("evidence_indexes"))
    if not evidence:
        return None
    best = evidence[0]
    title = _text(payload.get("title"), 180, f"{subject['display_name']} 的阶段观察")
    summary = _text(payload.get("summary"), 500, best.get("summary") or best["title"])
    analysis = _text(payload.get("analysis"), 1200)
    if not summary:
        return None
    return {
        "subject_id": subject["id"],
        "snapshot_date": snapshot_date,
        "module_type": "highlight",
        "insight_key": "highlight:recent-top",
        "title": title,
        "summary": summary,
        "analysis": analysis or None,
        "event_date": payload.get("event_date") or best["snapshot_date"],
        "comparison_subject_ids": [],
        "dimensions_json": {
            "generation_mode": "llm",
            "evidence_count": len(evidence),
            "item_titles": [record["title"] for record in evidence[:5]],
        },
        "importance_score": _clamp_score(payload.get("importance_score"), _max_importance(evidence)),
        "confidence": _max_confidence(evidence),
        "evidence_item_ids": list(dict.fromkeys(record["item_id"] for record in evidence)),
        "evidence_refs_json": _evidence_refs_many(evidence),
        "related_subject_ids": [],
        "generated_by": "pipeline_llm",
        "generator_version": GENERATOR_VERSION,
        "status": "published",
        "published_at": _published_at(),
    }


def _llm_comparison_rows(
    subject: dict[str, Any],
    payloads: Any,
    records: list[dict[str, Any]],
    related_subjects: list[dict[str, Any]],
    snapshot_date: str,
) -> list[dict[str, Any]]:
    rows = []
    for idx, payload in enumerate(_as_list(payloads), start=1):
        if not isinstance(payload, dict):
            continue
        related_ids = _resolve_related_ids(
            payload.get("comparison_subject_ids") or payload.get("related_subject_ids") or payload.get("comparison_subject_names"),
            related_subjects,
        )
        if not related_ids:
            continue
        evidence = _records_for_indexes(records, payload.get("evidence_indexes"))
        if not evidence:
            continue
        digest = hashlib.md5(",".join(sorted(related_ids)).encode()).hexdigest()[:12]
        title = _text(payload.get("title"), 180, f"{subject['display_name']} 的关联观察")
        summary = _text(payload.get("summary"), 500)
        analysis = _text(payload.get("analysis"), 1200)
        if not summary:
            continue
        rows.append({
            "subject_id": subject["id"],
            "snapshot_date": snapshot_date,
            "module_type": "comparison",
            "insight_key": f"comparison:recent-co-mentions:{digest}",
            "title": title,
            "summary": summary,
            "analysis": analysis or None,
            "event_date": payload.get("event_date") or snapshot_date,
            "comparison_subject_ids": related_ids,
            "dimensions_json": {
                "generation_mode": "llm",
                "comparison_index": idx,
                "related_subjects": [
                    r for r in related_subjects if r.get("subject_id") in related_ids
                ],
            },
            "importance_score": _clamp_score(payload.get("importance_score"), _max_importance(evidence)),
            "confidence": _max_confidence(evidence),
            "evidence_item_ids": list(dict.fromkeys(record["item_id"] for record in evidence))[:10],
            "evidence_refs_json": _evidence_refs_many(evidence),
            "related_subject_ids": related_ids,
            "generated_by": "pipeline_llm",
            "generator_version": GENERATOR_VERSION,
            "status": "published",
            "published_at": _published_at(),
        })
    return rows


def _llm_subject_rows(
    subject: dict[str, Any],
    records: list[dict[str, Any]],
    related_subjects: list[dict[str, Any]],
    prompt_cfg: Any,
    api_key: str,
    snapshot_date: str,
) -> list[dict[str, Any]] | None:
    prompt = prompt_cfg.render(
        snapshot_date=snapshot_date,
        subject_json=json.dumps(_subject_brief(subject), ensure_ascii=False),
        evidence_json=json.dumps(
            [_record_brief(record, idx) for idx, record in enumerate(records, start=1)],
            ensure_ascii=False,
        ),
        related_subjects_json=json.dumps(related_subjects, ensure_ascii=False),
    )
    result = call_llm(
        prompt,
        prompt_cfg,
        system_prompt="You only output JSON.",
        api_key=api_key,
    )
    if not isinstance(result, dict):
        return None

    rows = []
    highlight_payload = result.get("highlight")
    if not isinstance(highlight_payload, dict):
        highlights = [p for p in _as_list(result.get("highlights")) if isinstance(p, dict)]
        highlight_payload = highlights[0] if highlights else None
    if isinstance(highlight_payload, dict):
        highlight = _llm_highlight_row(subject, highlight_payload, records, snapshot_date)
        if highlight:
            rows.append(highlight)

    rows.extend(_llm_comparison_rows(
        subject,
        result.get("comparisons"),
        records,
        related_subjects,
        snapshot_date,
    ))
    return rows or None


def _timeline_rows(subject: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records[:6]:
        rows.append({
            "subject_id": subject["id"],
            "snapshot_date": record["snapshot_date"],
            "module_type": "timeline",
            "insight_key": f"timeline:{record['snapshot_date']}:{record['item_id']}",
            "title": record["title"][:180],
            "summary": (record.get("summary") or record["title"])[:500],
            "analysis": (record.get("analysis") or "")[:1000] or None,
            "event_date": record["snapshot_date"],
            "comparison_subject_ids": [],
            "dimensions_json": {
                "generation_mode": "rule",
                "source_name": record.get("source_name"),
                "rank": record.get("rank"),
                "score": record.get("score"),
            },
            "importance_score": _importance(record),
            "confidence": record.get("mention", {}).get("confidence"),
            "evidence_item_ids": [record["item_id"]],
            "evidence_refs_json": _evidence_refs(record),
            "related_subject_ids": [],
            "generated_by": "pipeline",
            "generator_version": GENERATOR_VERSION,
            "status": "published",
            "published_at": _published_at(),
        })
    return rows


def _highlight_row(subject: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    best = records[0]
    summary = best.get("summary") or best["title"]
    analysis = best.get("analysis") or f"近期来自 {best.get('source_name') or 'unknown'} 的高相关内容。"
    return {
        "subject_id": subject["id"],
        "snapshot_date": best["snapshot_date"],
        "module_type": "highlight",
        "insight_key": "highlight:recent-top",
        "title": f"{subject['display_name']} 的最新高信号",
        "summary": summary[:500],
        "analysis": analysis[:1000],
        "event_date": best["snapshot_date"],
        "comparison_subject_ids": [],
        "dimensions_json": {
            "generation_mode": "rule",
            "source_name": best.get("source_name"),
            "rank": best.get("rank"),
            "score": best.get("score"),
            "item_title": best["title"],
        },
        "importance_score": _importance(best),
        "confidence": best.get("mention", {}).get("confidence"),
        "evidence_item_ids": [best["item_id"]],
        "evidence_refs_json": _evidence_refs(best),
        "related_subject_ids": [],
        "generated_by": "pipeline",
        "generator_version": GENERATOR_VERSION,
        "status": "published",
        "published_at": _published_at(),
    }


def _co_mention_rows(
    subjects: list[dict[str, Any]],
    mentions: list[dict[str, Any]],
    records_by_subject: dict[str, list[dict[str, Any]]],
    today: str,
) -> list[dict[str, Any]]:
    subject_map = {s["id"]: s for s in subjects}
    item_subjects: dict[tuple[str, str], set[str]] = defaultdict(set)
    for mention in mentions:
        item_id = mention.get("item_id")
        snapshot_date = str(mention.get("snapshot_date") or "")
        subject_id = mention.get("subject_id")
        if item_id and snapshot_date and subject_id in subject_map:
            item_subjects[(item_id, snapshot_date)].add(subject_id)

    rows = []
    for subject in subjects:
        sid = subject["id"]
        records = records_by_subject.get(sid) or []
        if not records:
            continue
        co_counter: Counter[str] = Counter()
        evidence_ids: list[str] = []
        for record in records:
            key = (record["item_id"], record["snapshot_date"])
            others = item_subjects.get(key, set()) - {sid}
            if not others:
                continue
            evidence_ids.append(record["item_id"])
            for other in others:
                co_counter[other] += 1
        if not co_counter:
            continue
        related_ids = [sid for sid, _ in co_counter.most_common(5)]
        related_names = [subject_map[sid]["display_name"] for sid in related_ids if sid in subject_map]
        if not related_names:
            continue
        digest = hashlib.md5(",".join(sorted(related_ids)).encode()).hexdigest()[:12]
        rows.append({
            "subject_id": sid,
            "snapshot_date": today,
            "module_type": "comparison",
            "insight_key": f"comparison:recent-co-mentions:{digest}",
            "title": f"{subject['display_name']} 的关联观察",
            "summary": f"近期常与 {', '.join(related_names[:3])} 共同出现在相关内容中。",
            "analysis": f"这些共现关系来自 {len(set(evidence_ids))} 条内容，可作为后续人工或 AI 深度对比的候选。",
            "event_date": today,
            "comparison_subject_ids": related_ids,
            "dimensions_json": {
                "generation_mode": "rule",
                "co_mentions": dict(co_counter),
                "related_names": related_names,
            },
            "importance_score": 0.65,
            "confidence": None,
            "evidence_item_ids": list(dict.fromkeys(evidence_ids))[:10],
            "evidence_refs_json": {"co_mention_subjects": related_names},
            "related_subject_ids": related_ids,
            "generated_by": "pipeline",
            "generator_version": GENERATOR_VERSION,
            "status": "published",
            "published_at": _published_at(),
        })
    return rows


def _upsert_insights(sb: Client, rows: list[dict[str, Any]]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    written = 0
    failed = 0
    for i in range(0, len(rows), 100):
        batch = rows[i : i + 100]
        try:
            sb.table("subject_insights").upsert(
                batch,
                on_conflict="subject_id,module_type,insight_key,generator_version",
            ).execute()
            written += len(batch)
        except Exception as e:
            print(f"  ⚠️ subject_insights 批量写入失败 offset={i}: {e}")
            failed += len(batch)
    return written, failed


def run_subject_insights(
    sb: Client,
    config: PipelineConfig,
    snapshot_date: str,
    table_suffix: str = "",
) -> dict[str, Any]:
    if not _param_bool(config, "subject_insights_enabled", True):
        print("⏭️  subject_insights_enabled=false，跳过 Subject Insights")
        return {"skipped": True, "written": 0, "failed": 0}

    today = date.fromisoformat(snapshot_date)
    window_days = int(config.get_param("subject_insights_window_days", 14))
    max_subjects = int(config.get_param("subject_insights_max_subjects", 50))
    max_items_per_subject = int(config.get_param("subject_insights_max_items_per_subject", 12))
    use_llm = _param_bool(config, "subject_insights_use_llm", False)
    start_date = (today - timedelta(days=max(0, window_days - 1))).isoformat()

    subjects = _load_visible_subjects(sb, max_subjects)
    if not subjects:
        print("✅ 无 visible subject，跳过 Subject Insights")
        return {"skipped": True, "written": 0, "failed": 0}

    subject_ids = [s["id"] for s in subjects]
    mentions = _load_mentions(sb, subject_ids, start_date, snapshot_date, table_suffix)
    if not mentions:
        print("✅ 无 subject_mentions，跳过 Subject Insights")
        return {"skipped": True, "written": 0, "failed": 0, "subjects_total": len(subjects)}

    item_ids = list({m["item_id"] for m in mentions if m.get("item_id")})
    display_by_key = _load_display_items(sb, item_ids, table_suffix)
    processed_by_key = _load_processed_items(sb, item_ids, table_suffix)
    records_by_subject = _evidence_records(
        mentions, display_by_key, processed_by_key, max_items_per_subject
    )

    subject_map = {s["id"]: s for s in subjects}
    item_subjects = _item_subject_index(mentions, subject_map)
    prompt_cfg = config.get_prompt(LLM_PROMPT_NAME) if use_llm else None
    api_key = os.getenv("KIMI_API_KEY", "") if use_llm else ""
    llm_ready = bool(use_llm and prompt_cfg and api_key)
    if use_llm and not prompt_cfg:
        print(f"  ⚠️ 缺少 prompt_templates.{LLM_PROMPT_NAME}，Subject Insights 使用规则兜底")
    elif use_llm and not api_key:
        print("  ⚠️ 缺少 KIMI_API_KEY，Subject Insights 使用规则兜底")

    rows: list[dict[str, Any]] = []
    llm_subjects = 0
    llm_fallback_subjects = 0
    llm_comparison_keys: set[tuple[str, str]] = set()
    for subject in subjects:
        records = records_by_subject.get(subject["id"]) or []
        if not records:
            continue
        rows.extend(_timeline_rows(subject, records))

        llm_rows = None
        if llm_ready:
            related_subjects = _related_subjects_for_prompt(subject, records, subject_map, item_subjects)
            try:
                llm_rows = _llm_subject_rows(
                    subject,
                    records,
                    related_subjects,
                    prompt_cfg,
                    api_key,
                    snapshot_date,
                )
            except Exception as e:
                print(f"  ⚠️ subject_insights LLM 生成失败 subject={subject.get('slug')}: {e}")

        llm_has_highlight = False
        if llm_rows:
            llm_subjects += 1
            for row in llm_rows:
                if row["module_type"] == "highlight":
                    llm_has_highlight = True
                elif row["module_type"] == "comparison":
                    llm_comparison_keys.add((row["subject_id"], row["insight_key"]))
            rows.extend(llm_rows)
        elif use_llm:
            llm_fallback_subjects += 1

        if not llm_has_highlight:
            highlight = _highlight_row(subject, records)
            if highlight:
                rows.append(highlight)

    co_rows = _co_mention_rows(subjects, mentions, records_by_subject, snapshot_date)
    rows.extend([
        row for row in co_rows
        if (row["subject_id"], row["insight_key"]) not in llm_comparison_keys
    ])

    written, failed = _upsert_insights(sb, rows)
    subjects_with_evidence = len(records_by_subject)
    print(
        f"🧭 Subject Insights 完成: subjects={len(subjects)} "
        f"with_evidence={subjects_with_evidence} rows={len(rows)} "
        f"llm_subjects={llm_subjects} llm_fallback={llm_fallback_subjects} "
        f"written={written} failed={failed}"
    )
    return {
        "skipped": False,
        "subjects_total": len(subjects),
        "subjects_with_evidence": subjects_with_evidence,
        "llm_enabled": use_llm,
        "llm_subjects": llm_subjects,
        "llm_fallback_subjects": llm_fallback_subjects,
        "rows": len(rows),
        "written": written,
        "failed": failed,
    }
