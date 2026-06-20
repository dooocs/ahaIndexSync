# stages/subject.py
"""
Subject 处理逻辑，在 Enrich 阶段内被调用。

职责：
  1. upsert_subject(slug, ...)：创建或更新 subjects 记录，遵守 subject_aliases 合并
  2. record_mention(...)：写入 subject_mentions（唯一索引去重）

V1 自动创建仅限 type='project'（github:owner/repo）。其他 type 靠手工 seed。
"""

from __future__ import annotations

import threading
from typing import Any

from supabase import Client

from infra.db import enrich_table_names
from infra.time_utils import get_today_str


_cache_lock = threading.Lock()


def _schema_cache_missing_column(exc: Exception, table: str, columns: tuple[str, ...]) -> bool:
    message = str(exc).lower()
    return (
        table.lower() in message
        and "schema cache" in message
        and any(column.lower() in message for column in columns)
    )


class SubjectRegistry:
    """在一次 Enrich 运行内缓存 slug → subject_id，避免重复 upsert。"""

    def __init__(self, sb: Client, table_suffix: str = ""):
        self.sb = sb
        self._is_test_tables = bool(table_suffix)
        (
            self._item_enrichments_table,
            self._subjects_table,
            self._subject_mentions_table,
            self._subject_aliases_table,
        ) = enrich_table_names(table_suffix)
        self._subject_candidates_table = "" if table_suffix else "subject_candidates"
        self._slug_to_id: dict[str, str] = {}
        self._alias_map: dict[str, str] = {}
        self._lock = threading.Lock()
        self._load_aliases()

    def _load_aliases(self) -> None:
        try:
            rows = self.sb.table(self._subject_aliases_table).select("from_slug, to_subject_id").execute().data or []
            for r in rows:
                self._alias_map[r["from_slug"]] = r["to_subject_id"]
        except Exception as e:
            print(f"  ⚠️ 加载 subject_aliases 失败: {e}")

    def upsert_subject(
        self,
        slug: str,
        type: str,
        display_name: str,
        description: str = "",
        metadata: dict | None = None,
        auto_create_types: tuple[str, ...] = ("project",),
    ) -> str | None:
        """返回 subject_id。如果 slug 未知且 type 不在 auto_create_types，返回 None。"""
        if not slug:
            return None

        with self._lock:
            if slug in self._slug_to_id:
                return self._slug_to_id[slug]

            if slug in self._alias_map:
                sid = self._alias_map[slug]
                self._slug_to_id[slug] = sid
                return sid

        try:
            existing = (
                self.sb.table(self._subjects_table)
                .select("id")
                .eq("slug", slug)
                .limit(1)
                .execute()
                .data
            )
        except Exception as e:
            print(f"  ⚠️ 查询 subject 失败 {slug}: {e}")
            return None

        if existing:
            sid = existing[0]["id"]
            with self._lock:
                self._slug_to_id[slug] = sid
            return sid

        if type not in auto_create_types:
            return None

        today = get_today_str()
        try:
            inserted = (
                self.sb.table(self._subjects_table)
                .insert({
                    "slug": slug,
                    "type": type,
                    "display_name": display_name or slug,
                    "description": description,
                    "metadata": metadata or {},
                    "first_seen_at": today,
                    "last_seen_at": today,
                    "mention_count": 0,
                })
                .execute()
                .data
            )
        except Exception as e:
            print(f"  ⚠️ 创建 subject 失败 {slug}: {e}")
            try:
                existing = (
                    self.sb.table(self._subjects_table)
                    .select("id")
                    .eq("slug", slug)
                    .limit(1)
                    .execute()
                    .data
                )
                if existing:
                    sid = existing[0]["id"]
                    with self._lock:
                        self._slug_to_id[slug] = sid
                    return sid
            except Exception:
                pass
            return None

        if not inserted:
            return None
        sid = inserted[0]["id"]
        with self._lock:
            self._slug_to_id[slug] = sid
        return sid

    def record_mention(
        self,
        subject_id: str,
        item_id: str,
        snapshot_date: str,
        role: str = "mentioned",
        source_name: str | None = None,
        score: float | None = None,
        context: str | None = None,
        detected_by: str = "pipeline.enrich",
        confidence: float | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> bool:
        if not subject_id or not item_id:
            return False

        subject = self._load_subject(subject_id)
        if not subject:
            print(f"  ⚠️ 读取 subject 失败 {subject_id}: not found")
            return False

        mention_row = {
            "subject_id": subject_id,
            "item_id": item_id,
            "snapshot_date": snapshot_date,
            "role": role,
            "source_name": source_name,
            "score": score,
            "context": (context or "")[:500] if context else None,
            "detected_by": detected_by,
            "confidence": confidence,
            "evidence": evidence or {},
        }

        mention_is_new = self._mention_is_new(subject_id, item_id, snapshot_date)

        rpc_payload = {
            "p_slug": subject.get("slug") or "",
            "p_type": subject.get("type") or "",
            "p_display_name": subject.get("display_name") or subject.get("slug") or "",
            "p_item_id": item_id,
            "p_snapshot_date": snapshot_date,
            "p_role": role,
            "p_source_name": source_name,
            "p_score": score,
            "p_context": (context or "")[:500] if context else None,
            "p_metadata": subject.get("metadata") or {},
            "p_detected_by": detected_by,
            "p_confidence": confidence,
            "p_evidence": evidence or {},
        }

        rpc_runner = getattr(self.sb, "rpc", None)
        if callable(rpc_runner) and not self._is_test_tables:
            try:
                rpc_runner("record_subject_mention", rpc_payload).execute()
                return True
            except Exception as e:
                print(f"  ⚠️ record_subject_mention RPC 失败 {subject.get('slug')}/{item_id}: {e}")

        try:
            self.sb.table(self._subject_mentions_table).upsert(
                mention_row, on_conflict="subject_id,item_id,snapshot_date"
            ).execute()
        except Exception as e:
            if self._is_test_tables and _schema_cache_missing_column(
                e,
                self._subject_mentions_table,
                ("detected_by", "confidence", "evidence"),
            ):
                legacy_row = {
                    key: value
                    for key, value in mention_row.items()
                    if key not in ("detected_by", "confidence", "evidence")
                }
                try:
                    self.sb.table(self._subject_mentions_table).upsert(
                        legacy_row, on_conflict="subject_id,item_id,snapshot_date"
                    ).execute()
                except Exception as legacy_error:
                    print(f"  ⚠️ 写入 subject_mention 失败 {subject_id}/{item_id}: {legacy_error}")
                    return False
            else:
                print(f"  ⚠️ 写入 subject_mention 失败 {subject_id}/{item_id}: {e}")
                return False

        if mention_is_new is None:
            return True

        if mention_is_new:
            try:
                current = (
                    self.sb.table(self._subjects_table)
                    .select("mention_count, last_seen_at")
                    .eq("id", subject_id)
                    .limit(1)
                    .execute()
                    .data
                )
                if current:
                    current_row = current[0]
                    new_count = (current_row.get("mention_count") or 0) + 1
                    last_seen = current_row.get("last_seen_at") or snapshot_date
                    if snapshot_date > last_seen:
                        last_seen = snapshot_date
                    self.sb.table(self._subjects_table).update({
                        "mention_count": new_count,
                        "last_seen_at": last_seen,
                    }).eq("id", subject_id).execute()
            except Exception as e:
                print(f"  ⚠️ 更新 subject 计数失败 {subject_id}: {e}")

        return True

    def _load_subject(self, subject_id: str) -> dict[str, Any] | None:
        try:
            rows = (
                self.sb.table(self._subjects_table)
                .select("id, slug, type, display_name, metadata, mention_count, last_seen_at")
                .eq("id", subject_id)
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception as e:
            print(f"  ⚠️ 查询 subject 失败 {subject_id}: {e}")
            return None

        return rows[0] if rows else None

    def _mention_is_new(self, subject_id: str, item_id: str, snapshot_date: str) -> bool | None:
        try:
            current = (
                self.sb.table(self._subject_mentions_table)
                .select("id")
                .eq("subject_id", subject_id)
                .eq("item_id", item_id)
                .eq("snapshot_date", snapshot_date)
                .limit(1)
                .execute()
                .data
            )
        except Exception as e:
            print(f"  ⚠️ 检查 subject_mention 是否已存在失败 {subject_id}/{item_id}: {e}")
            return None

        return not bool(current)

    def record_candidate(
        self,
        cand: Any,
        item_id: str,
        snapshot_date: str,
        source_name: str | None = None,
        score: float | None = None,
        extractor_version: str = "enrich.subject_registry",
    ) -> bool:
        """Write an unknown subject into subject_candidates for Admin review.

        Test table runs intentionally skip this path because subject_candidates
        is an Admin production review queue, not a pipeline test artifact.
        """
        if not self._subject_candidates_table:
            return False
        if not getattr(cand, "slug", "") or not getattr(cand, "type", ""):
            return False

        candidate_key = self._candidate_key(cand)
        evidence_entry = {
            "item_id": item_id,
            "snapshot_date": snapshot_date,
            "source_name": source_name,
            "score": score,
            "role": getattr(cand, "role", "mentioned") or "mentioned",
            "context": (getattr(cand, "context", "") or "")[:500],
        }

        try:
            existing = (
                self.sb.table(self._subject_candidates_table)
                .select("id, source_item_ids, evidence")
                .eq("candidate_key", candidate_key)
                .in_("status", ["pending", "needs_more_evidence"])
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception as e:
            print(f"  ⚠️ 查询 subject_candidate 失败 {candidate_key}: {e}")
            return False

        if existing:
            row = existing[0]
            source_item_ids = self._limited_unique([*(row.get("source_item_ids") or []), item_id], 50)
            evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
            evidence_items = evidence.get("items") if isinstance(evidence.get("items"), list) else []
            candidate_evidence = getattr(cand, "evidence", None)
            if candidate_evidence:
                evidence_entry["candidate_evidence"] = candidate_evidence
            evidence_items.append(evidence_entry)
            evidence["items"] = self._dedupe_evidence(evidence_items, 30)
            evidence["latest"] = evidence_entry
            try:
                self.sb.table(self._subject_candidates_table).update({
                    "proposed_slug": cand.slug,
                    "proposed_type": cand.type,
                    "display_name": getattr(cand, "display_name", "") or cand.slug,
                    "definition": getattr(cand, "description", "") or None,
                    "homepage_url": getattr(cand, "homepage_url", "") or None,
                    "aliases": getattr(cand, "aliases", None) or [],
                    "metadata": getattr(cand, "metadata", None) or {},
                    "source_item_ids": source_item_ids,
                    "evidence": evidence,
                    "reason": getattr(cand, "reason", "") or getattr(cand, "context", "") or None,
                    "confidence": getattr(cand, "confidence", None),
                    "proposed_by": getattr(cand, "proposed_by", "") or "ai",
                    "extractor_version": getattr(cand, "extractor_version", "") or extractor_version,
                }).eq("id", row["id"]).execute()
                return True
            except Exception as e:
                print(f"  ⚠️ 更新 subject_candidate 失败 {candidate_key}: {e}")
                return False

        evidence = {
            "items": [evidence_entry],
            "latest": evidence_entry,
        }
        candidate_evidence = getattr(cand, "evidence", None)
        if candidate_evidence:
            evidence_entry["candidate_evidence"] = candidate_evidence
        row = {
            "candidate_key": candidate_key,
            "proposed_slug": cand.slug,
            "proposed_type": cand.type,
            "display_name": getattr(cand, "display_name", "") or cand.slug,
            "definition": getattr(cand, "description", "") or None,
            "homepage_url": getattr(cand, "homepage_url", "") or None,
            "aliases": getattr(cand, "aliases", None) or [],
            "metadata": getattr(cand, "metadata", None) or {},
            "source_item_ids": [item_id] if item_id else [],
            "evidence": evidence,
            "reason": getattr(cand, "reason", "") or getattr(cand, "context", "") or None,
            "confidence": getattr(cand, "confidence", None),
            "proposed_by": getattr(cand, "proposed_by", "") or "ai",
            "extractor_version": getattr(cand, "extractor_version", "") or extractor_version,
            "status": "pending",
        }
        try:
            self.sb.table(self._subject_candidates_table).insert(row).execute()
            return True
        except Exception as e:
            print(f"  ⚠️ 写入 subject_candidate 失败 {candidate_key}: {e}")
            return False

    @staticmethod
    def _candidate_key(cand: Any) -> str:
        return f"{cand.type}:{cand.slug}".lower()

    @staticmethod
    def _limited_unique(values: list[Any], limit: int) -> list[Any]:
        seen: set[Any] = set()
        out: list[Any] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out[-limit:]

    @staticmethod
    def _dedupe_evidence(items: list[dict], limit: int) -> list[dict]:
        seen: set[tuple[str, str, str]] = set()
        out: list[dict] = []
        for item in items:
            key = (
                str(item.get("item_id") or ""),
                str(item.get("snapshot_date") or ""),
                str(item.get("context") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out[-limit:]
