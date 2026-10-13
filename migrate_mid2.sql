-- migrate_mid_partb.sql
-- Switches generated_mid_papers.subjective_question_ids → part_b_group_ids
-- (stores QuestionGroup ids instead of MidSubjectiveQuestion ids)
-- Run once. Safe if column already exists.

ALTER TABLE generated_mid_papers
    ADD COLUMN part_b_group_ids JSON NOT NULL DEFAULT (JSON_ARRAY());