# infra/db.py
# Supabase client + table name helpers

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv
from .models import RawItem, ContentRecord
from .time_utils import get_fetch_window, get_today_str

load_dotenv()

_client: Client | None = None

# 单次 PostgREST 请求超时（秒）。supabase-py 默认 120s，数据库卡死时
# 一次配置读取就要等十几分钟才失败（2026-10-12 事故）。正常查询都是毫秒级。
SUPABASE_REQUEST_TIMEOUT_S = 30


def make_supabase_client() -> Client:
    try:
        from supabase import ClientOptions
    except ImportError:  # 测试里 supabase 模块是桩
        ClientOptions = None
    kwargs = {}
    if ClientOptions is not None:
        kwargs["options"] = ClientOptions(postgrest_client_timeout=SUPABASE_REQUEST_TIMEOUT_S)
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        **kwargs,
    )


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = make_supabase_client()
    return _client


# backward compat: old code that imports `supabase` directly from this module
# will fail at import time but that's OK since rank.py is deleted
supabase = None


def table_names(suffix: str = "") -> tuple[str, str, str, str]:
    """返回 (raw_items, processed_items, display_items, items_content) 表名。"""
    s = suffix or os.getenv("TABLE_SUFFIX", "")
    return f"raw_items{s}", f"processed_items{s}", f"display_items{s}", f"items_content{s}"


def enrich_table_names(suffix: str = "") -> tuple[str, str, str, str]:
    """
    返回 (item_enrichments, subjects, subject_mentions, subject_aliases) 4 张新表的名称。
    suffix='_test' 时用测试表；空字符串即生产表。
    """
    s = suffix or os.getenv("TABLE_SUFFIX", "")
    return (
        f"item_enrichments{s}",
        f"subjects{s}",
        f"subject_mentions{s}",
        f"subject_aliases{s}",
    )


_suffix = os.getenv("TABLE_SUFFIX", "")
RAW_TABLE, PROCESSED_TABLE, DISPLAY_TABLE, CONTENT_TABLE = table_names(_suffix)
ITEM_ENRICHMENTS_TABLE, SUBJECTS_TABLE, SUBJECT_MENTIONS_TABLE, SUBJECT_ALIASES_TABLE = enrich_table_names(_suffix)


# ── 写入 ───────────────────────────────────────────────────────

def upsert_raw_item(item: RawItem, raw_table: str | None = None) -> None:
    sb = get_supabase()
    tbl = raw_table or RAW_TABLE
    result = sb.table(tbl).upsert(item.to_db_dict()).execute()
    if not result.data:
        raise Exception(f"upsert_raw_item 失败: {item.title}")


def upsert_processed_item(item: RawItem, ai_data: dict, display_metrics: dict, processed_table: str | None = None) -> None:
    sb = get_supabase()
    tbl = processed_table or PROCESSED_TABLE
    result = sb.table(tbl).upsert({
        "item_id": item.id,
        "snapshot_date": get_today_str(),
        "raw_title": item.title,
        "original_url": item.original_url,
        "source_name": item.source_name,
        "content_type": item.content_type,
        "author": item.author,
        "raw_metrics": item.raw_metrics,
        "model": ai_data.get("model", "unknown"),
        "processed_title": ai_data.get("processed_title"),
        "summary": ai_data.get("summary"),
        "category": ai_data.get("category"),
        "tags": ai_data.get("tags", []),
        "keywords": ai_data.get("keywords", []),
        "aha_index": float(ai_data.get("aha_index", 0.5)),
        "expert_insight": ai_data.get("expert_insight"),
        "display_metrics": display_metrics,
        "extra": item.extra,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    if not result.data:
        raise Exception(f"upsert_processed_item 失败: {item.title}")


# ── 读取 ───────────────────────────────────────────────────────

def get_pending_items(raw_table: str | None = None, processed_table: str | None = None, fetch_window_hours: int = 24) -> list[RawItem]:
    sb = get_supabase()
    raw_tbl = raw_table or RAW_TABLE
    proc_tbl = processed_table or PROCESSED_TABLE

    start, end = get_fetch_window(fetch_window_hours)

    raw_data = (
        sb.table(raw_tbl)
        .select("*")
        .gte("created_at", start.isoformat())
        .lte("created_at", end.isoformat())
        .execute()
        .data
    )

    # 排除最近 7 天内任何日期已处理的 item（防止回补时覆盖历史数据）
    from datetime import timedelta
    week_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
    processed_raw_ids = {
        r["item_id"]
        for r in sb.table(proc_tbl)
        .select("item_id")
        .gte("snapshot_date", week_ago)
        .execute()
        .data
    }

    pending = [r for r in raw_data if r["id"] not in processed_raw_ids]

    items = []
    for r in pending:
        published_at = None
        if r.get("published_at"):
            try:
                published_at = datetime.fromisoformat(r["published_at"])
            except Exception:
                pass

        def _parse_json(val):
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except Exception:
                    return {}
            return val or {}

        items.append(RawItem(
            title=r["title"],
            original_url=r["original_url"],
            source_name=r["source_name"],
            source_type=r["source_type"],
            content_type=r["content_type"],
            author=r.get("author", ""),
            author_url=r.get("author_url", ""),
            raw_metrics=_parse_json(r.get("raw_metrics")),
            extra=_parse_json(r.get("extra")),
            published_at=published_at,
        ))

    return items


def get_pending_items_with_content(
    raw_table: str | None = None,
    content_table: str | None = None,
    processed_table: str | None = None,
    fetch_window_hours: int = 24,
    snapshot_date: str | None = None,
) -> list[tuple[RawItem, ContentRecord]]:
    """Stage 2 process 调用：JOIN raw_items + items_content，返回待处理项。"""
    sb = get_supabase()
    raw_tbl = raw_table or RAW_TABLE
    cont_tbl = content_table or CONTENT_TABLE
    proc_tbl = processed_table or PROCESSED_TABLE

    query = sb.table(raw_tbl).select(
        f"*, {cont_tbl}(raw_body, enriched_body, enriched_source, enriched_quality, fetch_attempts)"
    )
    if snapshot_date:
        # 阶段 5 之后：按 snapshot_date 过滤
        query = query.eq("snapshot_date", snapshot_date)
    else:
        # 阶段 5 之前：按 created_at 窗口过滤
        start, end = get_fetch_window(fetch_window_hours)
        query = query.gte("created_at", start.isoformat()).lte("created_at", end.isoformat())

    raw_data = query.execute().data

    from datetime import timedelta
    week_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
    processed_raw_ids = {
        r["item_id"]
        for r in sb.table(proc_tbl)
        .select("item_id")
        .gte("snapshot_date", week_ago)
        .execute()
        .data
    }

    def _parse_json(val):
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return {}
        return val or {}

    result = []
    for r in raw_data:
        if r["id"] in processed_raw_ids:
            continue

        published_at = None
        if r.get("published_at"):
            try:
                published_at = datetime.fromisoformat(r["published_at"])
            except Exception:
                pass

        item = RawItem(
            title=r["title"],
            original_url=r["original_url"],
            source_name=r["source_name"],
            source_type=r["source_type"],
            content_type=r["content_type"],
            author=r.get("author", ""),
            author_url=r.get("author_url", ""),
            raw_metrics=_parse_json(r.get("raw_metrics")),
            extra=_parse_json(r.get("extra")),
            published_at=published_at,
        )

        content_data = r.get(cont_tbl) or {}
        content = ContentRecord(
            item_id=r["id"],
            raw_body=content_data.get("raw_body"),
            enriched_body=content_data.get("enriched_body"),
            enriched_source=content_data.get("enriched_source"),
            enriched_quality=content_data.get("enriched_quality"),
            fetch_attempts=content_data.get("fetch_attempts", 0),
        )

        result.append((item, content))

    return result


# ── items_content 操作 ────────────────────────────────────────────

def upsert_content_initial(item_id: str, raw_body: str, content_table: str | None = None) -> None:
    """Stage 1 scrape 时调用：写入 items_content 初始记录（仅 raw_body）。"""
    sb = get_supabase()
    tbl = content_table or CONTENT_TABLE
    sb.table(tbl).upsert({
        "item_id": item_id,
        "raw_body": raw_body,
    }).execute()


def get_content(item_id: str, content_table: str | None = None) -> ContentRecord | None:
    """读取单条 items_content 记录。"""
    sb = get_supabase()
    tbl = content_table or CONTENT_TABLE
    result = sb.table(tbl).select("*").eq("item_id", item_id).limit(1).execute()
    if not result.data:
        return None
    r = result.data[0]
    return ContentRecord(
        item_id=r["item_id"],
        raw_body=r.get("raw_body"),
        enriched_body=r.get("enriched_body"),
        enriched_source=r.get("enriched_source"),
        enriched_quality=r.get("enriched_quality"),
        fetch_attempts=r.get("fetch_attempts", 0),
        last_fetch_error=r.get("last_fetch_error"),
    )


def list_unenriched_items(
    content_table: str | None = None,
    raw_table: str | None = None,
    snapshot_date: str | None = None,
    max_attempts: int = 3,
) -> list[dict]:
    """Stage 1.5 fetch_content 调用：列出待全文抓取的条目。"""
    sb = get_supabase()
    c_tbl = content_table or CONTENT_TABLE
    r_tbl = raw_table or RAW_TABLE

    query = (
        sb.table(c_tbl)
        .select(f"item_id, raw_body, {r_tbl}!inner(original_url, source_name)")
        .is_("enriched_body", "null")
        .lt("fetch_attempts", max_attempts)
    )
    if snapshot_date:
        query = query.eq(f"{r_tbl}.snapshot_date", snapshot_date)

    return query.execute().data


def update_enriched_content(
    item_id: str,
    enriched_body: str,
    enriched_source: str,
    enriched_quality: float | None = None,
    content_table: str | None = None,
) -> None:
    """fetch_content 成功时更新 items_content。"""
    sb = get_supabase()
    tbl = content_table or CONTENT_TABLE
    update = {
        "enriched_body": enriched_body,
        "enriched_source": enriched_source,
        "enriched_at": datetime.now(timezone.utc).isoformat(),
    }
    if enriched_quality is not None:
        update["enriched_quality"] = enriched_quality
    sb.table(tbl).update(update).eq("item_id", item_id).execute()
    # fetch_attempts 通过 SQL 或 RPC 原子 +1，这里用应用层兜底
    sb.rpc("increment_fetch_attempts", {"p_item_id": item_id, "p_table": tbl}).execute()


def record_fetch_failure(item_id: str, error: str, content_table: str | None = None) -> None:
    """fetch_content 失败时记录错误。"""
    sb = get_supabase()
    tbl = content_table or CONTENT_TABLE
    sb.table(tbl).update({
        "last_fetch_error": error[:500],
    }).eq("item_id", item_id).execute()
    sb.rpc("increment_fetch_attempts", {"p_item_id": item_id, "p_table": tbl}).execute()
