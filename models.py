from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100))
    role = db.Column(db.String(20), default='faculty')  # 'faculty' or 'admin'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


ROMAN_MAP = {1: 'I', 2: 'II', 3: 'III', 4: 'IV'}


# ----------------------------------------------------------------------
# BRANCH (CSE / AI&ML / ECE etc.)
# ----------------------------------------------------------------------
class Branch(db.Model):
    __tablename__ = 'branches'

    id = db.Column(db.Integer, primary_key=True)
    branch_code = db.Column(db.String(20), unique=True, nullable=False)
    branch_name = db.Column(db.String(100), nullable=False)

    def get_subjects(self, academic_year=None, semester_number=None):
        """Subjects taught to this branch, optionally filtered to one term."""
        query = BranchSubject.query.filter_by(branch_id=self.id)
        if academic_year is not None:
            query = query.filter_by(academic_year=academic_year)
        if semester_number is not None:
            query = query.filter_by(semester_number=semester_number)
        return [link.subject for link in query.all()]


# ----------------------------------------------------------------------
# SUBJECT
# ----------------------------------------------------------------------
class Subject(db.Model):
    __tablename__ = 'subjects'

    id = db.Column(db.Integer, primary_key=True)

    subject_name = db.Column(db.String(150), nullable=False)
    # Nullable on purpose: Year 3-4 subjects in the official syllabi have no
    # course code assigned yet (titles only). code_pending flags those rows
    # so the UI can show "Code TBD" instead of a blank/fake code.
    subject_code = db.Column(db.String(20), unique=True, nullable=True)
    code_pending = db.Column(db.Boolean, default=False)

    # NOTE: academic_year / semester_number used to live here, but real
    # syllabus data showed the SAME subject_code can sit in a different
    # year/semester depending on the branch (e.g. A2006 is Y1-S1 for
    # ECE/CSE but Y1-S2 for AIML). That per-branch term now lives on
    # BranchSubject instead — see below.

    total_marks = db.Column(db.Integer, default=60)
    duration_minutes = db.Column(db.Integer, default=180)
    part_a_marks = db.Column(db.Integer, default=10)
    part_a_count = db.Column(db.Integer, default=10)
    part_b_marks = db.Column(db.Integer, default=50)
    part_b_count = db.Column(db.Integer, default=5)

    units = db.relationship('Unit', backref='subject', lazy=True)

    def branch_codes(self):
        """Quick helper: which branches teach this subject."""
        return [link.branch.branch_code for link in self.branch_links]


# ----------------------------------------------------------------------
# BRANCH <-> SUBJECT LINK (replaces the old plain association table)
#
# This is a real model (not just db.Table) because year/semester are
# PER-BRANCH, not a property of the subject itself. One Subject row can
# have multiple BranchSubject rows, each with its own academic_year /
# semester_number for that branch.
# ----------------------------------------------------------------------
class BranchSubject(db.Model):
    __tablename__ = 'branch_subjects'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)

    academic_year = db.Column(db.Integer, nullable=False)        # 1-4
    semester_number = db.Column(db.Integer, nullable=False)      # 1-2

    # NULL for core/compulsory subjects. For elective options, holds the
    # slot name this option belongs to (e.g. "Professional Elective-I"),
    # normalized to the canonical form used in seed_curriculum.py. The
    # option itself is still a fully independent, searchable Subject —
    # this column only tags WHICH elective slot it satisfies for this
    # branch+year+semester. It lives here (not on Subject) because the
    # same option title could theoretically satisfy different slots in
    # different branches.
    elective_group = db.Column(db.String(50), nullable=True)

    branch = db.relationship('Branch', backref=db.backref('subject_links', lazy=True))
    subject = db.relationship('Subject', backref=db.backref('branch_links', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('branch_id', 'subject_id', name='uq_branch_subject'),
    )

    def get_roman_term(self):
        """e.g. 'II-I' for Year 2, Semester 1, for THIS branch's link."""
        yr = ROMAN_MAP.get(self.academic_year, str(self.academic_year))
        sem = ROMAN_MAP.get(self.semester_number, str(self.semester_number))
        return f"{yr}-{sem}"


class Unit(db.Model):
    __tablename__ = 'units'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    unit_number = db.Column(db.Integer, nullable=False)
    unit_name = db.Column(db.String(150), nullable=False)

    question_groups = db.relationship('QuestionGroup', backref='unit', lazy=True)
    part_a_questions = db.relationship('PartAQuestion', backref='unit', lazy=True)


# ----------------------------------------------------------------------
# PART A QUESTIONS (1-mark, no choice, no sub-parts)
# ----------------------------------------------------------------------
class PartAQuestion(db.Model):
    __tablename__ = 'part_a_questions'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    bloom_level = db.Column(db.String(20), default='Remember')
    answer_text = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    # How many generated papers have included this question — same idea as
    # QuestionGroup.usage_count below. Used to rank "important questions"
    # for the teacher-facing lookup page: questions that keep getting
    # selected across papers are the ones worth flagging for revision.
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ----------------------------------------------------------------------
# QUESTION GROUP (= one printed Part-B question number, e.g. "Q11")
# ----------------------------------------------------------------------
class QuestionGroup(db.Model):
    __tablename__ = 'question_groups'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=False)
    topic_id = db.Column(db.Integer, nullable=True)  # reserved for later use
    total_marks = db.Column(db.Integer, nullable=False, default=10)
    difficulty = db.Column(db.String(20), default='Medium')   # Easy / Medium / Hard
    question_type = db.Column(db.String(20), default='Single')  # 'Single' or 'Compound'
    is_active = db.Column(db.Boolean, default=True)
    is_pending = db.Column(db.Boolean, default=False)  # True = awaiting review
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    parts = db.relationship('QuestionPart', backref='group', lazy=True,
                             order_by='QuestionPart.part_order')

    def combined_text_preview(self):
        """Quick helper to see the whole question as one string (used in admin views)."""
        return " | ".join([p.question_text[:60] for p in self.parts])


# ----------------------------------------------------------------------
# QUESTION PART (the actual text — either the whole Single question,
# or one of the a/b sub-parts of a Compound question)
# ----------------------------------------------------------------------
class QuestionPart(db.Model):
    __tablename__ = 'question_parts'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('question_groups.id'), nullable=False)
    part_label = db.Column(db.String(5), nullable=True)   # NULL for Single, 'a'/'b' for Compound
    part_order = db.Column(db.Integer, default=1)
    question_text = db.Column(db.Text, nullable=False)
    marks = db.Column(db.Integer, nullable=False)
    bloom_level = db.Column(db.String(20), default='Understand')
    answer_text = db.Column(db.Text)


# ----------------------------------------------------------------------
# PENDING QUESTION (AI-generated OR manually bulk-pasted, awaiting review)
#
# RESTORED to the shape app.py / bulk_parser.py / questions.html actually
# use. The previous version of this file had been reduced to a flat
# text/marks/difficulty/bloom_level/part_type stub — almost certainly
# clobbered while the Branch<->Subject many-to-many edit was pasted in —
# which doesn't match payload_json-based approve/reject flow used
# everywhere else.
# ----------------------------------------------------------------------
class PendingQuestion(db.Model):
    __tablename__ = 'pending_questions'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=False)

    question_kind = db.Column(db.String(10), nullable=False)   # 'part_a' or 'group'
    payload_json = db.Column(db.JSON, nullable=False)

    topics_text = db.Column(db.Text)        # teacher-typed topics, or bulk-add marker
    raw_ai_response = db.Column(db.Text)    # raw Gemini text, NULL for bulk-add rows

    status = db.Column(db.String(20), default='pending')  # pending / approved / rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    subject = db.relationship('Subject', backref='pending_questions')
    unit = db.relationship('Unit', backref='pending_questions')


# ----------------------------------------------------------------------
# GENERATED PAPER
# ----------------------------------------------------------------------
class GeneratedPaper(db.Model):
    __tablename__ = 'generated_papers'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    total_marks = db.Column(db.Integer)
    difficulty_ratio = db.Column(db.String(50))
    requested_difficulty = db.Column(db.String(20), nullable=True)   # 'Easy'/'Medium'/'Hard'/'Mixed' chosen by user
    selected_unit_ids = db.Column(db.JSON, nullable=True)            # which units the user opted into
    part_a_question_ids = db.Column(db.JSON)   # list of PartAQuestion ids, length 10
    status = db.Column(db.String(20), default='Draft')   # Draft / Locked / Exported
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_path = db.Column(db.String(255))

    slots = db.relationship('PaperUnitSlot', backref='paper', lazy=True)


# ----------------------------------------------------------------------
# PAPER UNIT SLOT (the "Q11 OR Q12" pairing for ONE unit in ONE generated paper)
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# MID EXAM OBJECTIVE QUESTION (MCQ or Fill-in-the-Blank, 0.5 marks each)
# Used for Part-A of mid exam papers (10 MCQ + 10 FIB = 10 marks)
# ----------------------------------------------------------------------
class MidObjectiveQuestion(db.Model):
    __tablename__ = 'mid_objective_questions'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=False)

    question_type = db.Column(db.String(10), nullable=False)  # 'mcq' or 'fib'
    question_text = db.Column(db.Text, nullable=False)

    # MCQ fields
    option_a = db.Column(db.Text, nullable=True)
    option_b = db.Column(db.Text, nullable=True)
    option_c = db.Column(db.Text, nullable=True)
    option_d = db.Column(db.Text, nullable=True)
    correct_answer = db.Column(db.String(1), nullable=True)  # 'A','B','C','D' or fill answer

    answer_text = db.Column(db.Text, nullable=True)   # fill-blank answer or MCQ explanation
    bloom_level = db.Column(db.String(20), default='Remember')
    is_active = db.Column(db.Boolean, default=True)
    is_pending = db.Column(db.Boolean, default=False)  # True = awaiting review
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    subject = db.relationship('Subject', backref='mid_objective_questions')
    unit = db.relationship('Unit', backref='mid_objective_questions')


# ----------------------------------------------------------------------
# MID EXAM SUBJECTIVE QUESTION — DEPRECATED
# Part-B now uses QuestionGroup bank. This model/table kept for DB
# compatibility only. Do NOT use in new code.
# ----------------------------------------------------------------------
class MidSubjectiveQuestion(db.Model):
    __tablename__ = 'mid_subjective_questions'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=False)

    question_text = db.Column(db.Text, nullable=False)
    marks = db.Column(db.Integer, nullable=False, default=4)
    bloom_level = db.Column(db.String(20), default='Understand')
    difficulty = db.Column(db.String(20), default='Medium')
    answer_text = db.Column(db.Text, nullable=True)

    # For the boundary unit (unit 3): tag which half this belongs to
    # None = whole unit (usable in either mid), 'first' = mid-1 half, 'second' = mid-2 half
    unit_half = db.Column(db.String(10), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    is_pending = db.Column(db.Boolean, default=False)  # True = awaiting review
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    subject = db.relationship('Subject', backref='mid_subjective_questions')
    unit = db.relationship('Unit', backref='mid_subjective_questions')


# ----------------------------------------------------------------------
# GENERATED MID PAPER
# ----------------------------------------------------------------------
class GeneratedMidPaper(db.Model):
    __tablename__ = 'generated_mid_papers'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    mid_number = db.Column(db.Integer, nullable=False)   # 1 or 2

    # Part-A: JSON list of MidObjectiveQuestion ids (10 MCQ + 10 FIB = 20 ids)
    mcq_question_ids = db.Column(db.JSON, nullable=False, default=list)
    fib_question_ids = db.Column(db.JSON, nullable=False, default=list)

    # Part-B: JSON list of QuestionGroup ids (4 Single + 2 Compound = 6 groups, 5M each)
    # Replaces old subjective_question_ids (MidSubjectiveQuestion, now deprecated).
    part_b_group_ids = db.Column(db.JSON, nullable=False, default=list)

    total_marks = db.Column(db.Integer, default=30)
    status = db.Column(db.String(20), default='Draft')
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_path = db.Column(db.String(255))

    subject = db.relationship('Subject', backref='mid_papers')


class PaperUnitSlot(db.Model):
    __tablename__ = 'paper_unit_slots'

    id = db.Column(db.Integer, primary_key=True)
    paper_id = db.Column(db.Integer, db.ForeignKey('generated_papers.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=False)
    slot_position = db.Column(db.Integer)   # 1 to 5, printed order in the paper

    primary_group_id = db.Column(db.Integer, db.ForeignKey('question_groups.id'), nullable=False)
    alternative_group_id = db.Column(db.Integer, db.ForeignKey('question_groups.id'), nullable=False)

    primary_group = db.relationship('QuestionGroup', foreign_keys=[primary_group_id])
    alternative_group = db.relationship('QuestionGroup', foreign_keys=[alternative_group_id])

# ----------------------------------------------------------------------
# COURSE OUTCOME  (populated from CO-PO mapping excel)
# ----------------------------------------------------------------------
class CourseOutcome(db.Model):
    __tablename__ = 'course_outcomes'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    co_number = db.Column(db.String(10), nullable=False)   # 'CO1' .. 'CO6'
    statement = db.Column(db.Text, nullable=False)
    po_mapping = db.Column(db.JSON, nullable=True)   # {'PO1': '3', 'PO2': '2', ...}
    co_avg = db.Column(db.Float, nullable=True)      # CO AVG from excel

    subject = db.relationship('Subject', backref=db.backref('course_outcomes', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('subject_id', 'co_number', name='uq_subject_co'),
    )


# ----------------------------------------------------------------------
# ASSIGNMENT QUESTION
# ----------------------------------------------------------------------
ASSIGNMENT_TYPES = [
    'descriptive', 'project', 'seminar', 'working_prototype',
    'scenario', 'innovative', 'case_study', 'survey', 'presentation'
]


class AssignmentQuestion(db.Model):
    __tablename__ = 'assignment_questions'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=False)
    assignment_number = db.Column(db.Integer, nullable=False)  # 1 or 2
    question_text = db.Column(db.Text, nullable=False)
    assignment_type = db.Column(db.String(30), nullable=False, default='descriptive')
    co_mapping = db.Column(db.String(50))   # comma-separated e.g. 'CO1,CO3'
    bloom_level = db.Column(db.String(20), default='Apply')
    marks = db.Column(db.Integer, nullable=False, default=10)
    is_active = db.Column(db.Boolean, default=True)
    is_pending = db.Column(db.Boolean, default=False)
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    subject = db.relationship('Subject', backref=db.backref('assignment_questions', lazy=True))
    unit = db.relationship('Unit', backref=db.backref('assignment_questions', lazy=True))


# ----------------------------------------------------------------------
# GENERATED ASSIGNMENT
# ----------------------------------------------------------------------
class GeneratedAssignment(db.Model):
    __tablename__ = 'generated_assignments'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    assignment_number = db.Column(db.Integer, nullable=False)   # 1 or 2
    question_count = db.Column(db.Integer, nullable=False, default=5)
    question_ids = db.Column(db.JSON, nullable=False, default=list)
    status = db.Column(db.String(20), default='Draft')
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_path = db.Column(db.String(255))

    subject = db.relationship('Subject', backref=db.backref('assignments', lazy=True))