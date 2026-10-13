-- migrate_mid_exam.sql
-- Run once against your MySQL database to add mid exam tables.
-- Safe to run if tables already exist (uses IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS mid_objective_questions (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    subject_id       INT NOT NULL,
    unit_id          INT NOT NULL,
    question_type    VARCHAR(10) NOT NULL COMMENT 'mcq or fib',
    question_text    TEXT NOT NULL,
    option_a         TEXT,
    option_b         TEXT,
    option_c         TEXT,
    option_d         TEXT,
    correct_answer   VARCHAR(1),
    answer_text      TEXT,
    bloom_level      VARCHAR(20) DEFAULT 'Remember',
    is_active        TINYINT(1) DEFAULT 1,
    usage_count      INT DEFAULT 0,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (unit_id)    REFERENCES units(id)    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mid_subjective_questions (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    subject_id       INT NOT NULL,
    unit_id          INT NOT NULL,
    question_text    TEXT NOT NULL,
    marks            INT NOT NULL DEFAULT 4,
    bloom_level      VARCHAR(20) DEFAULT 'Understand',
    difficulty       VARCHAR(20) DEFAULT 'Medium',
    answer_text      TEXT,
    unit_half        VARCHAR(10) COMMENT 'NULL=whole unit, first=mid1 half, second=mid2 half',
    is_active        TINYINT(1) DEFAULT 1,
    usage_count      INT DEFAULT 0,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (unit_id)    REFERENCES units(id)    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generated_mid_papers (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    subject_id              INT NOT NULL,
    mid_number              INT NOT NULL COMMENT '1 or 2',
    mcq_question_ids        JSON NOT NULL,
    fib_question_ids        JSON NOT NULL,
    subjective_question_ids JSON NOT NULL,
    total_marks             INT DEFAULT 30,
    status                  VARCHAR(20) DEFAULT 'Draft',
    generated_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    pdf_path                VARCHAR(255),
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);