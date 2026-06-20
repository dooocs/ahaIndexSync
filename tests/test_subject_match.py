import sys
import types
import unittest

sys.modules.setdefault(
    "supabase",
    types.SimpleNamespace(Client=object, create_client=lambda *_args, **_kwargs: None),
)
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: None))

from pipeline.config_loader import PipelineConfig
from stages.subject import SubjectRegistry
from stages.subject_match import run_catalog_subject_match


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
        self.select_columns = "*"

    def select(self, columns="*"):
        self.operation = "select"
        self.select_columns = columns
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def upsert(self, payload, **kwargs):
        self.operation = "upsert"
        self.payload = payload
        self.upsert_kwargs = kwargs
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, list(values)))
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def execute(self):
        if self.operation == "select":
            self.client.select_calls.append((self.table, self.select_columns, list(self.filters)))
            if (
                self.client.raise_legacy_subject_schema
                and self.table == "subjects_test"
                and "definition" in str(self.select_columns)
            ):
                raise Exception(
                    "{'message': 'column subjects_test.definition does not exist', 'code': '42703'}"
                )
            rows = self.client.select_rows(self.table, self.filters)
            if self.limit_n is not None:
                rows = rows[: self.limit_n]
            return _Result(rows)
        if self.operation == "insert":
            row = dict(self.payload)
            row.setdefault("id", f"{self.table}-{len(self.client.tables.setdefault(self.table, [])) + 1}")
            self.client.tables.setdefault(self.table, []).append(row)
            return _Result([row])
        if self.operation == "update":
            rows = self.client.select_rows(self.table, self.filters)
            for row in rows:
                row.update(self.payload)
            return _Result(rows)
        if self.operation == "upsert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            rows = self.client.tables.setdefault(self.table, [])
            out = []
            keys = [
                key.strip()
                for key in self.upsert_kwargs.get("on_conflict", "").split(",")
                if key.strip()
            ]
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
            "subject_aliases": [],
            "subjects": [],
            "subject_mentions": [],
            "subject_aliases_test": [],
            "subjects_test": [],
            "subject_mentions_test": [],
        }
        self.select_calls = []
        self.raise_legacy_subject_schema = False

    def table(self, name):
        return _Query(self, name)

    def select_rows(self, table, filters):
        rows = list(self.tables.get(table, []))
        for kind, column, value in filters:
            if kind == "eq":
                rows = [row for row in rows if row.get(column) == value]
            elif kind == "in":
                rows = [row for row in rows if row.get(column) in value]
        return rows


class TestSubjectMatch(unittest.TestCase):
    def test_visible_subject_match_writes_evidence_without_forcing_generic_subject(self):
        sb = _FakeSupabase()
        sb.tables["subjects"] = [
            {
                "id": "subject-openai",
                "slug": "company:openai",
                "type": "company",
                "display_name": "OpenAI",
                "aliases": ["OpenAI"],
                "metadata": {},
                "status": "active",
                "directory_visible": True,
                "mention_count": 0,
                "last_seen_at": "2026-06-19",
            },
            {
                "id": "subject-ai",
                "slug": "concept:ai",
                "type": "concept",
                "display_name": "AI",
                "aliases": ["AI"],
                "metadata": {},
                "status": "active",
                "directory_visible": True,
                "mention_count": 0,
                "last_seen_at": "2026-06-19",
            },
        ]
        items = [
            {
                "item_id": "item-openai",
                "processed_title": "OpenAI 发布新模型",
                "raw_title": "OpenAI release",
                "summary": "OpenAI 推出新的推理模型。",
                "expert_insight": "这会影响应用开发者的模型选择。",
                "tags": ["OpenAI", "reasoning"],
                "keywords": ["OpenAI"],
                "source_name": "AI Blog",
                "original_url": "https://example.com/openai",
                "aha_index": 0.91,
            },
            {
                "item_id": "item-generic-ai",
                "processed_title": "AI 工具集合更新",
                "summary": "一些 AI 工具有小版本更新。",
                "tags": ["AI"],
                "keywords": ["AI"],
                "source_name": "AI Blog",
                "original_url": "https://example.com/ai-tools",
                "aha_index": 0.5,
            },
        ]

        registry = SubjectRegistry(sb)
        stats = run_catalog_subject_match(
            sb,
            PipelineConfig(params={"subject_match_min_confidence": 0.65}),
            items,
            registry,
            "2026-06-20",
        )

        self.assertEqual(stats["mentions"], 1)
        self.assertEqual(len(sb.tables["subject_mentions"]), 1)
        mention = sb.tables["subject_mentions"][0]
        self.assertEqual(mention["subject_id"], "subject-openai")
        self.assertEqual(mention["item_id"], "item-openai")
        self.assertEqual(mention["detected_by"], "enrich.catalog_subject_match")
        self.assertEqual(mention["evidence"]["matched_term"], "OpenAI")
        self.assertGreaterEqual(mention["confidence"], 0.65)

        run_catalog_subject_match(
            sb,
            PipelineConfig(params={"subject_match_min_confidence": 0.65}),
            items,
            registry,
            "2026-06-20",
        )
        self.assertEqual(len(sb.tables["subject_mentions"]), 1)
        self.assertEqual(sb.tables["subjects"][0]["mention_count"], 1)

    def test_test_subject_match_falls_back_for_legacy_catalog_schema(self):
        sb = _FakeSupabase()
        sb.raise_legacy_subject_schema = True
        sb.tables["subjects_test"] = [
            {
                "id": "subject-openai",
                "slug": "company:openai",
                "type": "company",
                "display_name": "OpenAI",
                "aliases": ["OpenAI"],
                "description": "AI lab",
                "metadata": {},
                "mention_count": 0,
                "last_seen_at": "2026-06-19",
            }
        ]
        items = [
            {
                "item_id": "item-openai",
                "processed_title": "OpenAI 发布新模型",
                "summary": "OpenAI 推出新的推理模型。",
                "tags": ["OpenAI"],
                "keywords": ["OpenAI"],
                "source_name": "AI Blog",
                "original_url": "https://example.com/openai",
                "aha_index": 0.91,
            }
        ]

        registry = SubjectRegistry(sb, "_test")
        stats = run_catalog_subject_match(
            sb,
            PipelineConfig(params={"subject_match_min_confidence": 0.65}),
            items,
            registry,
            "2026-06-20",
            "_test",
        )

        self.assertEqual(stats["mentions"], 1)
        self.assertEqual(len(sb.tables["subject_mentions_test"]), 1)
        self.assertIn(
            ("subjects_test", "id, slug, type, display_name, aliases, description, metadata", []),
            sb.select_calls,
        )


if __name__ == "__main__":
    unittest.main()
