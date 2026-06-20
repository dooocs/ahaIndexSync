-- ============================================================
-- Subject Catalog Fields
--
-- Existing subjects are the historical project graph. Directory pages should
-- not show all 1300+ project subjects by default. These fields separate
-- "known subject in graph" from "curated subject visible in directory".
-- ============================================================

ALTER TABLE subjects
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS directory_visible BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS section_slug TEXT,
    ADD COLUMN IF NOT EXISTS curation_priority INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT 'pipeline',
    ADD COLUMN IF NOT EXISTS definition TEXT,
    ADD COLUMN IF NOT EXISTS homepage_url TEXT;

CREATE INDEX IF NOT EXISTS idx_subjects_directory_visible
    ON subjects (directory_visible, curation_priority DESC, display_name)
    WHERE directory_visible = true;

CREATE INDEX IF NOT EXISTS idx_subjects_section_slug
    ON subjects (section_slug, curation_priority DESC)
    WHERE directory_visible = true;

COMMENT ON COLUMN subjects.status IS 'active / hidden / merged / deprecated. Existing project graph rows remain active but are not directory-visible by default.';
COMMENT ON COLUMN subjects.directory_visible IS 'Whether this subject is allowed into the public subject directory/read model.';
COMMENT ON COLUMN subjects.section_slug IS 'Directory section slug for MVP list pages, e.g. agent, company, person, task.';
COMMENT ON COLUMN subjects.curation_priority IS 'Manual ranking weight for directory ordering.';
COMMENT ON COLUMN subjects.created_by IS 'pipeline / seed / admin / approved_candidate / import.';
COMMENT ON COLUMN subjects.definition IS 'Curated definition for the subject catalog, separate from LLM summaries.';
COMMENT ON COLUMN subjects.homepage_url IS 'Canonical homepage/profile/company/site/repository URL for the subject.';
