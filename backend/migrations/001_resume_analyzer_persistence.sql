-- Apply after database/sql/placement_management_v1.sql.
-- Stores extracted resume content and analysis detail omitted from the base schema.
CREATE TABLE IF NOT EXISTS resume_extractions (
    resume_id uuid PRIMARY KEY REFERENCES resumes(resume_id) ON DELETE CASCADE,
    extracted_text text NOT NULL,
    structured_data jsonb NOT NULL,
    extraction_version varchar(30) NOT NULL,
    created_at timestamp NOT NULL
);

CREATE TABLE IF NOT EXISTS resume_analysis_details (
    analysis_id uuid PRIMARY KEY REFERENCES resume_analysis(analysis_id) ON DELETE CASCADE,
    target_job_description text,
    keyword_match_percentage numeric(5, 2),
    skill_match_percentage numeric(5, 2),
    experience_match_percentage numeric(5, 2),
    formatting_score numeric(5, 2),
    scoring_method varchar(50) NOT NULL
);
