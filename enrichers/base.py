# enrichers/base.py
"""Enricher 基础协议与数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from supabase import Client

from pipeline.config_loader import PipelineConfig
from infra.db import enrich_table_names


@dataclass
class SubjectCandidate:
    """Enricher 在增厚过程中发现的 subject 候选。"""
    slug: str
    type: str
    display_name: str
    description: str = ""
    homepage_url: str = ""
    aliases: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    role: str = "mentioned"
    context: str = ""
    reason: str = ""
    confidence: float | None = None
    proposed_by: str = "ai"
    extractor_version: str = ""


@dataclass
class EnrichmentResult:
    """单个 enricher 对单条 item 的产出。"""
    enrichment_type: str
    enricher_name: str
    data: dict[str, Any]
    subject_candidates: list[SubjectCandidate] = field(default_factory=list)


class BaseEnricher:
    """所有 enricher 的基类。子类通过 @register 注册。

    - preload(): 一次性预取需要的数据（如 Cross Reference 查询历史）
      在整个批次开始时被调用，避免逐条查询。子类可选实现。
    - applies_to(item): 判断是否对当前 item 触发
    - run(item): 返回 EnrichmentResult 或 None
    """

    name: str = ""
    enrichment_type: str = ""

    def __init__(self, sb: Client, config: PipelineConfig, api_key: str = "", table_suffix: str = ""):
        self.sb = sb
        self.config = config
        self.api_key = api_key
        self.table_suffix = table_suffix
        (
            self.item_enrichments_table,
            self.subjects_table,
            self.subject_mentions_table,
            self.subject_aliases_table,
        ) = enrich_table_names(table_suffix)

    def preload(self, items: list[dict], snapshot_date: str) -> None:  # noqa: B027
        return None

    def applies_to(self, item: dict) -> bool:
        return True

    def run(self, item: dict) -> EnrichmentResult | None:
        raise NotImplementedError
