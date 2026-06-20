"""
从 Supabase 加载全部配置，返回 PipelineConfig 快照。
Pipeline 启动时调用一次，整个运行周期使用同一份配置。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from supabase import Client


@dataclass
class PromptConfig:
    name: str
    stage: str
    template: str
    model: str
    model_base_url: str
    temperature: float
    max_retries: int
    request_interval: float
    version: int

    def render(self, **kwargs) -> str:
        text = self.template
        for k, v in kwargs.items():
            text = text.replace(f"{{{k}}}", str(v))
        return text


@dataclass
class ScraperConfig:
    id: str
    scraper_type: str
    name: str
    priority: int
    config: dict
    slug: str = ''
    source_type: str = ''
    content_type: str = ''


@dataclass
class RankGroupConfig:
    group_name: str
    source_names: list[str]
    limit: int
    must_include: bool
    sort_order: int


@dataclass
class TagSlotConfig:
    tag_name: str
    max_slots: int
    min_score: float


@dataclass
class DisplayMetricConfig:
    content_type: str
    metrics: list[dict]


@dataclass
class ContentFetchRule:
    rule_type: str
    value: str


@dataclass
class PipelineConfig:
    scrapers: list[ScraperConfig] = field(default_factory=list)
    prompts: dict[str, PromptConfig] = field(default_factory=dict)
    rank_groups: list[RankGroupConfig] = field(default_factory=list)
    tag_slots: list[TagSlotConfig] = field(default_factory=list)
    params: dict[str, any] = field(default_factory=dict)
    display_metrics: dict[str, list[dict]] = field(default_factory=dict)
    fetch_rules: list[ContentFetchRule] = field(default_factory=list)

    def get_param(self, key: str, default=None):
        val = self.params.get(key, default)
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val
        return val

    def get_prompt(self, name: str) -> PromptConfig | None:
        return self.prompts.get(name)

    @property
    def skip_domains(self) -> set[str]:
        return {r.value for r in self.fetch_rules if r.rule_type == "skip_domain"}

    @property
    def fulltext_tags(self) -> set[str]:
        return {r.value for r in self.fetch_rules if r.rule_type == "fetch_fulltext_tag"}

    def to_snapshot(self) -> dict:
        return {
            "scrapers": [{"id": s.id, "type": s.scraper_type, "name": s.name, "slug": s.slug} for s in self.scrapers],
            "prompts": {k: {"model": v.model, "version": v.version} for k, v in self.prompts.items()},
            "rank_groups": [{"group": g.group_name, "limit": g.limit} for g in self.rank_groups],
            "tag_slots": {t.tag_name: t.max_slots for t in self.tag_slots},
            "params": self.params,
        }


def _select_rows(label: str, build_query: Callable[[], Any], attempts: int = 5) -> list[dict]:
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            return build_query().execute().data or []
        except Exception as exc:
            if attempt == attempts:
                raise
            print(f"⚠️ 配置读取失败 [{label}] {attempt}/{attempts}: {exc}，{delay:.1f}s 后重试")
            time.sleep(delay)
            delay *= 2
    return []


def load_config(sb: Client) -> PipelineConfig:
    cfg = PipelineConfig()

    rows = _select_rows(
        "scraper_configs",
        lambda: sb.table("scraper_configs").select("*").eq("enabled", True).order("priority"),
    )
    cfg.scrapers = [
        ScraperConfig(
            id=r["id"], scraper_type=r["scraper_type"], name=r["name"],
            priority=r["priority"], config=r["config"] if isinstance(r["config"], dict) else json.loads(r["config"]),
            slug=r.get("slug", ""),
            source_type=r.get("source_type", ""),
            content_type=r.get("content_type", ""),
        )
        for r in rows
    ]

    rows = _select_rows(
        "prompt_templates",
        lambda: sb.table("prompt_templates").select("*").eq("enabled", True),
    )
    cfg.prompts = {
        r["name"]: PromptConfig(
            name=r["name"], stage=r["stage"], template=r["template"],
            model=r["model"], model_base_url=r.get("model_base_url", "https://api.moonshot.cn/v1"),
            temperature=r["temperature"], max_retries=r["max_retries"],
            request_interval=r["request_interval"], version=r["version"],
        )
        for r in rows
    }

    rows = _select_rows(
        "rank_group_configs",
        lambda: sb.table("rank_group_configs").select("*").eq("enabled", True).order("sort_order"),
    )
    cfg.rank_groups = [
        RankGroupConfig(
            group_name=r["group_name"], source_names=r["source_names"],
            limit=r["limit"], must_include=r["must_include"], sort_order=r["sort_order"],
        )
        for r in rows
    ]

    rows = _select_rows(
        "tag_slot_configs",
        lambda: sb.table("tag_slot_configs").select("*").eq("enabled", True),
    )
    cfg.tag_slots = [TagSlotConfig(tag_name=r["tag_name"], max_slots=r["max_slots"], min_score=r["min_score"]) for r in rows]

    rows = _select_rows(
        "pipeline_params",
        lambda: sb.table("pipeline_params").select("*"),
    )
    cfg.params = {r["key"]: r["value"] for r in rows}

    rows = _select_rows(
        "display_metrics_configs",
        lambda: sb.table("display_metrics_configs").select("*"),
    )
    cfg.display_metrics = {
        r["content_type"]: r["metrics"] if isinstance(r["metrics"], list) else json.loads(r["metrics"])
        for r in rows
    }

    rows = _select_rows(
        "content_fetch_rules",
        lambda: sb.table("content_fetch_rules").select("*").eq("enabled", True),
    )
    cfg.fetch_rules = [ContentFetchRule(rule_type=r["rule_type"], value=r["value"]) for r in rows]

    print(f"📋 配置加载完成: {len(cfg.scrapers)} scrapers, {len(cfg.prompts)} prompts, "
          f"{len(cfg.rank_groups)} rank groups, {len(cfg.tag_slots)} tag slots")

    return cfg
