-- ============================================================
-- Subject Candidates
--
-- AI/rule/import proposed subjects waiting for Admin review.
-- Approved candidates are promoted or merged into subjects.
-- Frontend directory pages should read approved subjects/read models,
-- never this candidate table directly.
-- ============================================================

CREATE TABLE IF NOT EXISTS subject_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Stable candidate identity proposed by extractor, e.g. company:nvidia.
    candidate_key TEXT NOT NULL,
    proposed_slug TEXT NOT NULL,
    proposed_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    definition TEXT,
    homepage_url TEXT,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',

    -- Evidence gathered from raw items or external inputs.
    source_item_ids TEXT[] NOT NULL DEFAULT '{}',
    evidence JSONB NOT NULL DEFAULT '{}',
    reason TEXT,
    confidence DOUBLE PRECISION,
    proposed_by TEXT NOT NULL DEFAULT 'ai',
    extractor_version TEXT,

    -- Admin review state.
    status TEXT NOT NULL DEFAULT 'pending',
    matched_subject_id UUID REFERENCES subjects(id) ON DELETE SET NULL,
    approved_subject_id UUID REFERENCES subjects(id) ON DELETE SET NULL,
    reviewed_by UUID,
    reviewed_at TIMESTAMPTZ,
    review_note TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT subject_candidates_confidence_check
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT subject_candidates_proposed_by_check
        CHECK (proposed_by IN ('ai', 'rule', 'import', 'admin')),
    CONSTRAINT subject_candidates_status_check
        CHECK (status IN ('pending', 'needs_more_evidence', 'approved', 'merged', 'rejected'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_candidates_pending_key
    ON subject_candidates (candidate_key)
    WHERE status IN ('pending', 'needs_more_evidence');

CREATE INDEX IF NOT EXISTS idx_subject_candidates_status
    ON subject_candidates (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_subject_candidates_type
    ON subject_candidates (proposed_type, status);
CREATE INDEX IF NOT EXISTS idx_subject_candidates_slug
    ON subject_candidates (proposed_slug);
CREATE INDEX IF NOT EXISTS idx_subject_candidates_matched_subject
    ON subject_candidates (matched_subject_id);
CREATE INDEX IF NOT EXISTS idx_subject_candidates_approved_subject
    ON subject_candidates (approved_subject_id);

COMMENT ON TABLE subject_candidates IS 'AI/rule/import proposed subjects waiting for Admin review before promotion into subjects';
COMMENT ON COLUMN subject_candidates.candidate_key IS 'Stable candidate identity before review, e.g. company:nvidia / person:lei-jun / concept:agent-memory';
COMMENT ON COLUMN subject_candidates.source_item_ids IS 'Raw item ids that produced or support this candidate; not constrained because candidates can come from multiple raw sources';
COMMENT ON COLUMN subject_candidates.evidence IS 'Structured evidence snippets, json paths, source fields, and extractor output for Admin review';
COMMENT ON COLUMN subject_candidates.status IS 'pending / needs_more_evidence / approved / merged / rejected';
COMMENT ON COLUMN subject_candidates.matched_subject_id IS 'Existing subject suggested as likely same entity before review';
COMMENT ON COLUMN subject_candidates.approved_subject_id IS 'Subject created or selected when candidate is approved or merged';

DO $$
BEGIN
    EXECUTE format(
        'DROP TRIGGER IF EXISTS trigger_update_subject_candidates_updated_at ON subject_candidates; '
        'CREATE TRIGGER trigger_update_subject_candidates_updated_at BEFORE UPDATE ON subject_candidates '
        'FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();'
    );
END;
$$;

ALTER TABLE subject_candidates ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON subject_candidates FROM anon;
REVOKE ALL ON subject_candidates FROM authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_candidates TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_candidates TO authenticated;

DROP POLICY IF EXISTS "subject candidates admin manage" ON subject_candidates;
CREATE POLICY "subject candidates admin manage"
    ON subject_candidates
    FOR ALL
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid)
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);
