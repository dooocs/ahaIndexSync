# stages/aggregate_projects.py
"""
Project Heatmap 聚合阶段：在 archive 之后运行。

职责：
  1. 加载 tracks、subjects、subject_mentions
  2. 匹配 subject → track（使用 LLM 语义匹配）
  3. 计算关联项目（共现分析 + timeline）
  4. 计算竞品（enricher ecosystem 数据 + 共现分析，合并去重）
  5. 增量写入 project_heatmap_data（今天日期的行 + 全量重算 related_data）
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict

from supabase import Client

from infra.llm import call_llm_raw


# 模块级缓存
_TRACKS_CACHE: list[dict] = []

# LLM 匹配配置
_LLM_MODEL = "kimi-k2.6"
_LLM_BASE_URL = "https://api.moonshot.cn/v1"
_LLM_BATCH_SIZE = 25


def _load_existing_track_assignments(sb: Client) -> dict[str, str]:
    """从 project_heatmap_data 加载已有 track_id 映射，用于跳过已匹配的 subject。

    返回: { subject_id: track_id }
    """
    existing: dict[str, str] = {}
    page_size = 1000
    offset = 0
    while True:
        resp = (
            sb.table("project_heatmap_data")
            .select("subject_id, track_id")
            .not_.is_("track_id", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        for r in batch:
            existing[r["subject_id"]] = r["track_id"]
        if len(batch) < page_size:
            break
        offset += page_size

    # subject_tracks 是新的可审计分配层，优先级高于 project_heatmap_data 的缓存。
    try:
        track_rows = (
            sb.table("subject_tracks")
            .select("subject_id, track_id")
            .eq("is_primary", True)
            .is_("valid_to", "null")
            .execute()
            .data
            or []
        )
        for r in track_rows:
            existing[r["subject_id"]] = r["track_id"]
    except Exception as e:
        print(f"  ⚠️ 读取 subject_tracks 失败: {e}")

    return existing


def _load_subject_stats(sb: Client) -> dict[str, dict]:
    """读取 subject_stats 视图，拿到去重后的 mention/时间范围统计。"""
    try:
        rows = (
            sb.table("subject_stats")
            .select("subject_id, mention_count, first_seen_at, last_seen_at, item_count")
            .execute()
            .data
            or []
        )
    except Exception as e:
        print(f"  ⚠️ 读取 subject_stats 失败: {e}")
        return {}

    return {r["subject_id"]: r for r in rows}


def _match_subjects_via_llm(
    subjects: list[dict],
    tracks: list[dict],
    subject_tags_map: dict[str, list[str]],
    existing_assignments: dict[str, str],
    api_key: str,
) -> dict[str, tuple[str | None, str | None, str | None]]:
    """使用 LLM 批量匹配 subject → track。

    返回: { subject_id: (track_id, track_name, track_group) }
    """
    # 构建 track slug → track 映射
    track_by_slug: dict[str, dict] = {t["slug"]: t for t in tracks}

    # 构建 subject slug → subject_id 映射
    subject_id_by_slug: dict[str, str] = {s["slug"]: s["id"] for s in subjects}

    # 过滤掉已匹配的 subjects
    unmatched = [s for s in subjects if s["id"] not in existing_assignments]
    print(f"  LLM 匹配: {len(unmatched)} 待匹配, {len(existing_assignments)} 已有缓存")

    if not unmatched:
        # 全部已缓存，直接返回
        result: dict[str, tuple[str | None, str | None, str | None]] = {}
        track_by_id: dict[str, dict] = {t["id"]: t for t in tracks}
        for s in subjects:
            sid = s["id"]
            cached_track_id = existing_assignments.get(sid)
            if cached_track_id and cached_track_id in track_by_id:
                t = track_by_id[cached_track_id]
                result[sid] = (t["id"], t["display_name"], t["group_name"])
            else:
                result[sid] = (None, None, None)
        return result

    # 构建 tracks 文本
    tracks_text = "\n".join(
        f"- {t['slug']} | {t['display_name']} | {t.get('description') or '无描述'}"
        for t in tracks
    )

    # 分批调用 LLM
    result: dict[str, tuple[str | None, str | None, str | None]] = {}
    track_by_id: dict[str, dict] = {t["id"]: t for t in tracks}

    # 先把已有缓存的结果填入
    for s in subjects:
        sid = s["id"]
        cached_track_id = existing_assignments.get(sid)
        if cached_track_id and cached_track_id in track_by_id:
            t = track_by_id[cached_track_id]
            result[sid] = (t["id"], t["display_name"], t["group_name"])

    batches = [unmatched[i : i + _LLM_BATCH_SIZE] for i in range(0, len(unmatched), _LLM_BATCH_SIZE)]

    for batch_idx, batch in enumerate(batches):
        # 构建 subjects 文本
        subjects_lines = []
        for s in batch:
            sid = s["id"]
            tags = subject_tags_map.get(sid, [])[:10]
            tags_str = ", ".join(tags) if tags else "无标签"
            subjects_lines.append(f"- {s['slug']} | {s['display_name']} | 标签: {tags_str}")
        subjects_text = "\n".join(subjects_lines)

        prompt = f"""你是一个项目分类专家。请将以下开源项目分配到最合适的技术赛道。

## 赛道列表
{tracks_text}

## 待分类项目（第 {batch_idx + 1}/{len(batches)} 批）
{subjects_text}

请返回 JSON:
{{"assignments": [{{"subject_slug": "github:x/y", "track_slug": "coding-agents"}}, ...]}}

规则：
- 每个项目只能分配到一个赛道
- 如果没有合适的赛道，track_slug 设为 null
- 必须返回所有项目，不能遗漏
- track_slug 必须是上面赛道列表中给出的 slug 之一"""

        llm_result = call_llm_raw(
            prompt=prompt,
            model=_LLM_MODEL,
            base_url=_LLM_BASE_URL,
            api_key=api_key,
            system_prompt="你是一个项目分类专家。只输出 JSON，不要输出其他内容。",
            temperature=0.1,
            timeout=60,
        )

        if not llm_result or "assignments" not in llm_result:
            print(f"  ⚠️ LLM 匹配第 {batch_idx + 1} 批失败，跳过")
            continue

        assignments = llm_result["assignments"]
        matched_in_batch = 0
        for a in assignments:
            slug = a.get("subject_slug", "")
            track_slug = a.get("track_slug")

            sub_id = subject_id_by_slug.get(slug)
            if not sub_id:
                continue

            if track_slug and track_slug in track_by_slug:
                t = track_by_slug[track_slug]
                result[sub_id] = (t["id"], t["display_name"], t["group_name"])
                matched_in_batch += 1
            else:
                result[sub_id] = (None, None, None)

        print(f"  LLM 匹配第 {batch_idx + 1}/{len(batches)} 批: {matched_in_batch}/{len(batch)} 匹配成功")

    # 未被 LLM 处理的 subject（理论上不应出现）
    for s in subjects:
        if s["id"] not in result:
            result[s["id"]] = (None, None, None)

    return result


def _load_all_subjects(sb: Client) -> list[dict]:
    """加载所有 type=project 的 subjects。"""
    rows = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            sb.table("subjects")
            .select("id, slug, display_name, description, metadata, first_seen_at, last_seen_at, mention_count")
            .eq("type", "project")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def _load_all_mentions(sb: Client) -> list[dict]:
    """加载所有 subject_mentions。"""
    rows = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            sb.table("subject_mentions")
            .select("subject_id, item_id, snapshot_date, role, source_name, score")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def _load_item_tags(sb: Client, item_ids: set[str]) -> dict[str, list[str]]:
    """从 processed_items 批量加载 item 的 tags。"""
    result: dict[str, list[str]] = {}
    ids_list = list(item_ids)
    page_size = 500
    for i in range(0, len(ids_list), page_size):
        batch_ids = ids_list[i : i + page_size]
        resp = (
            sb.table("processed_items")
            .select("item_id, tags")
            .in_("item_id", batch_ids)
            .execute()
        )
        for r in (resp.data or []):
            tags = r.get("tags") or []
            if tags:
                result[r["item_id"]] = tags
    return result


def _load_item_aha_scores(sb: Client, item_ids: set[str]) -> dict[str, float]:
    """从 display_items 批量加载 item 的最新 aha_index。"""
    result: dict[str, float] = {}
    ids_list = list(item_ids)
    page_size = 500
    for i in range(0, len(ids_list), page_size):
        batch_ids = ids_list[i : i + page_size]
        resp = (
            sb.table("display_items")
            .select("processed_item_id, aha_index, snapshot_date")
            .in_("processed_item_id", batch_ids)
            .order("snapshot_date", desc=True)
            .execute()
        )
        for r in (resp.data or []):
            pid = r["processed_item_id"]
            if pid not in result:
                result[pid] = float(r.get("aha_index") or 0)
    return result


def _load_enricher_competitors(sb: Client) -> dict[str, list[dict]]:
    """从 item_enrichments 加载 ecosystem 类型的竞品数据。

    返回: { repo_full_name: [ {name, comparison, stars}, ... ] }
    """
    result: dict[str, list[dict]] = {}
    rows = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            sb.table("item_enrichments")
            .select("data")
            .eq("enrichment_type", "ecosystem")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    for r in rows:
        data = r.get("data") or {}
        repo_name = data.get("repo_full_name")
        if not repo_name:
            continue
        competitors = data.get("competitors") or []
        if competitors:
            result[repo_name] = competitors
    return result


def _load_existing_heatmap(sb: Client) -> dict[str, dict]:
    """加载 project_heatmap_data 中已有的 related_data，用于合并。

    返回: { subject_id: row_dict }
    """
    existing: dict[str, dict] = {}
    page_size = 1000
    offset = 0
    while True:
        resp = (
            sb.table("project_heatmap_data")
            .select("subject_id, related_data")
            .not_.is_("related_data", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        for r in batch:
            existing[r["subject_id"]] = r
        if len(batch) < page_size:
            break
        offset += page_size
    return existing


def run_aggregate_projects(sb: Client, today: str) -> dict:
    """Project Heatmap 聚合主入口。

    Args:
        sb: Supabase client
        today: 日期字符串 YYYY-MM-DD

    Returns:
        统计信息 dict
    """
    print(f"=== Project Heatmap 聚合 {today} ===")

    # ── 1. 加载基础数据 ──
    global _TRACKS_CACHE
    tracks_resp = sb.table("tracks").select("*").eq("status", "active").order("display_order").execute()
    _TRACKS_CACHE = tracks_resp.data or []
    print(f"  加载 tracks: {len(_TRACKS_CACHE)}")

    subjects = _load_all_subjects(sb)
    print(f"  加载 subjects (project): {len(subjects)}")

    subject_stats = _load_subject_stats(sb)
    if subject_stats:
        for subject in subjects:
            stat = subject_stats.get(subject["id"])
            if not stat:
                continue
            subject["mention_count"] = stat.get("mention_count", subject.get("mention_count"))
            subject["first_seen_at"] = stat.get("first_seen_at") or subject.get("first_seen_at")
            subject["last_seen_at"] = stat.get("last_seen_at") or subject.get("last_seen_at")
            subject["item_count"] = stat.get("item_count")
        print(f"  合并 subject_stats: {len(subject_stats)}")

    mentions = _load_all_mentions(sb)
    print(f"  加载 subject_mentions: {len(mentions)}")

    # 收集所有 item_id
    all_item_ids = {m["item_id"] for m in mentions}

    item_tags = _load_item_tags(sb, all_item_ids)
    print(f"  加载 item tags: {len(item_tags)}")

    item_aha = _load_item_aha_scores(sb, all_item_ids)
    print(f"  加载 item aha_scores: {len(item_aha)}")

    enricher_competitors = _load_enricher_competitors(sb)
    print(f"  加载 enricher 竞品数据: {len(enricher_competitors)}")

    # ── 2. 构建辅助索引 ──

    # subject_id → subject dict
    subject_map: dict[str, dict] = {s["id"]: s for s in subjects}

    # subject_id → [mention, ...]
    subject_mentions_map: dict[str, list[dict]] = defaultdict(list)
    for m in mentions:
        subject_mentions_map[m["subject_id"]].append(m)

    # item_id → [subject_id, ...]（同一 item 被多个 subject 引用 → 共现）
    item_to_subjects: dict[str, list[str]] = defaultdict(list)
    for m in mentions:
        item_to_subjects[m["item_id"]].append(m["subject_id"])

    # 构建 subject → tags 映射（供 LLM 匹配使用）
    subject_tags_map: dict[str, list[str]] = {}
    for s in subjects:
        sid = s["id"]
        tags: list[str] = []
        for m in subject_mentions_map.get(sid, []):
            tags.extend(item_tags.get(m["item_id"], []))
        subject_tags_map[sid] = list(dict.fromkeys(tags))

    # ── 3. LLM 匹配 subject → track ──
    existing_assignments = _load_existing_track_assignments(sb)
    api_key = os.getenv("KIMI_API_KEY", "")
    subject_track = _match_subjects_via_llm(
        subjects, _TRACKS_CACHE, subject_tags_map, existing_assignments, api_key
    )

    matched_count = sum(1 for v in subject_track.values() if v[0] is not None)
    print(f"  track 匹配: {matched_count}/{len(subjects)}")

    # ── 4. 计算共现矩阵 ──
    # co_occurrence[(a_id, b_id)] = 共现次数
    co_occurrence: Counter = Counter()
    for item_id, sub_ids in item_to_subjects.items():
        unique_ids = list(set(sub_ids))
        for i in range(len(unique_ids)):
            for j in range(i + 1, len(unique_ids)):
                pair = tuple(sorted([unique_ids[i], unique_ids[j]]))
                co_occurrence[pair] += 1

    # ── 5. 构建关联项目 + 竞品数据 ──
    MIN_CO_OCCURRENCE = 1  # 最低共现次数阈值

    subject_related: dict[str, dict] = {}  # subject_id → {related: [...], competitors: [...]}

    for s in subjects:
        sid = s["id"]
        slug = s["slug"]
        display_name = s["display_name"]
        sub_track_id, sub_track_name, sub_track_group = subject_track.get(sid, (None, None, None))

        # 找关联项目
        related_list: list[dict] = []
        for (a, b), count in co_occurrence.items():
            if a == sid:
                other_id = b
            elif b == sid:
                other_id = a
            else:
                continue
            if count < MIN_CO_OCCURRENCE:
                continue

            other = subject_map.get(other_id)
            if not other:
                continue

            other_track_id, other_track_name, other_track_group = subject_track.get(other_id, (None, None, None))

            # 判断关系 kind
            if sub_track_id and other_track_id and sub_track_id == other_track_id:
                kind = "竞品"
            elif sub_track_group and other_track_group and sub_track_group == other_track_group:
                kind = "互通"
            else:
                kind = "生态"

            # 构建 timeline
            timeline: list[dict] = []
            for m in subject_mentions_map.get(other_id, []):
                aha = m.get("score")
                if aha is not None:
                    timeline.append({
                        "date": str(m["snapshot_date"]),
                        "aha": round(float(aha) * 100, 1),
                    })
            timeline.sort(key=lambda x: x["date"])

            related_list.append({
                "subject_id": other_id,
                "slug": other["slug"],
                "display_name": other["display_name"],
                "strength": min(count / 5.0, 1.0),  # 归一化
                "kind": kind,
                "co_appearances": count,
                "timeline": timeline,
            })

        # 按 strength 降序，取 top 20
        related_list.sort(key=lambda x: x["strength"], reverse=True)
        related_list = related_list[:20]

        # 构建竞品列表（enricher 数据 + 共现补充）
        competitors_list: list[dict] = []
        seen_comp_slugs: set[str] = set()

        # 来源 1: enricher ecosystem 数据
        repo_full_name = (s.get("metadata") or {}).get("repo_full_name")
        if repo_full_name:
            for comp in enricher_competitors.get(repo_full_name, []):
                comp_name = (comp.get("name") or "").strip()
                if not comp_name:
                    continue
                comp_slug = f"github:{comp_name.lower()}"
                seen_comp_slugs.add(comp_slug)
                competitors_list.append({
                    "subject_id": "",  # 后续尝试匹配
                    "slug": comp_slug,
                    "display_name": comp_name,
                    "strength": 0.8,
                    "kind": "竞品",
                    "co_appearances": 0,
                    "source": "enricher",
                    "aha_current": 0,
                    "overlap_tags": [],
                    "diff": comp.get("comparison") or "",
                })

        # 来源 2: 共现分析中同 track 的项目（补充 enricher 未覆盖的）
        for rel in related_list:
            if rel["kind"] != "竞品":
                continue
            if rel["slug"] in seen_comp_slugs:
                continue
            seen_comp_slugs.add(rel["slug"])
            competitors_list.append({
                "subject_id": rel["subject_id"],
                "slug": rel["slug"],
                "display_name": rel["display_name"],
                "strength": rel["strength"],
                "kind": "竞品",
                "co_appearances": rel["co_appearances"],
                "source": "co_appearance",
                "aha_current": 0,
                "overlap_tags": [],
                "diff": "",
            })

        # 尝试为 enricher 竞品匹配 subject_id 和 aha_current
        for comp in competitors_list:
            if not comp["subject_id"]:
                # 通过 slug 查找
                for other_s in subjects:
                    if other_s["slug"] == comp["slug"]:
                        comp["subject_id"] = other_s["id"]
                        # 计算 aha_current
                        other_mentions = subject_mentions_map.get(other_s["id"], [])
                        if other_mentions:
                            latest = max(other_mentions, key=lambda m: str(m["snapshot_date"]))
                            comp["aha_current"] = round(float(latest.get("score") or 0) * 100, 1)
                        break

            if comp["subject_id"] and not comp["aha_current"]:
                other_mentions = subject_mentions_map.get(comp["subject_id"], [])
                if other_mentions:
                    latest = max(other_mentions, key=lambda m: str(m["snapshot_date"]))
                    comp["aha_current"] = round(float(latest.get("score") or 0) * 100, 1)

            # 计算 overlap_tags
            sub_tags_set = set()
            for m in subject_mentions_map.get(sid, []):
                sub_tags_set.update(item_tags.get(m["item_id"], []))
            comp_tags_set = set()
            if comp["subject_id"]:
                for m in subject_mentions_map.get(comp["subject_id"], []):
                    comp_tags_set.update(item_tags.get(m["item_id"], []))
            comp["overlap_tags"] = list(sub_tags_set & comp_tags_set)[:5]

        subject_related[sid] = {
            "related": related_list,
            "competitors": competitors_list[:10],
        }

    print(f"  构建关联数据: {len(subject_related)} subjects")

    # ── 6. 写入 project_heatmap_data ──

    # 6a. 今天的行（增量）
    today_rows: list[dict] = []
    for s in subjects:
        sid = s["id"]
        slug = s["slug"]
        display_name = s["display_name"]
        track_id, track_name, track_group = subject_track.get(sid, (None, None, None))

        # 找今天日期的 mention（取最高分）
        today_mentions = [m for m in subject_mentions_map.get(sid, []) if str(m["snapshot_date"]) == today]
        if not today_mentions:
            # 今天没有 mention，但仍然写入 related_data（用于详情页）
            # 只有当 subject 有历史 mention 时才写入
            if not subject_mentions_map.get(sid):
                continue
            # 无今天的 mention，score 留空
            best_mention = None
            score = None
            role = None
            source_name = None
        else:
            best_mention = max(today_mentions, key=lambda m: float(m.get("score") or 0))
            score = float(best_mention.get("score") or 0)
            role = best_mention.get("role")
            source_name = best_mention.get("source_name")

        # 收集 tags（从关联 items 合并）
        all_tags: list[str] = []
        for m in subject_mentions_map.get(sid, []):
            all_tags.extend(item_tags.get(m["item_id"], []))
        unique_tags = list(dict.fromkeys(all_tags))[:20]

        row = {
            "subject_id": sid,
            "subject_slug": slug,
            "subject_name": display_name,
            "subject_type": "project",
            "track_id": track_id,
            "track_name": track_name,
            "track_group": track_group,
            "snapshot_date": today,
            "score": score,
            "score_100": round(score * 100, 1) if score is not None else None,
            "role": role,
            "source_name": source_name,
            "tags": unique_tags,
            "summary": s.get("description"),
            "first_seen_at": str(s.get("first_seen_at")) if s.get("first_seen_at") else None,
            "last_seen_at": str(s.get("last_seen_at")) if s.get("last_seen_at") else None,
            "mention_count": s.get("mention_count") or 0,
            "related_data": subject_related.get(sid),
        }
        today_rows.append(row)

    # 批量 upsert 今天的行
    written_today = 0
    if today_rows:
        page_size = 100
        for i in range(0, len(today_rows), page_size):
            batch = today_rows[i : i + page_size]
            try:
                sb.table("project_heatmap_data").upsert(
                    batch, on_conflict="subject_id,snapshot_date"
                ).execute()
                written_today += len(batch)
            except Exception as e:
                print(f"  ⚠️ 批量写入失败 (offset={i}): {e}")
                # 逐条重试
                for row in batch:
                    try:
                        sb.table("project_heatmap_data").upsert(
                            row, on_conflict="subject_id,snapshot_date"
                        ).execute()
                        written_today += 1
                    except Exception as ee:
                        print(f"    ↳ 单条写入失败 {row['subject_slug']}: {ee}")

    # 6b. 更新所有已有行的 related_data（全量重算）
    updated_related = 0
    existing = _load_existing_heatmap(sb)
    for sid, related in subject_related.items():
        if sid in existing:
            try:
                sb.table("project_heatmap_data").update({
                    "related_data": related,
                }).eq("subject_id", sid).execute()
                updated_related += 1
            except Exception as e:
                print(f"  ⚠️ 更新 related_data 失败 {sid}: {e}")

    stats = {
        "subjects_total": len(subjects),
        "tracks_matched": matched_count,
        "mentions_total": len(mentions),
        "rows_written_today": written_today,
        "related_data_updated": updated_related,
    }

    print(
        f"📊 Project Heatmap 完成: subjects={stats['subjects_total']} "
        f"matched={stats['tracks_matched']} "
        f"written_today={stats['rows_written_today']} "
        f"related_updated={stats['related_data_updated']}"
    )
    return stats
