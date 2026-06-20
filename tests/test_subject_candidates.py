import sys
import types
import unittest

sys.modules.setdefault(
    "supabase",
    types.SimpleNamespace(Client=object, create_client=lambda *_args, **_kwargs: None),
)
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: None))

from enrichers.base import EnrichmentResult, SubjectCandidate
from stages.enrich import _ItemOutput, _register_candidate_subjects
from stages.subject import SubjectRegistry


class _Result:
    def __init__(self, data=None):
        self.data = data


class _RpcQuery:
    def __init__(self, client, name, payload):
        self.client = client
        self.name = name
        self.payload = payload

    def execute(self):
        self.client.rpc_calls.append((self.name, self.payload))
        if self.name == "record_subject_mention":
            self.client.apply_record_subject_mention(self.payload)
        return _Result([])


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.operation = None
        self.payload = None
        self.filters = []
        self.limit_n = None

    def select(self, *_args):
        self.operation = "select"
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
        self.client.operations.append(("upsert", self.table, payload, kwargs))
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
        self.client.operations.append((self.operation, self.table, self.payload, list(self.filters)))
        if self.operation == "select":
            rows = self.client.select_rows(self.table, self.filters)
            if self.limit_n is not None:
                rows = rows[: self.limit_n]
            return _Result(rows)
        if self.operation == "insert":
            row = dict(self.payload)
            row.setdefault("id", f"{self.table}-1")
            self.client.tables.setdefault(self.table, []).append(row)
            return _Result([row])
        if self.operation == "update":
            rows = self.client.select_rows(self.table, self.filters)
            for row in rows:
                row.update(self.payload)
            return _Result(rows)
        if self.operation == "upsert":
            row = dict(self.payload)
            conflict = self.upsert_kwargs.get("on_conflict", "")
            keys = [k.strip() for k in conflict.split(",") if k.strip()]
            rows = self.client.tables.setdefault(self.table, [])
            matched = None
            if keys:
                for existing in rows:
                    if all(existing.get(k) == row.get(k) for k in keys):
                        existing.update(row)
                        matched = existing
                        break
            if matched is None:
                row.setdefault("id", f"{self.table}-{len(rows) + 1}")
                rows.append(row)
                matched = row
            return _Result([matched])
        return _Result([])


class _FakeSupabase:
    def __init__(self):
        self.tables = {
            "subject_aliases": [],
            "subjects": [],
            "subject_mentions": [],
            "subject_candidates": [],
            "subject_aliases_test": [],
            "subjects_test": [],
            "subject_mentions_test": [],
        }
        self.operations = []
        self.rpc_calls = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, payload):
        return _RpcQuery(self, name, payload)

    def select_rows(self, table, filters):
        rows = list(self.tables.get(table, []))
        for kind, column, value in filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(column) == value]
            elif kind == "in":
                rows = [r for r in rows if r.get(column) in value]
        return rows

    def apply_record_subject_mention(self, payload):
        subjects = self.tables.setdefault("subjects", [])
        mentions = self.tables.setdefault("subject_mentions", [])

        subject = next((row for row in subjects if row.get("slug") == payload["p_slug"]), None)
        if subject is None:
            subject = {
                "id": f"subject-{len(subjects) + 1}",
                "slug": payload["p_slug"],
                "type": payload["p_type"],
                "display_name": payload["p_display_name"],
                "metadata": payload.get("p_metadata") or {},
                "mention_count": 0,
                "first_seen_at": payload["p_snapshot_date"],
                "last_seen_at": payload["p_snapshot_date"],
            }
            subjects.append(subject)
        else:
            subject["type"] = payload["p_type"] or subject.get("type")
            subject["display_name"] = payload["p_display_name"] or subject.get("display_name")
            if payload.get("p_metadata"):
                subject["metadata"] = payload["p_metadata"]
            if not subject.get("first_seen_at") or payload["p_snapshot_date"] < subject["first_seen_at"]:
                subject["first_seen_at"] = payload["p_snapshot_date"]
            if not subject.get("last_seen_at") or payload["p_snapshot_date"] > subject["last_seen_at"]:
                subject["last_seen_at"] = payload["p_snapshot_date"]

        existing = next(
            (
                row
                for row in mentions
                if row.get("subject_id") == subject["id"]
                and row.get("item_id") == payload["p_item_id"]
                and row.get("snapshot_date") == payload["p_snapshot_date"]
            ),
            None,
        )
        if existing is not None:
            existing.update(
                {
                    "role": payload["p_role"],
                    "source_name": payload["p_source_name"],
                    "score": payload["p_score"],
                    "context": payload["p_context"],
                    "detected_by": payload["p_detected_by"],
                    "confidence": payload["p_confidence"],
                    "evidence": payload["p_evidence"],
                }
            )
            return

        mentions.append(
            {
                "id": f"subject_mentions-{len(mentions) + 1}",
                "subject_id": subject["id"],
                "item_id": payload["p_item_id"],
                "snapshot_date": payload["p_snapshot_date"],
                "role": payload["p_role"],
                "source_name": payload["p_source_name"],
                "score": payload["p_score"],
                "context": payload["p_context"],
                "detected_by": payload["p_detected_by"],
                "confidence": payload["p_confidence"],
                "evidence": payload["p_evidence"],
            }
        )
        subject["mention_count"] = (subject.get("mention_count") or 0) + 1
        if not subject.get("last_seen_at") or payload["p_snapshot_date"] > subject["last_seen_at"]:
            subject["last_seen_at"] = payload["p_snapshot_date"]


class TestSubjectCandidates(unittest.TestCase):
    def test_unknown_enrichment_subject_is_queued_for_review(self):
        sb = _FakeSupabase()
        registry = SubjectRegistry(sb)
        outputs = [
            _ItemOutput(
                item_id="item-1",
                source_name="hn",
                score=0.82,
                results=[
                    EnrichmentResult(
                        enrichment_type="ecosystem",
                        enricher_name="github_ecosystem",
                        data={},
                        subject_candidates=[
                            SubjectCandidate(
                                slug="github:owner/repo",
                                type="project",
                                display_name="owner/repo",
                                description="A candidate project",
                                metadata={"repo_full_name": "owner/repo"},
                                role="mentioned",
                                context="mentioned as competitor",
                            )
                        ],
                    )
                ],
            )
        ]

        mentions, candidates = _register_candidate_subjects(registry, outputs, "2026-06-20")

        self.assertEqual(mentions, 0)
        self.assertEqual(candidates, 1)
        self.assertEqual(sb.tables["subjects"], [])
        self.assertEqual(len(sb.tables["subject_candidates"]), 1)

        row = sb.tables["subject_candidates"][0]
        self.assertEqual(row["candidate_key"], "project:github:owner/repo")
        self.assertEqual(row["proposed_slug"], "github:owner/repo")
        self.assertEqual(row["proposed_type"], "project")
        self.assertEqual(row["source_item_ids"], ["item-1"])
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["evidence"]["items"][0]["context"], "mentioned as competitor")

        subject_inserts = [
            op for op in sb.operations
            if op[0] == "insert" and op[1] == "subjects"
        ]
        self.assertEqual(subject_inserts, [])

    def test_record_mention_is_idempotent(self):
        sb = _FakeSupabase()
        sb.tables["subjects"].append(
            {
                "id": "subject-1",
                "slug": "github:owner/repo",
                "type": "project",
                "display_name": "owner/repo",
                "metadata": {"repo_full_name": "owner/repo"},
                "mention_count": 5,
                "last_seen_at": "2026-06-18",
            }
        )
        registry = SubjectRegistry(sb)

        first = registry.record_mention(
            subject_id="subject-1",
            item_id="item-1",
            snapshot_date="2026-06-20",
            role="primary",
            source_name="GitHub Trending",
            score=0.91,
            context="primary repo mention",
            detected_by="enrich.primary_github_repo",
            confidence=1.0,
            evidence={"source_url": "https://github.com/owner/repo"},
        )
        second = registry.record_mention(
            subject_id="subject-1",
            item_id="item-1",
            snapshot_date="2026-06-20",
            role="primary",
            source_name="GitHub Trending",
            score=0.91,
            context="primary repo mention",
            detected_by="enrich.primary_github_repo",
            confidence=1.0,
            evidence={"source_url": "https://github.com/owner/repo"},
        )

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(sb.tables["subjects"][0]["mention_count"], 6)
        self.assertEqual(sb.tables["subjects"][0]["last_seen_at"], "2026-06-20")
        self.assertEqual(len(sb.tables["subject_mentions"]), 1)
        mention = sb.tables["subject_mentions"][0]
        self.assertEqual(mention["detected_by"], "enrich.primary_github_repo")
        self.assertEqual(mention["confidence"], 1.0)
        self.assertEqual(mention["evidence"], {"source_url": "https://github.com/owner/repo"})

    def test_record_mention_skips_rpc_for_test_tables(self):
        sb = _FakeSupabase()
        sb.tables["subjects_test"].append(
            {
                "id": "subject-test-1",
                "slug": "github:owner/repo",
                "type": "project",
                "display_name": "owner/repo",
                "metadata": {"repo_full_name": "owner/repo"},
                "mention_count": 5,
                "last_seen_at": "2026-06-18",
            }
        )
        registry = SubjectRegistry(sb, "_test")

        first = registry.record_mention(
            subject_id="subject-test-1",
            item_id="item-1",
            snapshot_date="2026-06-20",
            role="primary",
            source_name="GitHub Trending",
            score=0.91,
            context="primary repo mention",
            detected_by="enrich.primary_github_repo",
            confidence=1.0,
            evidence={"source_url": "https://github.com/owner/repo"},
        )
        second = registry.record_mention(
            subject_id="subject-test-1",
            item_id="item-1",
            snapshot_date="2026-06-20",
            role="primary",
            source_name="GitHub Trending",
            score=0.91,
            context="primary repo mention",
            detected_by="enrich.primary_github_repo",
            confidence=1.0,
            evidence={"source_url": "https://github.com/owner/repo"},
        )

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(sb.rpc_calls, [])
        self.assertEqual(sb.tables["subjects_test"][0]["mention_count"], 6)
        self.assertEqual(sb.tables["subjects_test"][0]["last_seen_at"], "2026-06-20")
        self.assertEqual(len(sb.tables["subject_mentions_test"]), 1)
        mention = sb.tables["subject_mentions_test"][0]
        self.assertEqual(mention["detected_by"], "enrich.primary_github_repo")
        self.assertEqual(mention["confidence"], 1.0)
        self.assertEqual(mention["evidence"], {"source_url": "https://github.com/owner/repo"})


if __name__ == "__main__":
    unittest.main()
