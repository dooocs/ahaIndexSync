import unittest
import sys
import types
from datetime import date
from unittest.mock import patch

sys.modules.setdefault(
    "supabase",
    types.SimpleNamespace(Client=object, create_client=lambda *_args, **_kwargs: None),
)
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: None))

from stages.tweet_aggregate import run_tweet_aggregate


class _Result:
    def __init__(self, data=None):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.operation = None

    def select(self, *_args):
        self.operation = "select"
        return self

    def eq(self, *_args):
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def in_(self, column, values):
        self.client.deletes.append((self.table, column, list(values)))
        self.client.events.append(("delete", self.table, column, list(values)))
        return self

    def execute(self):
        if self.operation == "select":
            return _Result(self.client.rows)
        return _Result([])


class _FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.deletes = []
        self.events = []

    def table(self, name):
        return _Query(self, name)


class TestTweetAggregate(unittest.TestCase):
    def test_digest_writes_items_content_for_processing(self):
        rows = [
            {
                "id": "tweet-1",
                "title": "First tweet",
                "original_url": "https://x.com/a/status/1",
                "author": "alice",
                "raw_metrics": {"likes": 20, "retweets": 2, "replies": 1, "views": 100},
                "extra": {"tweet_id": "1", "display_name": "Alice"},
                "items_content": {"raw_body": "First full tweet body"},
            },
            {
                "id": "tweet-2",
                "title": "Second tweet",
                "original_url": "https://x.com/b/status/2",
                "author": "bob",
                "raw_metrics": {"likes": 10, "retweets": 1, "replies": 3, "views": 80},
                "extra": {"tweet_id": "2", "display_name": "Bob"},
            },
        ]
        sb = _FakeSupabase(rows)
        config = types.SimpleNamespace(
            scrapers=[
                types.SimpleNamespace(
                    name="X (Twitter)",
                    scraper_type="twitter_twscrape",
                    slug="x-twitter-",
                    config={"content_type": "tweet"},
                )
            ]
        )

        def _record_raw(*args):
            sb.events.append(("upsert_raw", args[0].id))

        def _record_content(*args):
            sb.events.append(("upsert_content", args[0]))

        with patch("stages.tweet_aggregate.upsert_raw_item", side_effect=_record_raw) as upsert_raw, patch(
            "stages.tweet_aggregate.upsert_content_initial", side_effect=_record_content
        ) as upsert_content:
            stats = run_tweet_aggregate(sb, config=config, snapshot_date=date(2026, 6, 5))

        self.assertEqual(stats["aggregated"], 2)
        upsert_raw.assert_called_once()
        digest = upsert_raw.call_args.args[0]
        self.assertEqual(digest.content_type, "tweet_digest")
        self.assertEqual(digest.scraper_slug, "x-twitter-")
        self.assertEqual(digest.scraper_config_snapshot, {"content_type": "tweet"})
        self.assertEqual(digest.raw_metrics["tweet_count"], 2)
        upsert_content.assert_called_once_with(digest.id, digest.body_text, "items_content")
        self.assertIn("@alice: First full tweet body", digest.body_text)
        self.assertIn("@bob: Second tweet", digest.body_text)
        self.assertIn(("raw_items", "id", ["tweet-1", "tweet-2"]), sb.deletes)
        self.assertIn(("items_content", "item_id", ["tweet-1", "tweet-2"]), sb.deletes)
        self.assertEqual(sb.events[0][0], "upsert_raw")
        self.assertEqual(sb.events[1][0], "upsert_content")
        self.assertEqual(sb.events[2][0], "delete")


if __name__ == "__main__":
    unittest.main()
