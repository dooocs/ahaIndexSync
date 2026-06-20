import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault(
    "supabase",
    types.SimpleNamespace(Client=object, create_client=lambda *_args, **_kwargs: None),
)
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: None))

from pipeline.config_loader import PipelineConfig, PromptConfig
from stages.subject_insights import run_subject_insights


class _Result:
    def __init__(self, data=None):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.operation = None
        self.payload = None
        self.filters = []
        self.limit_n = None
        self.upsert_kwargs = {}

    def select(self, *_args):
        self.operation = "select"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, list(values)))
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        return self

    def lte(self, column, value):
        self.filters.append(("lte", column, value))
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def upsert(self, payload, **kwargs):
        self.operation = "upsert"
        self.payload = payload
        self.upsert_kwargs = kwargs
        return self

    def execute(self):
        if self.operation == "select":
            rows = self.client.select_rows(self.table, self.filters)
            if self.limit_n is not None:
                rows = rows[: self.limit_n]
            return _Result(rows)
        if self.operation == "upsert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            rows = self.client.tables.setdefault(self.table, [])
            keys = [
                key.strip()
                for key in self.upsert_kwargs.get("on_conflict", "").split(",")
                if key.strip()
            ]
            out = []
            for payload in payloads:
                row = dict(payload)
                matched = None
                if keys:
                    for existing in rows:
                        if all(existing.get(key) == row.get(key) for key in keys):
                            existing.update(row)
                            matched = existing
                            break
                if matched is None:
                    row.setdefault("id", f"{self.table}-{len(rows) + 1}")
                    rows.append(row)
                    matched = row
                out.append(matched)
            return _Result(out)
        return _Result([])


class _FakeSupabase:
    def __init__(self):
        self.tables = {
            "subjects": [
                {
                    "id": "subject-openai",
                    "slug": "company:openai",
                    "type": "company",
                    "display_name": "OpenAI",
                    "aliases": ["OpenAI"],
                    "metadata": {},
                    "status": "active",
                    "directory_visible": True,
                },
                {
                    "id": "subject-anthropic",
                    "slug": "company:anthropic",
                    "type": "company",
                    "display_name": "Anthropic",
                    "aliases": ["Anthropic"],
                    "metadata": {},
                    "status": "active",
                    "directory_visible": True,
                },
            ],
            "subject_mentions": [
                {
                    "subject_id": "subject-openai",
                    "item_id": "item-1",
                    "snapshot_date": "2026-06-20",
                    "role": "mentioned",
                    "source_name": "AI Blog",
                    "score": 0.9,
                    "context": "OpenAI and Anthropic are compared.",
                    "detected_by": "enrich.catalog_subject_match",
                    "confidence": 0.9,
                    "evidence": {"matched_term": "OpenAI"},
                },
                {
                    "subject_id": "subject-anthropic",
                    "item_id": "item-1",
                    "snapshot_date": "2026-06-20",
                    "role": "mentioned",
                    "source_name": "AI Blog",
                    "score": 0.88,
                    "context": "OpenAI and Anthropic are compared.",
                    "detected_by": "enrich.catalog_subject_match",
                    "confidence": 0.88,
                    "evidence": {"matched_term": "Anthropic"},
                },
            ],
            "display_items": [
                {
                    "processed_item_id": "item-1",
                    "snapshot_date": "2026-06-20",
                    "rank": 1,
                    "processed_title": "OpenAI 与 Anthropic 推理模型对比",
                    "summary": "两家公司最新推理模型在开发者场景中形成直接对比。",
                    "expert_insight": "这类对比会影响团队在成本、延迟和安全边界之间的取舍。",
                    "source_name": "AI Blog",
                    "content_type": "article",
                    "original_url": "https://example.com/compare",
                    "tags": ["OpenAI", "Anthropic"],
                    "aha_index": 0.92,
                    "extra": {},
                }
            ],
            "processed_items": [],
            "subject_insights": [],
        }

    def table(self, name):
        return _Query(self, name)

    def select_rows(self, table, filters):
        rows = list(self.tables.get(table, []))
        for kind, column, value in filters:
            if kind == "eq":
                rows = [row for row in rows if row.get(column) == value]
            elif kind == "in":
                rows = [row for row in rows if row.get(column) in value]
            elif kind == "gte":
                rows = [row for row in rows if str(row.get(column) or "") >= value]
            elif kind == "lte":
                rows = [row for row in rows if str(row.get(column) or "") <= value]
        return rows


class TestSubjectInsights(unittest.TestCase):
    def test_subject_insights_are_generated_and_upserted_idempotently(self):
        sb = _FakeSupabase()
        cfg = PipelineConfig(params={
            "subject_insights_window_days": 7,
            "subject_insights_max_subjects": 10,
            "subject_insights_max_items_per_subject": 5,
        })

        first = run_subject_insights(sb, cfg, "2026-06-20")
        first_count = len(sb.tables["subject_insights"])
        second = run_subject_insights(sb, cfg, "2026-06-20")
        second_count = len(sb.tables["subject_insights"])

        self.assertGreater(first["written"], 0)
        self.assertGreater(second["written"], 0)
        self.assertEqual(first_count, second_count)

        modules = {row["module_type"] for row in sb.tables["subject_insights"]}
        self.assertIn("timeline", modules)
        self.assertIn("highlight", modules)
        self.assertIn("comparison", modules)

        comparison = next(row for row in sb.tables["subject_insights"] if row["module_type"] == "comparison")
        self.assertIn("subject-anthropic", comparison["comparison_subject_ids"] + comparison["related_subject_ids"])
        self.assertEqual(comparison["status"], "published")
        self.assertEqual(comparison["evidence_item_ids"], ["item-1"])

    def test_subject_insights_can_use_llm_synthesis_with_evidence_guardrails(self):
        sb = _FakeSupabase()
        cfg = PipelineConfig(
            params={
                "subject_insights_use_llm": True,
                "subject_insights_window_days": 7,
                "subject_insights_max_subjects": 10,
                "subject_insights_max_items_per_subject": 5,
            },
            prompts={
                "subject_insights_generate": PromptConfig(
                    name="subject_insights_generate",
                    stage="subject_insights",
                    template="{subject_json}\n{evidence_json}\n{related_subjects_json}",
                    model="kimi-k2.6",
                    model_base_url="https://api.moonshot.cn/v1",
                    temperature=0.6,
                    max_retries=1,
                    request_interval=0,
                    version=1,
                )
            },
        )

        llm_response = {
            "highlight": {
                "title": "OpenAI 与 Anthropic 的模型选择分叉",
                "summary": "两家公司在推理模型场景中被直接比较，开发者需要重新权衡成本、延迟和安全边界。",
                "analysis": "这不是单条新闻摘要，而是近期证据合并后的 subject 级判断。",
                "evidence_indexes": [1],
                "importance_score": 0.91,
            },
            "comparisons": [
                {
                    "comparison_subject_ids": ["subject-anthropic"],
                    "title": "OpenAI 与 Anthropic 的开发者定位对比",
                    "summary": "共现内容显示两家公司正在同一类推理模型选型场景里竞争。",
                    "analysis": "该判断来自同一条内容的双 subject 关联，而不是模型自由发挥。",
                    "evidence_indexes": [1],
                    "importance_score": 0.82,
                }
            ],
        }

        with patch.dict("os.environ", {"KIMI_API_KEY": "test-key"}), patch(
            "stages.subject_insights.call_llm",
            return_value=llm_response,
        ) as mock_call:
            stats = run_subject_insights(sb, cfg, "2026-06-20")

        self.assertEqual(stats["llm_enabled"], True)
        self.assertEqual(stats["llm_subjects"], 2)
        self.assertGreaterEqual(mock_call.call_count, 2)

        openai_highlight = next(
            row
            for row in sb.tables["subject_insights"]
            if row["subject_id"] == "subject-openai" and row["module_type"] == "highlight"
        )
        self.assertEqual(openai_highlight["generated_by"], "pipeline_llm")
        self.assertEqual(openai_highlight["title"], "OpenAI 与 Anthropic 的模型选择分叉")
        self.assertEqual(openai_highlight["evidence_item_ids"], ["item-1"])
        self.assertEqual(openai_highlight["dimensions_json"]["generation_mode"], "llm")

        openai_comparison = next(
            row
            for row in sb.tables["subject_insights"]
            if row["subject_id"] == "subject-openai" and row["module_type"] == "comparison"
        )
        self.assertEqual(openai_comparison["generated_by"], "pipeline_llm")
        self.assertIn("subject-anthropic", openai_comparison["comparison_subject_ids"])
        self.assertEqual(openai_comparison["evidence_item_ids"], ["item-1"])


if __name__ == "__main__":
    unittest.main()
