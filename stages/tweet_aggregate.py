# stages/tweet_aggregate.py
"""
Twitter 推文聚合阶段
--------------------
在 scrape 之后、fetch_content 之前运行。
将当天所有 tweet 类型的 raw_items 聚合为一条 tweet_digest。
"""

from __future__ import annotations

from datetime import date

from supabase import Client
from pipeline.config_loader import PipelineConfig
from infra.db import table_names, upsert_raw_item, upsert_content_initial
from infra.models import RawItem


def _twitter_scraper_snapshot(config: PipelineConfig) -> tuple[str, dict]:
    """Return the source scraper slug/config used for the synthetic digest row."""
    for sc in getattr(config, "scrapers", []) or []:
        if sc.name == "X (Twitter)" or sc.scraper_type == "twitter_twscrape":
            return sc.slug or "x-twitter-", sc.config or {}
    return "x-twitter-", {}


def run_tweet_aggregate(
    sb: Client,
    config: PipelineConfig,
    table_suffix: str = "",
    snapshot_date: date | None = None,
) -> dict:
    raw_table, _, _, content_table = table_names(table_suffix)
    today = snapshot_date or date.today()
    today_str = today.isoformat()

    # 读取当天所有 tweet 类型的 raw_items
    rows = (
        sb.table(raw_table)
        .select(f"*, {content_table}(raw_body)")
        .eq("snapshot_date", today_str)
        .eq("content_type", "tweet")
        .execute()
        .data
        or []
    )

    if not rows:
        print("  📭 无推文，跳过聚合")
        return {"aggregated": 0}

    # 聚合指标
    total_likes = 0
    total_retweets = 0
    total_replies = 0
    total_views = 0
    tweets = []

    for r in rows:
        rm = r.get("raw_metrics") or {}
        if isinstance(rm, str):
            import json
            try:
                rm = json.loads(rm)
            except Exception:
                rm = {}

        likes = rm.get("likes", 0) or 0
        retweets = rm.get("retweets", 0) or 0
        replies = rm.get("replies", 0) or 0
        views = rm.get("views", 0) or 0

        total_likes += likes
        total_retweets += retweets
        total_replies += replies
        total_views += views

        ext = r.get("extra") or {}
        if isinstance(ext, str):
            import json
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        content = r.get(content_table) or {}
        if isinstance(content, list):
            content = content[0] if content else {}
        text = content.get("raw_body") or r.get("title", "")

        tweets.append({
            "author": r.get("author", ""),
            "display_name": ext.get("display_name", ""),
            "text": text,
            "likes": likes,
            "retweets": retweets,
            "url": r.get("original_url", ""),
            "tweet_id": ext.get("tweet_id", ""),
        })

    # 按 likes 排序
    tweets.sort(key=lambda t: t["likes"], reverse=True)

    # 生成标题：取 top 3 作者
    top_authors = list(dict.fromkeys(t["author"] for t in tweets if t["author"]))[:3]
    author_str = "、".join(f"@{a}" for a in top_authors) if top_authors else "AI 圈"
    title = f"{author_str} 等 {len(tweets)} 条推文热议"

    # 构造 digest item
    body_text = "\n\n".join(
        f"@{t['author']}: {t['text']}" for t in tweets
    )

    # 插入聚合后的 digest，并同步写入 items_content。
    # Stage 2 通过 raw_items JOIN items_content 查待处理项；缺少 content 记录会导致 digest 永远不进入展示链路。
    scraper_slug, scraper_config_snapshot = _twitter_scraper_snapshot(config)
    digest = RawItem(
        title=title,
        original_url=f"tweet_digest://{today_str}",
        source_name="X (Twitter)",
        source_type="TWEET",
        content_type="tweet_digest",
        author=", ".join(top_authors),
        body_text=body_text,
        raw_metrics={
            "likes": total_likes,
            "retweets": total_retweets,
            "replies": total_replies,
            "views": total_views,
            "tweet_count": len(tweets),
        },
        extra={
            "tweets": tweets,
        },
        published_at=today,
        snapshot_date=today,
        scraper_slug=scraper_slug,
        scraper_config_snapshot=scraper_config_snapshot,
    )
    upsert_raw_item(digest, raw_table)
    upsert_content_initial(digest.id, digest.body_text, content_table)

    # digest 写入成功后再删除原始 tweet，避免约束或网络错误导致原文先丢失。
    tweet_ids = [r["id"] for r in rows]
    if tweet_ids:
        batch_size = 100
        for i in range(0, len(tweet_ids), batch_size):
            batch = tweet_ids[i:i + batch_size]
            sb.table(raw_table).delete().in_("id", batch).execute()
        for i in range(0, len(tweet_ids), batch_size):
            batch = tweet_ids[i:i + batch_size]
            sb.table(content_table).delete().in_("item_id", batch).execute()

    print(f"  🐦 聚合 {len(tweets)} 条推文 → 1 条 digest（❤️ {total_likes} 🔁 {total_retweets}）")
    return {"aggregated": len(tweets), "digest_id": digest.id}
