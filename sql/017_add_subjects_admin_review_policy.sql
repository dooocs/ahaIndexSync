-- ============================================================
-- Subject Admin Review Policy
--
-- Admin review promotes approved subject_candidates into subjects.
-- The Admin frontend uses the publishable key, so RLS must explicitly allow
-- the trusted Admin user to read existing subjects and insert/update approved
-- catalog rows.
-- ============================================================

ALTER TABLE subjects ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON subjects TO authenticated;

DROP POLICY IF EXISTS "subjects admin select" ON subjects;
CREATE POLICY "subjects admin select"
    ON subjects
    FOR SELECT
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

DROP POLICY IF EXISTS "subjects admin insert" ON subjects;
CREATE POLICY "subjects admin insert"
    ON subjects
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);

DROP POLICY IF EXISTS "subjects admin update" ON subjects;
CREATE POLICY "subjects admin update"
    ON subjects
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid)
    WITH CHECK (auth.uid() = 'e3bffb6b-3a56-4c40-b47f-8bcb2de7916a'::uuid);
