-- Migration: Assignments feature
-- Run once against your MySQL DB

-- Course Outcomes table (mapped from CO-PO excel)
CREATE TABLE IF NOT EXISTS course_outcomes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id INT NOT NULL,
    co_number VARCHAR(10) NOT NULL,           -- e.g. 'CO1', 'CO2'
    statement TEXT NOT NULL,
    FOREIGN KEY (subject_id) REFERENCES subjects(id),
    UNIQUE KEY uq_subject_co (subject_id, co_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Assignment Questions bank
CREATE TABLE IF NOT EXISTS assignment_questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id INT NOT NULL,
    unit_id INT NOT NULL,
    assignment_number INT NOT NULL,           -- 1 or 2 (mirrors mid-1 / mid-2 unit split)
    question_text TEXT NOT NULL,
    assignment_type VARCHAR(30) NOT NULL DEFAULT 'descriptive',
    -- types: descriptive, project, seminar, working_prototype, scenario, innovative, case_study
    co_mapping VARCHAR(50),                   -- e.g. 'CO1,CO3'
    bloom_level VARCHAR(20) DEFAULT 'Apply',
    marks INT NOT NULL DEFAULT 10,
    is_active BOOLEAN DEFAULT TRUE,
    is_pending BOOLEAN DEFAULT FALSE,
    usage_count INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id),
    FOREIGN KEY (unit_id) REFERENCES units(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Generated Assignment Papers
CREATE TABLE IF NOT EXISTS generated_assignments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id INT NOT NULL,
    assignment_number INT NOT NULL,           -- 1 or 2
    question_count INT NOT NULL DEFAULT 5,   -- 5–10, user chosen
    question_ids JSON NOT NULL,              -- list of AssignmentQuestion ids
    status VARCHAR(20) DEFAULT 'Draft',
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    pdf_path VARCHAR(255),
    FOREIGN KEY (subject_id) REFERENCES subjects(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

