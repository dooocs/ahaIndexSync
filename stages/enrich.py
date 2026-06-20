# stages/enrich.py
"""
Enrich 阶段：第二层内容增厚。

流程：
  1. 接收粗排后的 items（按 aha_index 降序）
  2. 实例化所有 enricher，调用 preload()（批量预取历史、subjects 等）
  3. ThreadPool 并发处理 items
       - 单 item 内部顺序执行 enricher（cross_reference → hn_comments → github_ecosystem）
       - 每个 enricher 独立异常捕获，互不影响
  4. 收集到的 EnrichmentResult 批量写入 item_enrichments
  5. 收集到的 SubjectCandidate 去重后，已知 subject 写 subject_mentions，未知 subject 进入 subject_candidates
  6. item 本身若是 GitHub repo，自动登记为 primary mention 或候选

两层保护：
  - 单 enricher 失败不影响其他 enricher 和其他 item
  - 整体超时（默认 3600s）到达后立即停止，已写入保留
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from supabase import Client

from pipeline.config_loader import PipelineConfig
from infra.db import table_names, enrich_table_names
from infra.time_utils import today_str
from enrichers.base import BaseEnricher, EnrichmentResult, SubjectCandidate
from enrichers.registry import list_enrichers
from enrichers._utils import github_slug, primary_github_repo_for_item
from stages.subject import SubjectRegistry


@dataclass
class _ItemOutput:
    item_id: str
    source_name: str
    score: float
    results: list[EnrichmentResult]


def _enrich_one_item(item: dict, enrichers: list[BaseEnricher], deadline: float) -> _ItemOutput:
    results: list[EnrichmentResult] = []
    for enricher in enrichers:
        if time.monotonic() > deadline:
            break
        try:
            if not enricher.applies_to(item):
                continue
        except Exception as e:
            print(f"  ⚠️ [{enricher.name}] applies_to 异常 item={item.get('item_id')}: {e}")
            continue
        try:
            r = enricher.run(item)
            if r is not None:
                results.append(r)
        except Exception as e:
            title = (item.get("processed_title") or item.get("raw_title") or "")[:40]
            print(f"  ⚠️ [{enricher.name}] 失败 item='{title}': {e}")
    return _ItemOutput(
        item_id=item["item_id"],
        source_name=item.get("source_name", ""),
        score=float(item.get("aha_index") or 0),
        results=results,
    )


def _persist_enrichments(sb: Client, rows: list[dict], suffix: str) -> int:
    if not rows:
        return 0
    ie_table, _, _, _ = enrich_table_names(suffix)
    try:
        sb.table(ie_table).upsert(
            rows, on_conflict="item_id,snapshot_date,enrichment_type"
        ).execute()
        return len(rows)
    except Exception as e:
        print(f"  ⚠️ {ie_table} 批量写入失败: {e}")
        ok = 0
        for r in rows:
            try:
                sb.table(ie_table).upsert(
                    r, on_conflict="item_id,snapshot_date,enrichment_type"
                ).execute()
                ok += 1
            except Exception as ee:
                print(f"    ↳ 单条写入失败 {r['item_id']}/{r['enrichment_type']}: {ee}")
        return ok


def _register_primary_subjects(
    registry: SubjectRegistry, items: list[dict], snapshot_date: str
) -> tuple[int, int]:
    """item 本身是 GitHub repo 的，已有 subject 写 mention，未知 subject 进候选。"""
    mentions = 0
    candidates = 0
    for it in items:
        repo = primary_github_repo_for_item(it)
        if not repo:
            continue
        owner, repo_name = repo
        slug = github_slug(owner, repo_name)
        display_name = f"{owner}/{repo_name}"
        extra = it.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        metadata = {
            "repo_full_name": f"{owner}/{repo_name}",
        }
        if isinstance(extra, dict):
            if extra.get("stars") is not None:
                metadata["stars"] = extra.get("stars")
            if extra.get("topics"):
                metadata["topics"] = extra.get("topics")

        sid = registry.upsert_subject(
            slug=slug,
            type="project",
            display_name=display_name,
            description=(it.get("summary") or "")[:200],
            metadata=metadata,
            auto_create_types=(),
        )
        if not sid:
            cand = SubjectCandidate(
                slug=slug,
                type="project",
                display_name=display_name,
                description=(it.get("summary") or "")[:200],
                metadata=metadata,
                evidence={
                    "source_url": it.get("original_url"),
                    "repo_full_name": f"{owner}/{repo_name}",
                },
                role="primary",
                context=(it.get("processed_title") or it.get("raw_title") or "")[:200],
                reason="GitHub raw item primary subject",
                proposed_by="rule",
                extractor_version="enrich.primary_github_repo",
            )
            if registry.record_candidate(
                cand,
                item_id=it["item_id"],
                snapshot_date=snapshot_date,
                source_name=it.get("source_name"),
                score=it.get("aha_index"),
                extractor_version="enrich.primary_github_repo",
            ):
                candidates += 1
            continue
        if registry.record_mention(
            subject_id=sid,
            item_id=it["item_id"],
            snapshot_date=snapshot_date,
            role="primary",
            source_name=it.get("source_name"),
            score=it.get("aha_index"),
            context=(it.get("processed_title") or it.get("raw_title") or "")[:200],
            detected_by="enrich.primary_github_repo",
            confidence=1.0,
            evidence={
                "source_url": it.get("original_url"),
                "repo_full_name": f"{owner}/{repo_name}",
                "metadata": metadata,
            },
        ):
            mentions += 1
    return mentions, candidates


def _register_candidate_subjects(
    registry: SubjectRegistry,
    outputs: list[_ItemOutput],
    snapshot_date: str,
) -> tuple[int, int]:
    """Enricher 产出的 subject 候选：已有 subject 写 mention，未知进入审核队列。"""
    mentions = 0
    candidates = 0
    for out in outputs:
        for r in out.results:
            for cand in r.subject_candidates:
                sid = registry.upsert_subject(
                    slug=cand.slug,
                    type=cand.type,
                    display_name=cand.display_name,
                    description=cand.description,
                    metadata=cand.metadata,
                    auto_create_types=(),
                )
                if not sid:
                    if registry.record_candidate(
                        cand,
                        item_id=out.item_id,
                        snapshot_date=snapshot_date,
                        source_name=out.source_name,
                        score=out.score,
                        extractor_version=f"enrich.{r.enricher_name}",
                    ):
                        candidates += 1
                    continue
                if registry.record_mention(
                    subject_id=sid,
                    item_id=out.item_id,
                    snapshot_date=snapshot_date,
                    role=cand.role,
                    source_name=out.source_name,
                    score=out.score,
                    context=cand.context,
                    detected_by=f"enrich.{r.enricher_name}",
                    confidence=cand.confidence,
                    evidence={
                        "candidate_key": f"{cand.type}:{cand.slug}",
                        "reason": cand.reason,
                        "metadata": cand.metadata,
                        "proposed_by": cand.proposed_by,
                    },
                ):
                    mentions += 1
    return mentions, candidates


def run_enrich(
    sb: Client,
    config: PipelineConfig,
    items: list[dict],
    table_suffix: str = "",
) -> dict:
    enabled = config.get_param("enrich_enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.lower() not in ("false", "0", "no", "")
    if not enabled:
        print("⏭️  enrich_enabled=false，跳过 Enrich 阶段")
        return {"skipped": True}

    if not items:
        print("✅ 无候选 item，Enrich 阶段跳过")
        return {"skipped": True}

    api_key = os.getenv("KIMI_API_KEY", "")
    timeout_s = int(config.get_param("enrich_timeout", 3600))
    max_workers = int(config.get_param("enrich_max_workers", 5))
    snapshot_date = today_str()

    enricher_classes = list_enrichers()
    enrichers: list[BaseEnricher] = [cls(sb, config, api_key, table_suffix) for cls in enricher_classes]
    print(f"🧩 Enricher 列表: {[e.name for e in enrichers]}")

    for e in enrichers:
        try:
            e.preload(items, snapshot_date)
        except Exception as ex:
            print(f"  ⚠️ [{e.name}] preload 异常: {ex}")

    deadline = time.monotonic() + timeout_s
    print(f"⏱️  Enrich 总超时 {timeout_s}s，并发 workers={max_workers}")

    outputs: list[_ItemOutput] = []
    timed_out = False

    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {pool.submit(_enrich_one_item, it, enrichers, deadline): it for it in items}
        for fut in as_completed(futures):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                out = fut.result(timeout=max(0.1, remaining))
                outputs.append(out)
            except Exception as e:
                it = futures[fut]
                print(f"  ⚠️ enrich worker 异常 item={it.get('item_id')}: {e}")
    finally:
        # 超时/正常完成后都不等待未完成任务，避免卡在已经应当放弃的 HTTP/LLM 调用
        if timed_out:
            print("⏰ Enrich 整体超时，停止分派新任务（已写入的数据会保留）")
        pool.shutdown(wait=False, cancel_futures=True)

    enrichment_rows: list[dict] = []
    for out in outputs:
        for r in out.results:
            enrichment_rows.append({
                "item_id": out.item_id,
                "snapshot_date": snapshot_date,
                "enrichment_type": r.enrichment_type,
                "enricher_name": r.enricher_name,
                "data": r.data,
            })
    written = _persist_enrichments(sb, enrichment_rows, table_suffix)

    registry = SubjectRegistry(sb, table_suffix)
    primary_mentions, primary_candidates = _register_primary_subjects(registry, items, snapshot_date)
    candidate_mentions, enriched_candidates = _register_candidate_subjects(registry, outputs, snapshot_date)
    subject_candidates = primary_candidates + enriched_candidates
    catalog_stats = {"mentions": 0, "matches": 0, "subjects_loaded": 0}
    try:
        from stages.subject_match import run_catalog_subject_match
        catalog_stats = run_catalog_subject_match(
            sb, config, items, registry, snapshot_date, table_suffix
        )
    except Exception as e:
        print(f"  ⚠️ Catalog Subject 匹配阶段异常（跳过）: {e}")

    stats = {
        "items_total": len(items),
        "items_processed": len(outputs),
        "enrichments_written": written,
        "primary_mentions": primary_mentions,
        "candidate_mentions": candidate_mentions,
        "primary_candidates": primary_candidates,
        "enriched_candidates": enriched_candidates,
        "subject_candidates": subject_candidates,
        "catalog_subject_mentions": catalog_stats.get("mentions", 0),
        "catalog_subject_matches": catalog_stats.get("matches", 0),
        "catalog_subjects_loaded": catalog_stats.get("subjects_loaded", 0),
        "timed_out": timed_out,
    }
    print(
        f"📊 Enrich 完成: processed={stats['items_processed']}/{stats['items_total']} "
        f"enrichments={written} primary_mentions={primary_mentions} "
        f"candidate_mentions={candidate_mentions} subject_candidates={subject_candidates} "
        f"catalog_mentions={stats['catalog_subject_mentions']} "
        f"timed_out={timed_out}"
    )
    return stats
