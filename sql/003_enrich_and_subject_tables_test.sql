-- ============================================================
-- AhaIndexSync - 测试环境 4 张表（_test 后缀版本）
-- 与 003_enrich_and_subject_tables.sql 结构完全一致，仅表名带 _test 后缀。
--
-- 测试时配合 TABLE_SUFFIX=_test 或 python main.py --suffix _test 使用，
-- 可与生产数据完全隔离。
-- ============================================================

-- 1. item_enrichments_test
CREATE TABLE IF NOT EXISTS item_enrichments_test (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    enrichment_type TEXT NOT NULL,
    enricher_name TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_item_enrichments_test_key
    ON item_enrichments_test (item_id, snapshot_date, enrichment_type);
CREATE INDEX IF NOT EXISTS idx_item_enrichments_test_date
    ON item_enrichments_test (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_item_enrichments_test_type
    ON item_enrichments_test (enrichment_type, snapshot_date);


-- 2. subjects_test
CREATE TABLE IF NOT EXISTS subjects_test (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    description TEXT,
    metadata JSONB NOT NULL DEFAULT '{}',
    first_seen_at DATE NOT NULL DEFAULT CURRENT_DATE,
    last_seen_at DATE NOT NULL DEFAULT CURRENT_DATE,
    mention_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subjects_test_type ON subjects_test (type);
CREATE INDEX IF NOT EXISTS idx_subjects_test_last_seen ON subjects_test (last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_subjects_test_mention_count ON subjects_test (mention_count DESC);


-- 3. subject_mentions_test
CREATE TABLE IF NOT EXISTS subject_mentions_test (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL REFERENCES subjects_test(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    role TEXT NOT NULL DEFAULT 'mentioned',
    source_name TEXT,
    score FLOAT,
    context TEXT,
    detected_by TEXT,
    confidence DOUBLE PRECISION,
    evidence JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_mentions_test_key
    ON subject_mentions_test (subject_id, item_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_subject_mentions_test_subject ON subject_mentions_test (subject_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_subject_mentions_test_item ON subject_mentions_test (item_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_subject_mentions_test_date ON subject_mentions_test (snapshot_date);


-- 4. subject_aliases_test
CREATE TABLE IF NOT EXISTS subject_aliases_test (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_slug TEXT UNIQUE NOT NULL,
    to_subject_id UUID NOT NULL REFERENCES subjects_test(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subject_aliases_test_to ON subject_aliases_test (to_subject_id);


-- auto update updated_at trigger（subjects_test 表）
DO $$
BEGIN
    EXECUTE format(
        'DROP TRIGGER IF EXISTS trigger_update_subjects_test_updated_at ON subjects_test; '
        'CREATE TRIGGER trigger_update_subjects_test_updated_at BEFORE UPDATE ON subjects_test '
        'FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();'
    );
END;
$$;
