-- ============================================================
-- Subject V1 Guardrails
--
-- This migration adds the missing subject audit and tracking layer:
-- - subject_stats view for real mention counts
-- - provenance columns on subject_mentions
-- - tracks table and subject_tracks audit link
-- - evidence / facts / relations / extraction_runs tables
-- - record_subject_mention RPC for atomic mention writes
-- ============================================================

BEGIN;

ALTER TABLE subject_mentions
    ADD COLUMN IF NOT EXISTS detected_by TEXT,
    ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN subject_mentions.detected_by IS 'Extractor or manual path that detected the mention';
COMMENT ON COLUMN subject_mentions.confidence IS 'Mention detection confidence between 0 and 1';
COMMENT ON COLUMN subject_mentions.evidence IS 'Structured evidence payload for provenance and audit';

CREATE OR REPLACE VIEW subject_stats
WITH (security_invoker = true) AS
SELECT
    subject_id,
    COUNT(*) AS mention_count,
    MIN(snapshot_date) AS first_seen_at,
    MAX(snapshot_date) AS last_seen_at,
    COUNT(DISTINCT item_id) AS item_count
FROM subject_mentions
GROUP BY subject_id;

CREATE TABLE IF NOT EXISTS tracks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    display_name_en TEXT,
    description TEXT,
    group_name TEXT NOT NULL DEFAULT 'general',
    cover_color TEXT,
    display_order INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT tracks_status_check
        CHECK (status IN ('active', 'hidden', 'deprecated'))
);

CREATE INDEX IF NOT EXISTS idx_tracks_status_order
    ON tracks (status, display_order, group_name);

COMMENT ON TABLE tracks IS 'Subject / project track catalog used by project heatmap aggregation';

DO $$
BEGIN
    EXECUTE format(
        'DROP TRIGGER IF EXISTS trigger_update_tracks_updated_at ON tracks; '
        'CREATE TRIGGER trigger_update_tracks_updated_at BEFORE UPDATE ON tracks '
        'FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();'
    );
END;
$$;

CREATE TABLE IF NOT EXISTS subject_tracks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    track_id UUID NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    confidence DOUBLE PRECISION,
    assigned_by TEXT NOT NULL DEFAULT 'rule',
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT subject_tracks_assigned_by_check
        CHECK (assigned_by IN ('rule', 'llm', 'manual', 'import'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_tracks_subject_track_from
    ON subject_tracks (subject_id, track_id, valid_from);
CREATE INDEX IF NOT EXISTS idx_subject_tracks_subject_primary
    ON subject_tracks (subject_id, is_primary, valid_to);
CREATE INDEX IF NOT EXISTS idx_subject_tracks_track
    ON subject_tracks (track_id, valid_to);

COMMENT ON TABLE subject_tracks IS 'Auditable subject -> track assignment history';

DO $$
BEGIN
    EXECUTE format(
        'DROP TRIGGER IF EXISTS trigger_update_subject_tracks_updated_at ON subject_tracks; '
        'CREATE TRIGGER trigger_update_subject_tracks_updated_at BEFORE UPDATE ON subject_tracks '
        'FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();'
    );
END;
$$;

CREATE TABLE IF NOT EXISTS subject_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    candidate_subject_key TEXT,
    item_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    evidence_type TEXT NOT NULL,
    source_field TEXT,
    json_path TEXT,
    text_excerpt TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    detected_by TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT subject_evidence_type_check
        CHECK (evidence_type IN ('identity', 'mention', 'fact', 'relation', 'track')),
    CONSTRAINT subject_evidence_confidence_check
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_evidence_key
    ON subject_evidence (item_id, snapshot_date, candidate_subject_key, evidence_type, json_path, extractor_version);
CREATE INDEX IF NOT EXISTS idx_subject_evidence_subject_date
    ON subject_evidence (subject_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_subject_evidence_item_date
    ON subject_evidence (item_id, snapshot_date DESC);

COMMENT ON TABLE subject_evidence IS 'Structured evidence snippets used to justify subject mentions, facts and relations';

CREATE TABLE IF NOT EXISTS subject_facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    candidate_subject_key TEXT,
    item_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    fact_type TEXT NOT NULL,
    value JSONB NOT NULL,
    observed_at TIMESTAMPTZ,
    confidence DOUBLE PRECISION,
    evidence_id UUID REFERENCES subject_evidence(id) ON DELETE SET NULL,
    extractor_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT subject_facts_type_check
        CHECK (fact_type IN ('release', 'funding', 'benchmark', 'launch', 'metric', 'hiring', 'controversy')),
    CONSTRAINT subject_facts_confidence_check
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_facts_key
    ON subject_facts (subject_id, item_id, snapshot_date, fact_type, extractor_version);
CREATE INDEX IF NOT EXISTS idx_subject_facts_subject_date
    ON subject_facts (subject_id, snapshot_date DESC);

COMMENT ON TABLE subject_facts IS 'Structured subject facts extracted from raw items';

CREATE TABLE IF NOT EXISTS subject_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    to_subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    from_candidate_key TEXT,
    to_candidate_key TEXT,
    relation_type TEXT NOT NULL,
    item_id TEXT,
    snapshot_date DATE,
    confidence DOUBLE PRECISION,
    evidence_id UUID REFERENCES subject_evidence(id) ON DELETE SET NULL,
    extractor_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT subject_relations_type_check
        CHECK (relation_type IN ('mentions', 'competitor', 'built_on', 'owned_by', 'created_by', 'same_as', 'implements')),
    CONSTRAINT subject_relations_confidence_check
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_relations_key
    ON subject_relations (from_subject_id, to_subject_id, relation_type, item_id, snapshot_date, extractor_version);
CREATE INDEX IF NOT EXISTS idx_subject_relations_from
    ON subject_relations (from_subject_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_subject_relations_to
    ON subject_relations (to_subject_id, snapshot_date DESC);

COMMENT ON TABLE subject_relations IS 'Directed subject-to-subject relations with provenance';

CREATE TABLE IF NOT EXISTS subject_extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_date DATE NOT NULL,
    source TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    input_count INTEGER NOT NULL DEFAULT 0,
    extracted_subject_count INTEGER NOT NULL DEFAULT 0,
    mention_count INTEGER NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT subject_extraction_runs_status_check
        CHECK (status IN ('running', 'succeeded', 'failed', 'skipped'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_extraction_runs_key
    ON subject_extraction_runs (snapshot_date, source, extractor_version);
CREATE INDEX IF NOT EXISTS idx_subject_extraction_runs_status
    ON subject_extraction_runs (status, started_at DESC);

COMMENT ON TABLE subject_extraction_runs IS 'Audit rows for subject extraction jobs and backfills';

CREATE OR REPLACE FUNCTION record_subject_mention(
    p_slug TEXT,
    p_type TEXT,
    p_display_name TEXT,
    p_item_id TEXT,
    p_snapshot_date DATE,
    p_role TEXT DEFAULT 'mentioned',
    p_source_name TEXT DEFAULT NULL,
    p_score DOUBLE PRECISION DEFAULT NULL,
    p_context TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'::jsonb,
    p_detected_by TEXT DEFAULT 'pipeline.enrich',
    p_confidence DOUBLE PRECISION DEFAULT NULL,
    p_evidence JSONB DEFAULT '{}'::jsonb
)
RETURNS TABLE (
    subject_id UUID,
    mention_id UUID,
    mention_inserted BOOLEAN
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_subject_id UUID;
    v_mention_id UUID;
BEGIN
    INSERT INTO subjects (
        slug,
        type,
        display_name,
        metadata,
        first_seen_at,
        last_seen_at,
        mention_count
    )
    VALUES (
        p_slug,
        p_type,
        p_display_name,
        COALESCE(p_metadata, '{}'::jsonb),
        p_snapshot_date,
        p_snapshot_date,
        0
    )
    ON CONFLICT (slug) DO UPDATE SET
        type = EXCLUDED.type,
        display_name = EXCLUDED.display_name,
        metadata = CASE
            WHEN EXCLUDED.metadata = '{}'::jsonb THEN subjects.metadata
            ELSE EXCLUDED.metadata
        END,
        first_seen_at = LEAST(subjects.first_seen_at, EXCLUDED.first_seen_at),
        last_seen_at = GREATEST(subjects.last_seen_at, EXCLUDED.last_seen_at)
    RETURNING id INTO v_subject_id;

    INSERT INTO subject_mentions (
        subject_id,
        item_id,
        snapshot_date,
        role,
        source_name,
        score,
        context,
        detected_by,
        confidence,
        evidence
    )
    VALUES (
        v_subject_id,
        p_item_id,
        p_snapshot_date,
        COALESCE(p_role, 'mentioned'),
        p_source_name,
        p_score,
        LEFT(COALESCE(p_context, ''), 500),
        p_detected_by,
        p_confidence,
        COALESCE(p_evidence, '{}'::jsonb)
    )
    ON CONFLICT (subject_id, item_id, snapshot_date) DO NOTHING
    RETURNING id INTO v_mention_id;

    IF v_mention_id IS NOT NULL THEN
        UPDATE subjects
        SET mention_count = mention_count + 1,
            last_seen_at = GREATEST(last_seen_at, p_snapshot_date)
        WHERE id = v_subject_id;
    END IF;

    subject_id := v_subject_id;
    mention_id := v_mention_id;
    mention_inserted := v_mention_id IS NOT NULL;
    RETURN NEXT;
END;
$$;

COMMIT;
