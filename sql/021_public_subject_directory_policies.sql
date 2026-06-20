-- ============================================================
-- Public Subject Directory Read Policies
--
-- Allow the public frontend to read only curated subject directory rows
-- and published subject insights. This keeps the broader subject graph
-- private while exposing the approved directory/read models.
-- ============================================================

BEGIN;

ALTER TABLE public.subjects ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON public.subjects TO anon;

DROP POLICY IF EXISTS "subjects public select" ON public.subjects;
CREATE POLICY "subjects public select"
    ON public.subjects
    FOR SELECT
    TO anon
    USING (status = 'active' AND directory_visible = true);

ALTER TABLE public.subject_insights ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON public.subject_insights TO anon;

DROP POLICY IF EXISTS "subject insights public select" ON public.subject_insights;
CREATE POLICY "subject insights public select"
    ON public.subject_insights
    FOR SELECT
    TO anon
    USING (status = 'published');

COMMIT;
