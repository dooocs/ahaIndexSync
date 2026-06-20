"""
Pipeline 编排器：加载配置 → 按阶段顺序执行。
"""

from __future__ import annotations

import os
from datetime import datetime

from supabase import create_client
from dotenv import load_dotenv

from pipeline.config_loader import load_config
from pipeline.run_tracker import RunTracker


def get_supabase():
    load_dotenv()
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def run_pipeline(
    mode: str = "daily",
    table_suffix: str = "",
    scraper_name: str = "",
    override_date: str | None = None,
):
    if override_date:
        from infra.time_utils import set_override_date
        set_override_date(override_date)
        print(f"📅 使用指定日期: {override_date}")

    start_time = datetime.now()
    print(f"\n{'═' * 60}")
    print(f"🚀 Pipeline 启动 | mode={mode} | {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 60}\n")

    sb = get_supabase()
    config = load_config(sb)

    if scraper_name:
        config.scrapers = [s for s in config.scrapers if s.name == scraper_name or s.scraper_type == scraper_name or s.slug == scraper_name]
        if not config.scrapers:
            print(f"❌ 找不到 scraper: {scraper_name}")
            return

    tracker = RunTracker(sb, run_type=mode, table_suffix=table_suffix)
    tracker.start_run(config.to_snapshot())

    stats = {
        "scraped": 0,
        "fetched_content": 0,
        "processed": 0,
        "coarse_survived": 0,
        "enriched": 0,
        "ranked": 0,
        "archived": 0,
        "subject_insights": 0,
        "aggregated": 0,
        "errors": 0,
    }

    # 计算 snapshot_date 供各 stage 使用
    from infra.time_utils import get_today_str
    from datetime import date as date_cls
    snapshot_date_str = override_date or get_today_str()
    snapshot_date = date_cls.fromisoformat(snapshot_date_str)

    try:
        # Stage 1: Scrape
        print(f"\n{'─' * 40}")
        print("📡 Stage 1: Scrape")
        print(f"{'─' * 40}")
        from stages.scrape import run_scrape
        scrape_stats = run_scrape(sb, config, tracker, table_suffix, snapshot_date=snapshot_date)
        stats["scraped"] = scrape_stats.get("saved", 0)
        stats["errors"] += scrape_stats.get("errors", 0)

        # Stage 1.3: Tweet Aggregate (推文聚合)
        print(f"\n{'─' * 40}")
        print("🐦 Stage 1.3: Tweet Aggregate")
        print(f"{'─' * 40}")
        try:
            from stages.tweet_aggregate import run_tweet_aggregate
            agg_stats = run_tweet_aggregate(sb, config, table_suffix, snapshot_date=snapshot_date)
            stats["tweets_aggregated"] = agg_stats.get("aggregated", 0)
        except Exception as e:
            print(f"⚠️ Tweet Aggregate 阶段异常（降级为单独推文）: {e}")

        # Stage 1.5: Fetch Content (全文抓取)
        print(f"\n{'─' * 40}")
        print("📥 Stage 1.5: Fetch Content")
        print(f"{'─' * 40}")
        try:
            from stages.fetch_content import run_fetch_content
            fetch_stats = run_fetch_content(sb, config, table_suffix, snapshot_date=snapshot_date_str)
            stats["fetched_content"] = fetch_stats.get("success", 0)
        except Exception as e:
            print(f"⚠️ Fetch Content 阶段异常（降级为无全文）: {e}")

        # Stage 2: Process
        print(f"\n{'─' * 40}")
        print("🤖 Stage 2: Process")
        print(f"{'─' * 40}")
        from stages.process import run_process
        process_stats = run_process(sb, config, table_suffix, snapshot_date=snapshot_date_str)
        stats["processed"] = process_stats.get("success", 0)
        stats["errors"] += process_stats.get("failed", 0)

        # Stage 3a: Coarse Filter
        print(f"\n{'─' * 40}")
        print("🪓 Stage 3a: Coarse Filter")
        print(f"{'─' * 40}")
        from stages.coarse_filter import run_coarse_filter
        coarse_stats = run_coarse_filter(sb, config, table_suffix)
        candidates = coarse_stats.get("items", [])
        stats["coarse_survived"] = coarse_stats.get("survived", 0)

        # Stage 3b: Enrich (不可阻塞主管道：单 enricher 容错 + 总体超时)
        print(f"\n{'─' * 40}")
        print("🧩 Stage 3b: Enrich")
        print(f"{'─' * 40}")
        try:
            from stages.enrich import run_enrich
            enrich_stats = run_enrich(sb, config, candidates, table_suffix)
            stats["enriched"] = enrich_stats.get("enrichments_written", 0)
        except Exception as e:
            print(f"⚠️ Enrich 阶段整体异常（降级为无 enrichment）: {e}")

        # Stage 4: Rank
        print(f"\n{'─' * 40}")
        print("🏆 Stage 4: Rank")
        print(f"{'─' * 40}")
        from stages.rank import run_rank
        rank_stats = run_rank(sb, config, table_suffix, candidates=candidates)
        stats["ranked"] = rank_stats.get("display_count", 0)

        # Stage 5: Archive (only for production runs)
        if not table_suffix:
            print(f"\n{'─' * 40}")
            print("📦 Stage 5: Archive")
            print(f"{'─' * 40}")
            from stages.archive import run_archive
            archive_stats = run_archive(sb, config)
            stats["archived"] = archive_stats.get("daily", 0)

            # Stage 5.5: Subject Insights (only for production runs)
            print(f"\n{'─' * 40}")
            print("🧭 Stage 5.5: Subject Insights")
            print(f"{'─' * 40}")
            try:
                from stages.subject_insights import run_subject_insights
                insights_stats = run_subject_insights(sb, config, snapshot_date_str)
                stats["subject_insights"] = insights_stats.get("written", 0)
                stats["subject_insights_failed"] = insights_stats.get("failed", 0)
            except Exception as e:
                print(f"⚠️ Subject Insights 阶段异常（跳过）: {e}")

            # Stage 6: Aggregate Projects (only for production runs)
            print(f"\n{'─' * 40}")
            print("📊 Stage 6: Aggregate Projects")
            print(f"{'─' * 40}")
            from stages.aggregate_projects import run_aggregate_projects
            from infra.time_utils import get_today_str
            agg_stats = run_aggregate_projects(sb, get_today_str())
            stats["aggregated"] = agg_stats.get("rows_written_today", 0)

        tracker.finish_run(stats)

    except Exception as e:
        stats["errors"] += 1
        tracker.finish_run(stats, error=str(e))
        print(f"\n❌ Pipeline 失败: {e}")
        raise

    total_cost = (datetime.now() - start_time).total_seconds()
    print(f"\n{'═' * 60}")
    print(f"✨ Pipeline 完成 | {total_cost:.1f}s | scraped={stats['scraped']} "
          f"fetched={stats['fetched_content']} processed={stats['processed']} "
          f"coarse={stats['coarse_survived']} enriched={stats['enriched']} "
          f"ranked={stats['ranked']} archived={stats['archived']} "
          f"subject_insights={stats['subject_insights']} "
          f"aggregated={stats['aggregated']} errors={stats['errors']}")
    print(f"{'═' * 60}\n")
