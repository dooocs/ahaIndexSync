# enrichers/cross_reference.py
"""
Cross Reference Enricher
------------------------
纯数据库查询，零外部 API 调用。

产出：
  - historical_mentions: 该 item 关联到的 subject 历史出现记录（跨日期、跨源）
  - same_day_cross_refs: 当天其他 item 是否也提及了同一 subject

不创建新 subject。仅基于：
  1. item 自身若是 GitHub repo → 构造 github:owner/repo slug
  2. subjects 表已存在的 slug
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from enrichers.base import BaseEnricher, EnrichmentResult, SubjectCandidate
from enrichers.registry import register
from enrichers._utils import github_slug, primary_github_repo_for_item


@register("cross_reference")
class CrossReferenceEnricher(BaseEnricher):
    enrichment_type = "cross_reference"

    def __init__(self, sb, config, api_key="", table_suffix=""):
        super().__init__(sb, config, api_key, table_suffix)
        self._subjects_by_slug: dict[str, dict] = {}
        self._mentions_by_subject: dict[str, list[dict]] = defaultdict(list)
        self._same_day_items_by_subject: dict[str, list[dict]] = defaultdict(list)
        self._snapshot_date: str = ""

    def preload(self, items: list[dict], snapshot_date: str) -> None:
        """批量拉取可能用到的 subject 与 mentions，避免逐条查询。"""
        self._snapshot_date = snapshot_date

        candidate_slugs: set[str] = set()
        for it in items:
            repo = primary_github_repo_for_item(it)
            if repo:
                candidate_slugs.add(github_slug(*repo))

        if not candidate_slugs:
            return

        try:
            rows = (
                self.sb.table(self.subjects_table)
                .select("id, slug, type, display_name, mention_count, first_seen_at, last_seen_at")
                .in_("slug", list(candidate_slugs))
                .execute()
                .data
                or []
            )
        except Exception as e:
            print(f"  ⚠️ cross_reference preload subjects 失败: {e}")
            rows = []

        for r in rows:
            self._subjects_by_slug[r["slug"]] = r

        subject_ids = [r["id"] for r in rows]
        if not subject_ids:
            return

        try:
            stats_rows = (
                self.sb.table("subject_stats")
                .select("subject_id, mention_count, first_seen_at, last_seen_at, item_count")
                .in_("subject_id", subject_ids)
                .execute()
                .data
                or []
            )
        except Exception as e:
            print(f"  ⚠️ cross_reference preload subject_stats 失败: {e}")
            stats_rows = []

        stats_by_subject = {r["subject_id"]: r for r in stats_rows}
        for slug, subj in list(self._subjects_by_slug.items()):
            stat = stats_by_subject.get(subj["id"])
            if not stat:
                continue
            self._subjects_by_slug[slug] = {
                **subj,
                "mention_count": stat.get("mention_count", subj.get("mention_count")),
                "first_seen_at": stat.get("first_seen_at") or subj.get("first_seen_at"),
                "last_seen_at": stat.get("last_seen_at") or subj.get("last_seen_at"),
                "item_count": stat.get("item_count"),
            }

        cutoff = (date.fromisoformat(snapshot_date) - timedelta(days=90)).isoformat()
        try:
            mentions = (
                self.sb.table(self.subject_mentions_table)
                .select("subject_id, item_id, snapshot_date, source_name, score")
                .in_("subject_id", subject_ids)
                .gte("snapshot_date", cutoff)
                .execute()
                .data
                or []
            )
        except Exception as e:
            print(f"  ⚠️ cross_reference preload mentions 失败: {e}")
            mentions = []

        for m in mentions:
            self._mentions_by_subject[m["subject_id"]].append(m)
            if m["snapshot_date"] == snapshot_date:
                self._same_day_items_by_subject[m["subject_id"]].append(m)

    def applies_to(self, item: dict) -> bool:
        return True

    def run(self, item: dict) -> EnrichmentResult | None:
        repo = primary_github_repo_for_item(item)
        if not repo:
            return None

        slug = github_slug(*repo)
        subj = self._subjects_by_slug.get(slug)

        historical: list[dict] = []
        same_day: list[dict] = []
        trend = "new"

        if subj:
            mentions = self._mentions_by_subject.get(subj["id"], [])
            for m in mentions:
                if m["item_id"] == item.get("item_id") and m["snapshot_date"] == self._snapshot_date:
                    continue
                rec = {
                    "date": m["snapshot_date"],
                    "source": m.get("source_name"),
                    "score": m.get("score"),
                }
                if m["snapshot_date"] == self._snapshot_date:
                    same_day.append(rec)
                else:
                    historical.append(rec)

            historical.sort(key=lambda x: x["date"], reverse=True)

            if historical:
                recent = [h for h in historical if h["date"] >= (date.fromisoformat(self._snapshot_date) - timedelta(days=30)).isoformat()]
                if len(recent) >= 3:
                    trend = "rising" if _is_rising(recent) else "steady"
                else:
                    trend = "occasional"

        data = {
            "subject_slug": slug,
            "subject_known": subj is not None,
            "first_seen_at": subj["first_seen_at"] if subj else None,
            "total_mention_count": subj["mention_count"] if subj else 0,
            "historical_mentions": historical[:10],
            "same_day_cross_refs": same_day,
            "trend": trend,
        }

        return EnrichmentResult(
            enrichment_type=self.enrichment_type,
            enricher_name=self.name,
            data=data,
            subject_candidates=[],
        )


def _is_rising(mentions: list[dict]) -> bool:
    if len(mentions) < 3:
        return False
    mentions_sorted = sorted(mentions, key=lambda x: x["date"])
    half = len(mentions_sorted) // 2
    if half == 0:
        return False
    early = mentions_sorted[:half]
    late = mentions_sorted[half:]
    early_avg = sum((m.get("score") or 0) for m in early) / max(1, len(early))
    late_avg = sum((m.get("score") or 0) for m in late) / max(1, len(late))
    return late_avg > early_avg + 0.05
