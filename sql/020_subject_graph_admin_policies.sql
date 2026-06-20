-- ============================================================
-- Subject Graph Admin Policies
--
-- Admin UI uses the anon key plus authenticated session, so the new subject
-- graph tables need explicit grants and policies. Service role access keeps
-- working for pipeline and build-time reads.
-- ============================================================

BEGIN;

ALTER TABLE subject_mentions ENABLE ROW LEVEL SECURITY;
ALTER TABLE subject_tracks ENABLE ROW LEVEL SECURITY;
ALTER TABLE subject_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE subject_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE subject_relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE subject_extraction_runs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON subject_mentions FROM anon;
REVOKE ALL ON subject_mentions FROM authenticated;
REVOKE ALL ON subject_tracks FROM anon;
REVOKE ALL ON subject_tracks FROM authenticated;
REVOKE ALL ON subject_evidence FROM anon;
REVOKE ALL ON subject_evidence FROM authenticated;
REVOKE ALL ON subject_facts FROM anon;
REVOKE ALL ON subject_facts FROM authenticated;
REVOKE ALL ON subject_relations FROM anon;
REVOKE ALL ON subject_relations FROM authenticated;
REVOKE ALL ON subject_extraction_runs FROM anon;
REVOKE ALL ON subject_extraction_runs FROM authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON subject_mentions TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_mentions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_tracks TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_tracks TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_evidence TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_evidence TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_facts TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_facts TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_relations TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_relations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_extraction_runs TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON subject_extraction_runs TO authenticated;
GRANT SELECT ON subject_stats TO service_role;
GRANT SELECT ON subject_stats TO authenticated;

DROP POLICY IF EXISTS "subject mentions admin manage" ON subject_mentions;
CREATE POLICY "subject mentions admin manage"
    ON subject_mentions
    FOR ALL
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid)
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

DROP POLICY IF EXISTS "subject tracks admin manage" ON subject_tracks;
CREATE POLICY "subject tracks admin manage"
    ON subject_tracks
    FOR ALL
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid)
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

DROP POLICY IF EXISTS "subject evidence admin manage" ON subject_evidence;
CREATE POLICY "subject evidence admin manage"
    ON subject_evidence
    FOR ALL
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid)
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

DROP POLICY IF EXISTS "subject facts admin manage" ON subject_facts;
CREATE POLICY "subject facts admin manage"
    ON subject_facts
    FOR ALL
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid)
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

DROP POLICY IF EXISTS "subject relations admin manage" ON subject_relations;
CREATE POLICY "subject relations admin manage"
    ON subject_relations
    FOR ALL
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid)
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

DROP POLICY IF EXISTS "subject extraction runs admin manage" ON subject_extraction_runs;
CREATE POLICY "subject extraction runs admin manage"
    ON subject_extraction_runs
    FOR ALL
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid)
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

COMMIT;
