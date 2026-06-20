import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault(
    "supabase",
    types.SimpleNamespace(Client=object, create_client=lambda *_args, **_kwargs: None),
)
sys.modules.setdefault("openai", types.SimpleNamespace(OpenAI=object))

from stages.aggregate_projects import run_aggregate_projects


class _Result:
    def __init__(self, data=None):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.operation = None
        self.payload = None

    def select(self, *_args):
        self.operation = "select"
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def upsert(self, payload, **kwargs):
        self.operation = "upsert"
        self.payload = payload
        self.client.writes.append((self.table, "upsert", payload, kwargs))
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def execute(self):
        if self.operation == "select" and self.table == "tracks":
            return _Result(self.client.tables["tracks"])
        if self.operation == "upsert":
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            self.client.tables.setdefault(self.table, []).extend(rows)
            return _Result(rows)
        if self.operation == "update":
            self.client.writes.append((self.table, "update", self.payload, None))
            return _Result([])
        return _Result([])


class _FakeSupabase:
    def __init__(self):
        self.tables = {
            "tracks": [
                {
                    "id": "track-1",
                    "slug": "foundation-models",
                    "display_name": "Foundation Models",
                    "group_name": "model",
                    "display_order": 1,
                    "status": "active",
                },
                {
                    "id": "track-2",
                    "slug": "applications",
                    "display_name": "Applications",
                    "group_name": "application",
                    "display_order": 2,
                    "status": "active",
                },
            ],
            "project_heatmap_data": [],
        }
        self.writes = []

    def table(self, name):
        return _Query(self, name)


class TestAggregateProjects(unittest.TestCase):
    def test_related_data_shape_and_track_cache(self):
        sb = _FakeSupabase()

        subjects = [
            {
                "id": "subject-1",
                "slug": "github:alice/one",
                "display_name": "alice/one",
                "description": "One",
                "metadata": {"repo_full_name": "alice/one"},
                "first_seen_at": "2026-06-18",
                "last_seen_at": "2026-06-19",
                "mention_count": 2,
            },
            {
                "id": "subject-2",
                "slug": "github:bob/two",
                "display_name": "bob/two",
                "description": "Two",
                "metadata": {"repo_full_name": "bob/two"},
                "first_seen_at": "2026-06-18",
                "last_seen_at": "2026-06-19",
                "mention_count": 1,
            },
            {
                "id": "subject-3",
                "slug": "github:carol/three",
                "display_name": "carol/three",
                "description": "Three",
                "metadata": {"repo_full_name": "carol/three"},
                "first_seen_at": "2026-06-18",
                "last_seen_at": "2026-06-19",
                "mention_count": 1,
            },
        ]
        mentions = [
            {
                "subject_id": "subject-1",
                "item_id": "item-1",
                "snapshot_date": "2026-06-20",
                "role": "primary",
                "source_name": "GitHub Trending",
                "score": 0.8,
            },
            {
                "subject_id": "subject-2",
                "item_id": "item-1",
                "snapshot_date": "2026-06-20",
                "role": "mentioned",
                "source_name": "HackerNews",
                "score": 0.7,
            },
            {
                "subject_id": "subject-3",
                "item_id": "item-2",
                "snapshot_date": "2026-06-20",
                "role": "mentioned",
                "source_name": "HackerNews",
                "score": 0.6,
            },
        ]

        with patch("stages.aggregate_projects._load_all_subjects", return_value=subjects), patch(
            "stages.aggregate_projects._load_all_mentions", return_value=mentions
        ), patch("stages.aggregate_projects._load_item_tags", return_value={"item-1": ["agents", "open-source"]}), patch(
            "stages.aggregate_projects._load_item_aha_scores", return_value={}
        ), patch(
            "stages.aggregate_projects._load_enricher_competitors",
            return_value={"alice/one": [{"name": "bob/two", "comparison": "similar repo"}]},
        ), patch(
            "stages.aggregate_projects._load_existing_track_assignments",
            return_value={},
        ), patch(
            "stages.aggregate_projects._load_existing_heatmap",
            return_value={},
        ), patch(
            "stages.aggregate_projects._match_subjects_via_llm",
            return_value={
                "subject-1": ("track-1", "Foundation Models", "model"),
                "subject-2": ("track-1", "Foundation Models", "model"),
                "subject-3": ("track-2", "Applications", "application"),
            },
        ):
            stats = run_aggregate_projects(sb, "2026-06-20")

        self.assertEqual(stats["subjects_total"], 3)
        self.assertEqual(stats["rows_written_today"], 3)
        self.assertEqual(stats["tracks_matched"], 3)
        self.assertEqual(len(sb.tables["project_heatmap_data"]), 3)

        row = next(r for r in sb.tables["project_heatmap_data"] if r["subject_slug"] == "github:alice/one")
        self.assertEqual(row["mention_count"], 2)
        self.assertEqual(row["score_100"], 80.0)
        self.assertIn("related", row["related_data"])
        self.assertIn("competitors", row["related_data"])
        self.assertTrue(any(rel["slug"] == "github:bob/two" and rel["kind"] == "竞品" for rel in row["related_data"]["related"]))
        self.assertTrue(
            any(comp["slug"] == "github:bob/two" and comp["source"] in {"enricher", "co_appearance"} for comp in row["related_data"]["competitors"])
        )


if __name__ == "__main__":
    unittest.main()
