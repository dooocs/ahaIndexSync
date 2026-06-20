-- ============================================================
-- Subject Insights
--
-- Published analytical modules for Subject detail pages.
-- The first detail-page shape is fixed to timeline / highlight / comparison.
-- ============================================================

CREATE TABLE IF NOT EXISTS subject_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    snapshot_date DATE,
    module_type TEXT NOT NULL,
    insight_key TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    analysis TEXT,
    event_date DATE,
    comparison_subject_ids UUID[] NOT NULL DEFAULT '{}',
    dimensions_json JSONB NOT NULL DEFAULT '{}',
    importance_score DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    evidence_item_ids TEXT[] NOT NULL DEFAULT '{}',
    evidence_refs_json JSONB NOT NULL DEFAULT '{}',
    related_subject_ids UUID[] NOT NULL DEFAULT '{}',
    generated_by TEXT NOT NULL DEFAULT 'pipeline',
    generator_version TEXT NOT NULL DEFAULT 'v1',
    status TEXT NOT NULL DEFAULT 'draft',
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT subject_insights_module_type_check
        CHECK (module_type IN ('timeline', 'highlight', 'comparison')),
    CONSTRAINT subject_insights_status_check
        CHECK (status IN ('draft', 'published', 'hidden')),
    CONSTRAINT subject_insights_importance_check
        CHECK (importance_score IS NULL OR (importance_score >= 0 AND importance_score <= 1)),
    CONSTRAINT subject_insights_confidence_check
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_insights_key
    ON subject_insights (subject_id, module_type, insight_key, generator_version);

CREATE INDEX IF NOT EXISTS idx_subject_insights_subject_module
    ON subject_insights (subject_id, module_type, importance_score DESC);

CREATE INDEX IF NOT EXISTS idx_subject_insights_published
    ON subject_insights (subject_id, module_type, event_date DESC, importance_score DESC)
    WHERE status = 'published';

COMMENT ON TABLE subject_insights IS 'Published analytical modules for Subject detail pages: timeline / highlight / comparison';
COMMENT ON COLUMN subject_insights.module_type IS 'timeline / highlight / comparison';
COMMENT ON COLUMN subject_insights.insight_key IS 'Stable business key for idempotent generation within subject/module/generator_version';
COMMENT ON COLUMN subject_insights.dimensions_json IS 'Structured comparison dimensions or highlight attributes';
COMMENT ON COLUMN subject_insights.evidence_refs_json IS 'Evidence references back to mentions/raw items/json paths';

DO $$
BEGIN
    EXECUTE format(
        'DROP TRIGGER IF EXISTS trigger_update_subject_insights_updated_at ON subject_insights; '
        'CREATE TRIGGER trigger_update_subject_insights_updated_at BEFORE UPDATE ON subject_insights '
        'FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();'
    );
END;
$$;

ALTER TABLE subject_insights ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON subject_insights FROM anon;
REVOKE ALL ON subject_insights FROM authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_insights TO service_role;
GRANT SELECT, INSERT, UPDATE ON subject_insights TO authenticated;

DROP POLICY IF EXISTS "subject insights admin select" ON subject_insights;
CREATE POLICY "subject insights admin select"
    ON subject_insights
    FOR SELECT
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

DROP POLICY IF EXISTS "subject insights admin insert" ON subject_insights;
CREATE POLICY "subject insights admin insert"
    ON subject_insights
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

DROP POLICY IF EXISTS "subject insights admin update" ON subject_insights;
CREATE POLICY "subject insights admin update"
    ON subject_insights
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid)
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);
