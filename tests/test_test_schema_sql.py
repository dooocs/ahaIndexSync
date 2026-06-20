import unittest
from pathlib import Path


class TestTestSchemaSql(unittest.TestCase):
    def test_subject_test_schema_backfills_existing_tables(self):
        sql = Path("sql/003_enrich_and_subject_tables_test.sql").read_text()

        self.assertIn("ALTER TABLE IF EXISTS subjects_test", sql)
        for column in (
            "status",
            "directory_visible",
            "section_slug",
            "curation_priority",
            "created_by",
            "definition",
            "homepage_url",
        ):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", sql)

        self.assertIn("ALTER TABLE IF EXISTS subject_mentions_test", sql)
        for column in ("detected_by", "confidence", "evidence"):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", sql)


if __name__ == "__main__":
    unittest.main()
