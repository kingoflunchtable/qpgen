import os
from functools import wraps
from urllib.parse import quote_plus

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session, flash
from flask_wtf.csrf import CSRFProtect

from models import (
    db, Branch, Subject, BranchSubject, Unit, PartAQuestion, QuestionGroup, QuestionPart,
    GeneratedPaper, PaperUnitSlot, PendingQuestion, User,
    MidObjectiveQuestion, GeneratedMidPaper,
    CourseOutcome, AssignmentQuestion, GeneratedAssignment, ASSIGNMENT_TYPES
)
from generator import generate_paper, swap_question_group, get_paper_data_for_export, get_important_questions
from generator import generate_mid_paper, get_mid_paper_data_for_export
from pdf_generator import render_paper_pdf, render_important_questions_pdf, render_mid_paper_pdf
from bulk_parser import parse_bulk_text

load_dotenv()

app = Flask(__name__)

# SECRET_KEY is required for sessions (login) and CSRF protection to work at
# all. Set a real value in .env for production — this fallback is fine for
# local dev only, since it means sessions reset every time the value changes.
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "dev-only-change-me")
csrf = CSRFProtect(app)


def login_required(view_func):
    """
    Kept for any route where you want to be extra explicit, but actual
    enforcement for the whole site happens via the before_request hook
    below — a single allowlist is much harder to accidentally leave a
    hole in than decorating ~20 routes individually and missing one.
    """
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        return view_func(*args, **kwargs)
    return wrapped


# Only these endpoints are reachable without being logged in. Everything
# else — every page, every /api/ route, every form POST — requires a
# session. 'static' covers CSS/JS/images served by Flask's built-in
# static route, which must stay public or the login page's own logo and
# background image would fail to load.
PUBLIC_ENDPOINTS = {'login', 'signup', 'static'}


@app.before_request
def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if not session.get('user_id'):
        return redirect(url_for('login', next=request.path))
    return None


@app.context_processor
def inject_current_user():
    """Makes `current_user` available in every template (base.html's nav
    reads this to show either a username+logout or a login link) without
    every single route needing to look it up and pass it explicitly."""
    user = None
    if session.get('user_id'):
        user = User.query.get(session['user_id'])
    return {'current_user': user}


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            next_url = request.args.get('next')
            # Only honor 'next' if it's a relative path on this same site —
            # an absolute/external URL here would be an open-redirect hole.
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('home'))

        flash('Incorrect username or password.')
        return render_template('login.html'), 401

    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        display_name = request.form.get('display_name', '').strip()

        if not username or not password:
            flash('Username and password are required.')
            return render_template('signup.html'), 400

        if User.query.filter_by(username=username).first():
            flash('That username is already taken.')
            return render_template('signup.html'), 400

        user = User(username=username, display_name=display_name or username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        session['user_id'] = user.id
        return redirect(url_for('home'))

    return render_template('signup.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))


# --- DATABASE CONFIGURATION ---
# Pulled from .env — see .env.example. Never hardcode credentials here.
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "exam_generator_db")

app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"mysql+mysqlconnector://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}/{DB_NAME}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


# ----------------------------------------------------------------------
# PAGE ROUTES
# ----------------------------------------------------------------------
@app.route('/')
def home():
    stats = {
        "branch_count": Branch.query.count(),
        "subject_count": Subject.query.count(),
        "question_count": PartAQuestion.query.count() + QuestionGroup.query.count(),
        "pending_count": PendingQuestion.query.filter_by(status='pending').count(),
        "paper_count": GeneratedPaper.query.count(),
    }

    recent_papers = (
        db.session.query(GeneratedPaper, Subject.subject_name, Subject.subject_code)
        .join(Subject, GeneratedPaper.subject_id == Subject.id)
        .order_by(GeneratedPaper.generated_at.desc())
        .limit(5)
        .all()
    )

    return render_template('index.html', stats=stats, recent_papers=recent_papers)


@app.route('/generator', methods=['GET'])
def generator_page():
    branches = Branch.query.order_by(Branch.branch_name).all()
    subjects = Subject.query.order_by(Subject.subject_code).all()
    return render_template('generator.html', branches=branches, subjects=subjects)


# ----------------------------------------------------------------------
# JSON HELPERS — cascading dropdowns for the generator form
# ----------------------------------------------------------------------
@app.route('/api/subjects', methods=['GET'])
def api_subjects():
    """Returns subjects. If branch_id is given, filters to subjects taught
    to that branch (optionally narrowed to one academic_year/semester_number),
    and includes that branch's term info for each subject. Without a
    branch_id, returns every subject with no term info attached."""
    branch_id = request.args.get('branch_id', type=int)
    academic_year = request.args.get('academic_year', type=int)
    semester_number = request.args.get('semester_number', type=int)

    if branch_id:
        query = BranchSubject.query.filter_by(branch_id=branch_id)
        if academic_year:
            query = query.filter_by(academic_year=academic_year)
        if semester_number:
            query = query.filter_by(semester_number=semester_number)
        links = query.join(Subject).order_by(Subject.subject_code).all()
        return jsonify([
            {
                "id": link.subject.id,
                "subject_code": link.subject.subject_code,
                "subject_name": link.subject.subject_name,
                "code_pending": link.subject.code_pending,
                "academic_year": link.academic_year,
                "semester_number": link.semester_number,
                "term": link.get_roman_term(),
                "elective_group": link.elective_group,
            }
            for link in links
        ])

    subjects = Subject.query.order_by(Subject.subject_code).all()
    return jsonify([
        {"id": s.id, "subject_code": s.subject_code, "subject_name": s.subject_name,
         "code_pending": s.code_pending}
        for s in subjects
    ])


@app.route('/api/units', methods=['GET'])
def api_units():
    """Returns units for a given subject_id (by id) or subject_code."""
    subject_id = request.args.get('subject_id', type=int)
    subject_code = request.args.get('subject_code')

    if subject_id:
        units = Unit.query.filter_by(subject_id=subject_id).order_by(Unit.unit_number).all()
    elif subject_code:
        subject = Subject.query.filter_by(subject_code=subject_code).first()
        units = subject.units if subject else []
        units = sorted(units, key=lambda u: u.unit_number)
    else:
        units = []

    return jsonify([
        {"id": u.id, "unit_number": u.unit_number, "unit_name": u.unit_name}
        for u in units
    ])


# ----------------------------------------------------------------------
# ADMIN — read-only browse of the full curriculum (all branches/terms),
# with elective tags and pending-code flags visible at a glance.
# ----------------------------------------------------------------------
@app.route('/admin/subjects', methods=['GET'])
def admin_subjects():
    branches = Branch.query.order_by(Branch.branch_name).all()

    # Build: branch -> { (year, sem): [link, link, ...] }, sorted, with
    # electives grouped under their slot name within each term.
    structure = []
    for branch in branches:
        links = BranchSubject.query.filter_by(branch_id=branch.id).join(Subject).order_by(
            Subject.subject_code
        ).all()

        terms = {}
        for link in links:
            key = (link.academic_year, link.semester_number)
            terms.setdefault(key, {"core": [], "electives": {}})
            if link.elective_group:
                terms[key]["electives"].setdefault(link.elective_group, []).append(link)
            else:
                terms[key]["core"].append(link)

        sorted_terms = [
            {
                "year": yr, "semester": sem, "roman": f"{['', 'I', 'II', 'III', 'IV'][yr]}-{['', 'I', 'II'][sem]}",
                "core": data["core"],
                "electives": data["electives"],
            }
            for (yr, sem), data in sorted(terms.items())
        ]

        structure.append({"branch": branch, "terms": sorted_terms})

    return render_template('admin_subjects.html', structure=structure)


@app.route('/api/search-subjects', methods=['GET'])
def api_search_subjects():
    """Free-text search across subject name/code, optionally narrowed by
    branch_id / academic_year / semester_number. Used by the generator
    page's search box."""
    q = request.args.get('q', '').strip()
    branch_id = request.args.get('branch_id', type=int)
    academic_year = request.args.get('academic_year', type=int)
    semester_number = request.args.get('semester_number', type=int)

    query = BranchSubject.query.join(Subject)

    if branch_id:
        query = query.filter(BranchSubject.branch_id == branch_id)
    if academic_year:
        query = query.filter(BranchSubject.academic_year == academic_year)
    if semester_number:
        query = query.filter(BranchSubject.semester_number == semester_number)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Subject.subject_name.ilike(like), Subject.subject_code.ilike(like))
        )

    links = query.order_by(Subject.subject_code).limit(50).all()
    seen_ids = set()
    unique_links = []
    for link in links:
        if link.subject_id not in seen_ids:
            seen_ids.add(link.subject_id)
            unique_links.append(link)
    links = unique_links

    return jsonify([
        {
            "id": link.subject.id,
            "subject_code": link.subject.subject_code,
            "subject_name": link.subject.subject_name,
            "code_pending": link.subject.code_pending,
            "academic_year": link.academic_year,
            "semester_number": link.semester_number,
            "term": link.get_roman_term(),
            "elective_group": link.elective_group,
            "branch_code": link.branch.branch_code,
        }
        for link in links
    ])



@app.route('/admin/bulk', methods=['GET'])
@login_required
def admin_bulk_page():
    subjects = Subject.query.order_by(Subject.subject_code).all()
    units = Unit.query.order_by(Unit.unit_number).all()
    assign_pending = AssignmentQuestion.query.filter_by(is_pending=True).order_by(AssignmentQuestion.id.desc()).all()
    return render_template('admin_bulk.html',
        subjects=subjects, units=units, assign_pending=assign_pending)


@app.route('/questions/assign-approve/<int:qid>', methods=['POST'])
@login_required
def assign_approve(qid):
    q = AssignmentQuestion.query.get_or_404(qid)
    q.is_pending = False
    q.is_active = True
    db.session.commit()
    flash(f'Question approved.')
    return redirect(url_for('admin_bulk_page'))


@app.route('/questions/assign-reject/<int:qid>', methods=['POST'])
@login_required
def assign_reject(qid):
    q = AssignmentQuestion.query.get_or_404(qid)
    db.session.delete(q)
    db.session.commit()
    flash(f'Question rejected and deleted.')
    return redirect(url_for('admin_bulk_page'))


@app.route('/questions/assign-approve-all', methods=['POST'])
@login_required
def assign_approve_all():
    pending = AssignmentQuestion.query.filter_by(is_pending=True).all()
    for q in pending:
        q.is_pending = False
        q.is_active = True
    db.session.commit()
    flash(f'Approved {len(pending)} assignment questions.')
    return redirect(url_for('admin_bulk_page'))


@app.route('/questions', methods=['GET'])
def view_questions():
    part_a_count = PartAQuestion.query.count()
    group_count = QuestionGroup.query.count()
    mid_obj_count = MidObjectiveQuestion.query.filter_by(is_active=True).count()
    pending = PendingQuestion.query.filter_by(status='pending').order_by(PendingQuestion.id.desc()).all()
    mid_obj_pending = MidObjectiveQuestion.query.filter_by(is_pending=True).order_by(MidObjectiveQuestion.id.desc()).all()
    assign_pending = AssignmentQuestion.query.filter_by(is_pending=True, is_active=False).order_by(AssignmentQuestion.id.desc()).all()

    branches = Branch.query.order_by(Branch.branch_name).all()
    subjects = Subject.query.order_by(Subject.subject_code).all()
    units = Unit.query.order_by(Unit.unit_number).all()

    return render_template(
        'questions.html',
        part_a_count=part_a_count,
        group_count=group_count,
        mid_obj_count=mid_obj_count,
        pending=pending,
        mid_obj_pending=mid_obj_pending,
        assign_pending=assign_pending,
        branches=branches,
        subjects=subjects,
        units=units,
    )


# ----------------------------------------------------------------------
# PART A — ADD QUESTION
# ----------------------------------------------------------------------
@app.route('/questions/add-part-a', methods=['POST'])
def add_part_a_question():
    try:
        new_q = PartAQuestion(
            subject_id=int(request.form['subject_id']),
            unit_id=int(request.form['unit_id']),
            question_text=request.form['question_text'],
            bloom_level=request.form.get('bloom_level', 'Remember')
        )
        db.session.add(new_q)
        db.session.commit()
        flash('Part-A question added.')
        return redirect(url_for('view_questions'))
    except Exception as e:
        flash(f'Could not add question: {str(e)}')
        return redirect(url_for('view_questions'))


# ----------------------------------------------------------------------
# PART B — ADD QUESTION GROUP (Single or Compound)
# ----------------------------------------------------------------------
@app.route('/questions/add-group', methods=['POST'])
def add_question_group():
    """
    Expects form data:
      subject_id, unit_id, question_type ('Single' or 'Compound'), difficulty
      For Single:   part_a_text, part_a_marks
      For Compound: part_a_text, part_a_marks, part_b_text, part_b_marks
    """
    try:
        question_type = request.form['question_type']  # 'Single' or 'Compound'

        if question_type == 'Single':
            total_marks = int(request.form['part_a_marks'])
        else:
            total_marks = int(request.form['part_a_marks']) + int(request.form['part_b_marks'])

        new_group = QuestionGroup(
            subject_id=int(request.form['subject_id']),
            unit_id=int(request.form['unit_id']),
            total_marks=total_marks,
            difficulty=request.form.get('difficulty', 'Medium'),
            question_type=question_type
        )
        db.session.add(new_group)
        db.session.flush()  # get new_group.id before commit

        if question_type == 'Single':
            part = QuestionPart(
                group_id=new_group.id,
                part_label=None,
                part_order=1,
                question_text=request.form['part_a_text'],
                marks=int(request.form['part_a_marks']),
                bloom_level=request.form.get('part_a_bloom', 'Understand')
            )
            db.session.add(part)
        else:
            part_a = QuestionPart(
                group_id=new_group.id,
                part_label='a',
                part_order=1,
                question_text=request.form['part_a_text'],
                marks=int(request.form['part_a_marks']),
                bloom_level=request.form.get('part_a_bloom', 'Understand')
            )
            part_b = QuestionPart(
                group_id=new_group.id,
                part_label='b',
                part_order=2,
                question_text=request.form['part_b_text'],
                marks=int(request.form['part_b_marks']),
                bloom_level=request.form.get('part_b_bloom', 'Understand')
            )
            db.session.add(part_a)
            db.session.add(part_b)

        db.session.commit()
        flash('Question group added.')
        return redirect(url_for('view_questions'))

    except Exception as e:
        db.session.rollback()
        flash(f'Could not add question group: {str(e)}')
        return redirect(url_for('view_questions'))


@app.route('/questions/bulk-add', methods=['POST'])
def bulk_add_questions():
    """
    Manual Admin entry — lets a teacher paste several questions at once
    (typed from a syllabus/reference PDF) using the bulk text format
    documented in bulk_parser.py. Parsed questions go into PendingQuestion
    for review, using the EXACT SAME approve/reject flow as AI-generated
    questions, so nothing reaches the live question bank unreviewed.

    Supports two modes:
      - Single-unit (original): form sends unit_id, every parsed question
        goes to that unit. Works whether or not the paste used [UNIT:N]
        markers — if it did, those markers are ignored and everything
        still goes to the chosen unit_id (keeps old behavior for anyone
        not using the new marker).
      - Multi-unit: form sends NO unit_id (or it's blank). The paste MUST
        use [UNIT:N] markers, which are resolved against this subject's
        real Unit rows by unit_number. Any question with no unit_number
        (paste had no marker before it) or referencing a unit_number that
        doesn't exist for this subject is reported as an error and skipped
        — not silently dropped into the wrong unit.
    """
    try:
        subject_id = int(request.form['subject_id'])
        unit_id_raw = request.form.get('unit_id', '').strip()
        bulk_text = request.form.get('bulk_text', '')

        Subject.query.get_or_404(subject_id)

        parsed = parse_bulk_text(bulk_text)
        extra_errors = []

        if unit_id_raw:
            # Single-unit mode: every question goes to this one unit,
            # regardless of any [UNIT:N] markers in the paste.
            fixed_unit_id = int(unit_id_raw)
            Unit.query.get_or_404(fixed_unit_id)
            resolve_unit_id = lambda _unit_number: fixed_unit_id
        else:
            # Multi-unit mode: resolve each question's unit_number against
            # this subject's real units.
            units_by_number = {u.unit_number: u.id for u in Unit.query.filter_by(subject_id=subject_id).all()}
            if not units_by_number:
                return (f"This subject has no units yet — add units first "
                        f"(see seed_units.py), or pick a single unit from the "
                        f"dropdown instead of using [UNIT:N] markers.")

            def resolve_unit_id(unit_number):
                if unit_number is None:
                    extra_errors.append(
                        "A question had no [UNIT:N] marker before it, and no "
                        "single unit was selected — skipped."
                    )
                    return None
                if unit_number not in units_by_number:
                    extra_errors.append(
                        f"[UNIT:{unit_number}] doesn't exist for this subject "
                        f"(has units {sorted(units_by_number)}) — its questions were skipped."
                    )
                    return None
                return units_by_number[unit_number]

        added_count = 0

        for pa in parsed['part_a']:
            target_unit_id = resolve_unit_id(pa.pop('unit_number'))
            if target_unit_id is None:
                continue
            db.session.add(PendingQuestion(
                subject_id=subject_id,
                unit_id=target_unit_id,
                question_kind='part_a',
                payload_json=pa,
                topics_text='(manually entered via bulk-add)',
                raw_ai_response=None,
            ))
            added_count += 1

        for grp in parsed['groups']:
            target_unit_id = resolve_unit_id(grp.pop('unit_number'))
            if target_unit_id is None:
                continue
            db.session.add(PendingQuestion(
                subject_id=subject_id,
                unit_id=target_unit_id,
                question_kind='group',
                payload_json=grp,
                topics_text='(manually entered via bulk-add)',
                raw_ai_response=None,
            ))
            added_count += 1

        db.session.commit()

        all_errors = parsed['errors'] + extra_errors
        error_count = len(all_errors)

        message = f"Imported {added_count} question(s) for review."
        if error_count:
            message += f" {error_count} line(s) had issues and were skipped: " + " | ".join(all_errors)

        flash(message)
        return redirect(url_for('view_questions'))

    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for('view_questions'))


# ----------------------------------------------------------------------
# AI GENERATION (Gemini) — creates PendingQuestion rows for review
# ----------------------------------------------------------------------
def _approve_one_pending(pending):
    """
    Copies a PendingQuestion's payload into PartAQuestion or
    QuestionGroup+QuestionPart, and marks it approved. Does NOT commit —
    caller is responsible for committing (so bulk-approve can do all
    inserts in one transaction instead of one per question).
    Raises on unknown question_kind or malformed payload; caller decides
    whether to roll back the whole batch or skip just this one.
    """
    data = pending.payload_json

    if pending.question_kind == 'part_a':
        new_q = PartAQuestion(
            subject_id=pending.subject_id,
            unit_id=pending.unit_id,
            question_text=data['question_text'],
            bloom_level=data.get('bloom_level', 'Remember'),
        )
        db.session.add(new_q)

    elif pending.question_kind == 'group':
        total_marks = sum(p['marks'] for p in data['parts'])
        new_group = QuestionGroup(
            subject_id=pending.subject_id,
            unit_id=pending.unit_id,
            total_marks=total_marks,
            difficulty=data.get('difficulty', 'Medium'),
            question_type=data.get('question_type', 'Single'),
        )
        db.session.add(new_group)
        db.session.flush()  # get new_group.id before adding parts

        for p in data['parts']:
            db.session.add(QuestionPart(
                group_id=new_group.id,
                part_label=p.get('part_label'),
                part_order=p.get('part_order', 1),
                question_text=p['question_text'],
                marks=p['marks'],
                bloom_level=p.get('bloom_level', 'Understand'),
            ))
    else:
        raise ValueError(f"Unknown question_kind: {pending.question_kind}")

    pending.status = 'approved'


@app.route('/questions/pending/<int:pending_id>/approve', methods=['POST'])
def approve_pending_question(pending_id):
    """Approves a single pending question (kept for cases where someone
    wants to approve one at a time, or reject a specific one after a
    bulk-approve pass)."""
    pending = PendingQuestion.query.get_or_404(pending_id)
    try:
        _approve_one_pending(pending)
        db.session.commit()
        flash('Question approved.')
    except Exception as e:
        db.session.rollback()
        flash(f'Could not approve: {str(e)}')
    return redirect(url_for('view_questions'))


@app.route('/questions/pending/approve-all', methods=['POST'])
def approve_all_pending_questions():
    """
    Approves every currently-pending question in ONE request and ONE
    database commit — built for the bulk-paste workflow, where a single
    subject's import can produce 50+ pending rows and approving them one
    at a time (each its own page load) isn't practical.

    If any single question's payload is malformed, that one is skipped
    (logged in the response) and the rest still go through — one bad row
    shouldn't block approving everything else in the batch.
    """
    pending_list = PendingQuestion.query.filter_by(status='pending').all()

    if not pending_list:
        flash('Nothing to approve.')
        return redirect(url_for('view_questions'))

    approved_count = 0
    skipped = []

    for pending in pending_list:
        try:
            _approve_one_pending(pending)
            approved_count += 1
        except Exception as e:
            skipped.append(f"Pending #{pending.id}: {str(e)}")

    db.session.commit()

    message = f"Approved {approved_count} question(s)."
    if skipped:
        message += f" {len(skipped)} skipped due to errors: " + "; ".join(skipped)

    flash(message)
    return redirect(url_for('view_questions'))


@app.route('/questions/pending/reject-all', methods=['POST'])
def reject_all_pending_questions():
    """Rejects every currently-pending question in one request."""
    pending_list = PendingQuestion.query.filter_by(status='pending').all()

    if not pending_list:
        flash('Nothing to reject.')
        return redirect(url_for('view_questions'))

    count = len(pending_list)
    for pending in pending_list:
        pending.status = 'rejected'

    db.session.commit()
    flash(f'Rejected {count} question(s).')
    return redirect(url_for('view_questions'))


@app.route('/questions/pending/<int:pending_id>/reject', methods=['POST'])
def reject_pending_question(pending_id):
    pending = PendingQuestion.query.get_or_404(pending_id)
    pending.status = 'rejected'
    db.session.commit()
    flash('Question rejected.')
    return redirect(url_for('view_questions'))


# ----------------------------------------------------------------------
# PAPER GENERATION
# ----------------------------------------------------------------------
@app.route('/generate', methods=['POST'])
@csrf.exempt
def generate_paper_route():
    data = request.json or {}
    subject_code = data.get('subject_code')
    selected_unit_ids = data.get('unit_ids')      # optional list of Unit.id
    difficulty = data.get('difficulty')            # optional 'Easy'/'Medium'/'Hard'/'Mixed'

    if not subject_code:
        return jsonify({"success": False, "error": "subject_code is required"}), 400

    result = generate_paper(subject_code, selected_unit_ids=selected_unit_ids, difficulty=difficulty)
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route('/swap', methods=['POST'])
@csrf.exempt
def swap_route():
    """
    Expects JSON: { "paper_id": 1, "slot_position": 2, "side": "primary" }
    """
    data = request.json
    result = swap_question_group(
        paper_id=data.get('paper_id'),
        slot_position=data.get('slot_position'),
        side=data.get('side')
    )
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route('/export-pdf/<int:paper_id>', methods=['GET'])
def export_pdf_route(paper_id):
    """
    Rebuilds the paper data from the DB (so it reflects any swaps made)
    and renders it into a PDF matching your college's layout.

    Accepts the person-entered "Format Paper" details as query params —
    these are things the app has no way to know on its own (which exact
    exam sitting this is, the Set number, the Regulation, etc. are decided
    by the exam cell at publish time, not at generation time):

        ?regulation=R22&set_number=1&branch=COMMON+TO+ALL
        &academic_year_label=I&semester_label=II&exam_session=Regular/Supplementary
        &exam_month_year=July+2024&academic_year_range=2023-24

    All are optional — sensible defaults are used for anything not given,
    so an old bookmarked link or a direct GET still produces a valid PDF.
    """
    paper_data = get_paper_data_for_export(paper_id)

    if not paper_data.get("success"):
        return jsonify(paper_data), 404

    output_path = f"output/paper_{paper_id}.pdf"
    render_paper_pdf(
        paper_data, output_path=output_path,
        regulation=request.args.get('regulation', 'R22'),
        set_number=request.args.get('set_number', '1'),
        branch=request.args.get('branch', 'COMMON TO ALL'),
        academic_year_label=request.args.get('academic_year_label', 'I'),
        semester_label=request.args.get('semester_label', 'I'),
        exam_session=request.args.get('exam_session', 'Regular/Supplementary'),
        exam_month_year=request.args.get('exam_month_year', ''),
        academic_year_range=request.args.get('academic_year_range', ''),
    )

    return send_file(output_path, as_attachment=True, download_name=f"question_paper_{paper_id}.pdf")


# ----------------------------------------------------------------------
# IMPORTANT QUESTIONS — public, no-login lookup for teachers/students.
# Ranks each subject's questions by usage_count (how often they've been
# picked into generated exam papers) as a proxy for "important", since
# that reflects real exam-paper history rather than a manual flag.
# ----------------------------------------------------------------------
@app.route('/important-questions', methods=['GET'])
def important_questions_page():
    """Renders the lookup page shell. Subject search and question loading
    happen client-side via /api/search-subjects and /api/important-questions,
    same pattern as the generator page."""
    return render_template('important_questions.html')


@app.route('/api/important-questions', methods=['GET'])
def api_important_questions():
    """
    ?subject_code=A2501[&unit_id=3][&limit_per_unit=5]
    Returns ranked Part-A and Question-Group data for the subject, grouped
    by unit. See generator.get_important_questions() for the ranking logic.
    """
    subject_code = request.args.get('subject_code')
    unit_id = request.args.get('unit_id', type=int)
    limit_per_unit = request.args.get('limit_per_unit', type=int)

    if not subject_code:
        return jsonify({"success": False, "error": "subject_code is required"}), 400

    result = get_important_questions(subject_code, unit_id=unit_id, limit_per_unit=limit_per_unit)
    status_code = 200 if result.get("success") else 404
    return jsonify(result), status_code


@app.route('/important-questions/export-pdf', methods=['POST'])
@csrf.exempt
def export_important_questions_pdf():
    """
    Expects JSON: {
      "subject_code": "A2501",
      "part_a_ids": [1, 2, 5],       // PartAQuestion.id values the teacher selected
      "group_ids": [11, 14]          // QuestionGroup.id values the teacher selected
    }
    Renders ONLY the selected questions (not the whole ranked list) into a
    study-sheet style PDF — no marks-allocation header, no OR-pairs, just
    a clean per-unit list a teacher can hand to students.
    """
    data = request.json or {}
    subject_code = data.get('subject_code')
    part_a_ids = data.get('part_a_ids') or []
    group_ids = data.get('group_ids') or []

    if not subject_code:
        return jsonify({"success": False, "error": "subject_code is required"}), 400
    if not part_a_ids and not group_ids:
        return jsonify({"success": False, "error": "Select at least one question first."}), 400

    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return jsonify({"success": False, "error": f"Subject '{subject_code}' not found."}), 404

    part_a_questions = PartAQuestion.query.filter(
        PartAQuestion.id.in_(part_a_ids), PartAQuestion.subject_id == subject.id
    ).all()
    groups = QuestionGroup.query.filter(
        QuestionGroup.id.in_(group_ids), QuestionGroup.subject_id == subject.id
    ).all()

    # Group everything by unit for a clean per-unit layout in the PDF
    units_by_id = {u.id: u for u in Unit.query.filter_by(subject_id=subject.id).all()}
    by_unit = {}
    for q in part_a_questions:
        by_unit.setdefault(q.unit_id, {"part_a": [], "groups": []})["part_a"].append(q)
    for g in groups:
        by_unit.setdefault(g.unit_id, {"part_a": [], "groups": []})["groups"].append(g)

    pdf_data = {
        "subject_name": subject.subject_name,
        "subject_code": subject.subject_code,
        "units": [
            {
                "unit_name": units_by_id[uid].unit_name if uid in units_by_id else "Unit",
                "part_a": [{"text": q.question_text, "bloom": q.bloom_level} for q in bucket["part_a"]],
                "groups": [_group_to_pdf_dict(g) for g in bucket["groups"]],
            }
            for uid, bucket in by_unit.items()
        ],
    }

    output_path = f"output/important_questions_{subject.subject_code}.pdf"
    render_important_questions_pdf(pdf_data, output_path=output_path)

    return send_file(
        output_path, as_attachment=True,
        download_name=f"important_questions_{subject.subject_code}.pdf"
    )


def _group_to_pdf_dict(group):
    return {
        "total_marks": group.total_marks,
        "question_type": group.question_type,
        "parts": [
            {"label": p.part_label, "text": p.question_text, "marks": p.marks, "bloom": p.bloom_level}
            for p in group.parts
        ],
    }


@app.route('/questions/mid-bulk-add', methods=['POST'])
def mid_bulk_add_questions():
    """
    Bulk import for mid exam objective questions (MCQ + FIB).
    Format (pipe-separated):
      [MCQ]
      Question text | A | B | C | D | correct_letter | bloom | unit_number
      [FIB]
      Question text ____. | answer | bloom | unit_number
    """
    try:
        subject_id = int(request.form['subject_id'])
        bulk_text = request.form.get('bulk_text', '').strip()
        subject = Subject.query.get_or_404(subject_id)
        units_by_number = {u.unit_number: u.id for u in Unit.query.filter_by(subject_id=subject_id).all()}

        lines = bulk_text.splitlines()
        current_section = None
        added = 0
        errors = []

        VALID_BLOOM = {"Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"}

        def norm_bloom(raw, default="Remember"):
            if not raw:
                return default
            raw = raw.strip()
            for b in VALID_BLOOM:
                if raw.lower() == b.lower():
                    return b
            return default

        current_unit_override = None  # set by [UNIT:N] block markers

        for i, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line:
                continue
            # skip comment lines
            if line.startswith('#') or line.startswith('//') or set(line) <= set('=-~*'):
                continue
            upper = line.upper()
            # [UNIT:N] block marker — sets sticky unit for following lines
            if upper.startswith('[UNIT:') and line.endswith(']'):
                num_part = line[6:-1].strip()
                try:
                    current_unit_override = int(num_part)
                except ValueError:
                    errors.append(f"Line {i}: bad unit marker '{line}' — ignored.")
                continue
            if upper in ('[MCQ]', '[MCQ-SECTION]'):
                current_section = 'mcq'
                continue
            if upper in ('[FIB]', '[FILL]', '[FILL-IN-BLANK]'):
                current_section = 'fib'
                continue
            if line.startswith('[') and line.endswith(']'):
                errors.append(f"Line {i}: unknown section '{line}' — skipped.")
                continue
            if current_section is None:
                errors.append(f"Line {i}: text before section header — skipped.")
                continue

            fields = [f.strip() for f in line.split('|')]

            if current_section == 'mcq':
                # text | A | B | C | D | correct | bloom | unit_no
                if len(fields) < 6 or not fields[0]:
                    errors.append(f"Line {i}: MCQ needs 'text|A|B|C|D|correct[|bloom|unit]' — skipped.")
                    continue
                q_text = fields[0]
                opt_a = fields[1] if len(fields) > 1 else ''
                opt_b = fields[2] if len(fields) > 2 else ''
                opt_c = fields[3] if len(fields) > 3 else ''
                opt_d = fields[4] if len(fields) > 4 else ''
                correct = fields[5].strip().upper() if len(fields) > 5 else ''
                if correct not in ('A', 'B', 'C', 'D'):
                    errors.append(f"Line {i}: correct_answer '{correct[:20]}' not A/B/C/D — check field count (need: text|A|B|C|D|letter|bloom) — skipped.")
                    continue
                bloom = norm_bloom(fields[6] if len(fields) > 6 else None)
                unit_no_raw = fields[7].strip() if len(fields) > 7 else ''
                try:
                    unit_no = int(unit_no_raw)
                except (ValueError, TypeError):
                    unit_no = current_unit_override
                unit_id = units_by_number.get(unit_no) if unit_no else None
                if unit_id is None:
                    errors.append(f"Line {i}: unit {unit_no_raw!r} not found — skipped.")
                    continue
                db.session.add(MidObjectiveQuestion(
                    subject_id=subject_id, unit_id=unit_id,
                    question_type='mcq', question_text=q_text,
                    option_a=opt_a, option_b=opt_b, option_c=opt_c, option_d=opt_d,
                    correct_answer=correct, bloom_level=bloom,
                    is_active=False, is_pending=True,
                ))
                added += 1

            elif current_section == 'fib':
                # text (with ____ blank) | answer | bloom | unit_no
                if len(fields) < 2 or not fields[0]:
                    errors.append(f"Line {i}: FIB needs 'text|answer[|bloom|unit]' — skipped.")
                    continue
                q_text = fields[0]
                answer = fields[1]
                bloom = norm_bloom(fields[2] if len(fields) > 2 else None)
                unit_no_raw = fields[3].strip() if len(fields) > 3 else ''
                try:
                    unit_no = int(unit_no_raw)
                except (ValueError, TypeError):
                    unit_no = current_unit_override
                unit_id = units_by_number.get(unit_no) if unit_no else None
                if unit_id is None:
                    errors.append(f"Line {i}: unit {unit_no_raw!r} not found — skipped.")
                    continue
                db.session.add(MidObjectiveQuestion(
                    subject_id=subject_id, unit_id=unit_id,
                    question_type='fib', question_text=q_text,
                    answer_text=answer, bloom_level=bloom,
                    is_active=False, is_pending=True,
                ))
                added += 1

        db.session.commit()
        msg = f"Imported {added} mid objective question(s)."
        if errors:
            msg += f" {len(errors)} skipped: " + " | ".join(errors)
        flash(msg)
        return redirect(url_for('view_questions'))

    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}")
        return redirect(url_for('view_questions'))


# mid_subjective_bulk_add route REMOVED — Part-B now uses QuestionGroup bank.



# -----------------------------------------------------------------------
# MID OBJECTIVE PENDING REVIEW ROUTES
# -----------------------------------------------------------------------
@app.route('/questions/mid-objectives/pending')
def mid_obj_pending():
    pending = MidObjectiveQuestion.query.filter_by(is_pending=True).order_by(MidObjectiveQuestion.created_at.desc()).all()
    return render_template('mid_obj_pending.html', pending=pending)

@app.route('/questions/mid-objectives/<int:qid>/approve', methods=['POST'])
def mid_obj_approve(qid):
    q = MidObjectiveQuestion.query.get_or_404(qid)
    q.is_pending = False
    q.is_active = True
    db.session.commit()
    flash(f'Question #{qid} approved.')
    return redirect(url_for('view_questions') + '#mid-obj-tab')

@app.route('/questions/mid-objectives/<int:qid>/reject', methods=['POST'])
def mid_obj_reject(qid):
    q = MidObjectiveQuestion.query.get_or_404(qid)
    db.session.delete(q)
    db.session.commit()
    flash(f'Question #{qid} rejected and deleted.')
    return redirect(url_for('view_questions') + '#mid-obj-tab')

@app.route('/questions/mid-objectives/approve-all', methods=['POST'])
def mid_obj_approve_all():
    subject_id = request.form.get('subject_id', type=int)
    q = MidObjectiveQuestion.query.filter_by(is_pending=True)
    if subject_id:
        q = q.filter_by(subject_id=subject_id)
    count = 0
    for obj in q.all():
        obj.is_pending = False
        obj.is_active = True
        count += 1
    db.session.commit()
    flash(f'Approved {count} mid objective questions.')
    return redirect(url_for('view_questions') + '#mid-obj-tab')

@app.route('/questions/mid-objectives/reject-all', methods=['POST'])
def mid_obj_reject_all():
    subject_id = request.form.get('subject_id', type=int)
    q = MidObjectiveQuestion.query.filter_by(is_pending=True)
    if subject_id:
        q = q.filter_by(subject_id=subject_id)
    count = q.count()
    q.delete()
    db.session.commit()
    flash(f'Rejected and deleted {count} mid objective questions.')
    return redirect(url_for('view_questions') + '#mid-obj-tab')

# ======================================================================
# MID EXAM ROUTES
# ======================================================================

@app.route('/api/mid-objectives', methods=['GET'])
def api_mid_objectives():
    """List mid objective questions for a subject+unit."""
    subject_code = request.args.get('subject_code')
    unit_id = request.args.get('unit_id', type=int)
    q_type = request.args.get('question_type')   # 'mcq' or 'fib'

    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return jsonify({"success": False, "error": "Subject not found"}), 404

    q = MidObjectiveQuestion.query.filter_by(subject_id=subject.id, is_active=True)
    if unit_id:
        q = q.filter_by(unit_id=unit_id)
    if q_type:
        q = q.filter_by(question_type=q_type)
    questions = q.all()

    return jsonify({
        "success": True,
        "questions": [
            {"id": x.id, "text": x.question_text, "type": x.question_type,
             "unit_id": x.unit_id, "bloom": x.bloom_level, "usage_count": x.usage_count}
            for x in questions
        ]
    })


@app.route('/api/mid-objectives/add', methods=['POST'])
@csrf.exempt
def add_mid_objective():
    """Add a mid exam objective question (MCQ or FIB)."""
    data = request.json or {}
    subject = Subject.query.filter_by(subject_code=data.get('subject_code')).first()
    if not subject:
        return jsonify({"success": False, "error": "Subject not found"}), 404

    unit = Unit.query.filter_by(subject_id=subject.id, unit_number=data.get('unit_number')).first()
    if not unit:
        return jsonify({"success": False, "error": "Unit not found"}), 404

    q = MidObjectiveQuestion(
        subject_id=subject.id,
        unit_id=unit.id,
        question_type=data.get('question_type', 'mcq'),  # 'mcq' or 'fib'
        question_text=data['question_text'],
        option_a=data.get('option_a'),
        option_b=data.get('option_b'),
        option_c=data.get('option_c'),
        option_d=data.get('option_d'),
        correct_answer=data.get('correct_answer'),
        answer_text=data.get('answer_text'),
        bloom_level=data.get('bloom_level', 'Remember'),
    )
    db.session.add(q)
    db.session.commit()
    return jsonify({"success": True, "id": q.id})


# add_mid_subjective route REMOVED — Part-B now uses QuestionGroup bank.


@app.route('/generate-mid', methods=['POST'])
@csrf.exempt
def generate_mid_paper_route():
    """Generate a mid exam paper (mid_number=1 or 2)."""
    data = request.json or {}
    subject_code = data.get('subject_code')
    mid_number = int(data.get('mid_number', 1))
    difficulty = data.get('difficulty')

    if not subject_code:
        return jsonify({"success": False, "error": "subject_code required"}), 400
    if mid_number not in (1, 2):
        return jsonify({"success": False, "error": "mid_number must be 1 or 2"}), 400

    result = generate_mid_paper(subject_code, mid_number=mid_number, difficulty=difficulty)
    return jsonify(result), 200 if result.get("success") else 400


@app.route('/mid-paper/<int:paper_id>')
def view_mid_paper(paper_id):
    paper_data = get_mid_paper_data_for_export(paper_id)
    if not paper_data.get('success'):
        return "Mid paper not found", 404
    return render_template('mid_paper.html', paper=paper_data)


@app.route('/export-mid-pdf/<int:paper_id>', methods=['GET'])
def export_mid_pdf_route(paper_id):
    """Export a mid exam paper as PDF."""
    paper_data = get_mid_paper_data_for_export(paper_id)
    if not paper_data.get("success"):
        return jsonify(paper_data), 404

    output_path = f"output/mid_paper_{paper_id}.pdf"
    render_mid_paper_pdf(
        paper_data, output_path=output_path,
        regulation=request.args.get('regulation', 'R22'),
        set_number=request.args.get('set_number', '1'),
        branch=request.args.get('branch', 'COMMON TO ALL'),
        academic_year_label=request.args.get('academic_year_label', 'I'),
        semester_label=request.args.get('semester_label', 'I'),
        exam_session=request.args.get('exam_session', 'Regular'),
        exam_month_year=request.args.get('exam_month_year', ''),
        academic_year_range=request.args.get('academic_year_range', ''),
    )
    return send_file(output_path, as_attachment=True,
                     download_name=f"mid{paper_data['mid_number']}_paper_{paper_id}.pdf")

@app.route('/export-mid-objective-pdf/<int:paper_id>', methods=['GET'])
def export_mid_objective_pdf_route(paper_id):
    """Export only Part-A (objective). Add ?key=1 for answer key version."""
    from pdf_generator import render_mid_objective_pdf
    paper_data = get_mid_paper_data_for_export(paper_id)
    if not paper_data.get('success'):
        return jsonify(paper_data), 404
    show_key = request.args.get('key', '0') == '1'
    suffix = '_KEY' if show_key else ''
    output_path = f'output/mid_objective_{paper_id}{suffix}.pdf'
    render_mid_objective_pdf(paper_data, output_path=output_path, show_key=show_key)
    fname = f'mid{paper_data["mid_number"]}_objective{suffix}_{paper_id}.pdf'
    return send_file(output_path, as_attachment=True, download_name=fname)


@app.route('/export-mid-subjective-pdf/<int:paper_id>', methods=['GET'])
def export_mid_subjective_pdf_route(paper_id):
    """Export only Part-B (subjective) of a mid exam as PDF."""
    from pdf_generator import render_mid_subjective_pdf
    paper_data = get_mid_paper_data_for_export(paper_id)
    if not paper_data.get('success'):
        return jsonify(paper_data), 404
    output_path = f'output/mid_subjective_{paper_id}.pdf'
    render_mid_subjective_pdf(paper_data, output_path=output_path)
    return send_file(output_path, as_attachment=True,
                     download_name=f'mid{paper_data["mid_number"]}_subjective_{paper_id}.pdf')


@app.route('/api/mid-stats', methods=['GET'])
def mid_question_stats():
    """Count mid objective/subjective questions per subject."""
    subject_code = request.args.get('subject_code')
    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return jsonify({"success": False, "error": "Subject not found"}), 404

    units = Unit.query.filter_by(subject_id=subject.id).order_by(Unit.unit_number).all()
    stats = []
    for u in units:
        mcq_count = MidObjectiveQuestion.query.filter_by(
            unit_id=u.id, question_type='mcq', is_active=True).count()
        fib_count = MidObjectiveQuestion.query.filter_by(
            unit_id=u.id, question_type='fib', is_active=True).count()
        group_count = QuestionGroup.query.filter_by(
            unit_id=u.id, is_active=True).count()
        stats.append({
            "unit_number": u.unit_number,
            "unit_name": u.unit_name,
            "mcq": mcq_count,
            "fib": fib_count,
            "question_groups": group_count,
        })
    return jsonify({"success": True, "subject": subject.subject_name, "units": stats})


# ══════════════════════════════════════════════════════════════════════
#  ASSIGNMENTS
# ══════════════════════════════════════════════════════════════════════


@app.route('/assignments', methods=['GET'])
@login_required
def assignments_page():
    """Assignment generator landing — same subject selector as generator."""
    subjects = Subject.query.order_by(Subject.subject_name).all()
    recent = GeneratedAssignment.query.order_by(GeneratedAssignment.generated_at.desc()).limit(50).all()
    return render_template('assignments.html', subjects=subjects,
                           assignment_types=ASSIGNMENT_TYPES, recent_assignments=recent)


@app.route('/api/course-outcomes', methods=['GET'])
@login_required
def api_course_outcomes():
    subject_code = request.args.get('subject_code')
    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return jsonify({'success': False, 'error': 'Subject not found'}), 404
    cos = CourseOutcome.query.filter_by(subject_id=subject.id).order_by(CourseOutcome.co_number).all()
    return jsonify({'success': True, 'course_outcomes': [
        {'co_number': c.co_number, 'statement': c.statement} for c in cos
    ]})


@app.route('/api/assignment-questions', methods=['GET'])
@login_required
def api_assignment_questions():
    subject_code = request.args.get('subject_code')
    assignment_number = request.args.get('assignment_number', type=int)
    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return jsonify({'success': False, 'error': 'Subject not found'}), 404

    q = AssignmentQuestion.query.filter_by(
        subject_id=subject.id, is_active=True
    )
    if assignment_number in (1, 2):
        q = q.filter_by(assignment_number=assignment_number)
    questions = q.all()
    return jsonify({'success': True, 'questions': [
        {
            'id': aq.id,
            'unit_number': aq.unit.unit_number if aq.unit else None,
            'question_text': aq.question_text,
            'assignment_type': aq.assignment_type,
            'co_mapping': aq.co_mapping,
            'bloom_level': aq.bloom_level,
            'marks': aq.marks,
        } for aq in questions
    ]})


@app.route('/generate-assignment', methods=['POST'])
@csrf.exempt
@login_required
def generate_assignment_route():
    data = request.get_json()
    subject_code = data.get('subject_code')
    assignment_number = int(data.get('assignment_number', 1))
    question_count = max(5, min(20, int(data.get('question_count', 5))))
    preferred_types = data.get('assignment_types', [])  # optional filter

    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return jsonify({'success': False, 'error': 'Subject not found'}), 404

    # assignment_number=0 means both 1 and 2
    def _build_pool(assign_num):
        q = AssignmentQuestion.query.filter_by(
            subject_id=subject.id,
            is_active=True,
            is_pending=False,
        )
        if assign_num in (1, 2):
            q = q.filter_by(assignment_number=assign_num)
        if preferred_types:
            q = q.filter(AssignmentQuestion.assignment_type.in_(preferred_types))
        pool = q.order_by(AssignmentQuestion.usage_count.asc()).all()
        if not pool:
            # fallback ignore type filter
            fb = AssignmentQuestion.query.filter_by(
                subject_id=subject.id,
                is_active=True,
                is_pending=False,
            )
            if assign_num in (1, 2):
                fb = fb.filter_by(assignment_number=assign_num)
            pool = fb.order_by(AssignmentQuestion.usage_count.asc()).all()
        return pool

    if assignment_number == 0:
        pool1 = _build_pool(1)
        pool2 = _build_pool(2)
        pool = pool1 + pool2
    else:
        pool = _build_pool(assignment_number)

    if not pool:
        return jsonify({'success': False, 'error': 'No assignment questions found. Add questions first.'}), 400

    import random
    selected = pool[:question_count]
    random.shuffle(selected)

    # bump usage counts
    for aq in selected:
        aq.usage_count += 1

    ga = GeneratedAssignment(
        subject_id=subject.id,
        assignment_number=assignment_number,
        question_count=question_count,
        question_ids=[aq.id for aq in selected],
    )
    db.session.add(ga)
    db.session.commit()

    cos = CourseOutcome.query.filter_by(subject_id=subject.id).order_by(CourseOutcome.co_number).all()

    return jsonify({
        'success': True,
        'assignment_id': ga.id,
        'assignment_number': assignment_number,
        'subject_name': subject.subject_name,
        'subject_code': subject.subject_code,
        'questions': [
            {
                'id': aq.id,
                'sno': i + 1,
                'unit_number': aq.unit.unit_number if aq.unit else None,
                'question_text': aq.question_text,
                'assignment_type': aq.assignment_type,
                'co_mapping': aq.co_mapping,
                'marks': aq.marks,
            } for i, aq in enumerate(selected)
        ],
        'course_outcomes': [
            {'co_number': c.co_number, 'statement': c.statement} for c in cos
        ],
    })


@app.route('/assignments/history')
@login_required
def assignments_history():
    """List all generated assignments, newest first."""
    records = GeneratedAssignment.query.order_by(GeneratedAssignment.generated_at.desc()).limit(100).all()
    return render_template('assignments_history.html', records=records)


@app.route('/assignment/<int:assignment_id>')
@login_required
def view_assignment(assignment_id):
    ga = GeneratedAssignment.query.get_or_404(assignment_id)
    questions = [AssignmentQuestion.query.get(qid) for qid in ga.question_ids]
    questions = [q for q in questions if q]
    cos = CourseOutcome.query.filter_by(subject_id=ga.subject_id).order_by(CourseOutcome.co_number).all()
    return render_template('view_assignment.html', ga=ga, questions=questions, course_outcomes=cos)


@app.route('/export-assignment-pdf/<int:assignment_id>', methods=['GET'])
@login_required
def export_assignment_pdf(assignment_id):
    from pdf_generator import render_assignment_pdf
    ga = GeneratedAssignment.query.get_or_404(assignment_id)
    questions = [AssignmentQuestion.query.get(qid) for qid in ga.question_ids]
    questions = [q for q in questions if q]
    cos = CourseOutcome.query.filter_by(subject_id=ga.subject_id).order_by(CourseOutcome.co_number).all()

    paper_data = {
        'subject_name': ga.subject.subject_name,
        'subject_code': ga.subject.subject_code,
        'assignment_number': ga.assignment_number,
        'question_count': ga.question_count,
        'questions': [
            {
                'sno': i + 1,
                'unit_number': q.unit.unit_number if q.unit else '',
                'question_text': q.question_text,
                'assignment_type': q.assignment_type,
                'co_mapping': q.co_mapping or '',
                'marks': q.marks,
            } for i, q in enumerate(questions)
        ],
        'course_outcomes': [
            {'co_number': c.co_number, 'statement': c.statement} for c in cos
        ],
    }

    os.makedirs('output', exist_ok=True)
    output_path = f'output/assignment_{assignment_id}.pdf'
    render_assignment_pdf(paper_data, output_path)
    return send_file(output_path, as_attachment=True,
                     download_name=f'assignment{ga.assignment_number}_{ga.subject.subject_code}_{assignment_id}.pdf')


@app.route('/questions/assignment-bulk-add', methods=['POST'])
@csrf.exempt
@login_required
def assignment_bulk_add():
    """
    Bulk paste format (one question per line):
    [ASSIGN:1|2] question_text | type | CO1,CO2 | bloom | marks
    e.g.:
    [ASSIGN:1] Design a working prototype for a smart irrigation system | working_prototype | CO2,CO4 | Create | 10
    """
    raw = request.form.get('bulk_text', '').strip()
    subject_code = request.form.get('subject_code', '').strip()
    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return jsonify({'success': False, 'error': 'Subject not found'}), 404

    units = {u.unit_number: u for u in Unit.query.filter_by(subject_id=subject.id).all()}

    inserted = 0
    errors = []
    current_assign = 1
    current_unit = 1

    for lineno, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[ASSIGN:'):
            try:
                current_assign = int(line[8:line.index(']')])
            except Exception:
                pass
            # rest of line after ]
            rest = line[line.index(']') + 1:].strip()
            if not rest:
                continue
            line = rest
        if line.startswith('[UNIT:'):
            try:
                current_unit = int(line[6:line.index(']')])
            except Exception:
                pass
            rest = line[line.index(']') + 1:].strip()
            if not rest:
                continue
            line = rest

        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 2:
            errors.append(f"Line {lineno}: too few fields")
            continue

        question_text = parts[0]
        assign_type = parts[1] if len(parts) > 1 else 'descriptive'
        if assign_type not in ASSIGNMENT_TYPES:
            assign_type = 'descriptive'
        co_mapping = parts[2] if len(parts) > 2 else ''
        bloom_level = parts[3] if len(parts) > 3 else 'Apply'
        try:
            marks = int(parts[4]) if len(parts) > 4 else 10
        except ValueError:
            marks = 10

        unit_obj = units.get(current_unit)
        if not unit_obj:
            errors.append(f"Line {lineno}: unit {current_unit} not found")
            continue

        db.session.add(AssignmentQuestion(
            subject_id=subject.id,
            unit_id=unit_obj.id,
            assignment_number=current_assign,
            question_text=question_text,
            assignment_type=assign_type,
            co_mapping=co_mapping,
            bloom_level=bloom_level,
            marks=marks,
            is_pending=True,
            is_active=False,
        ))
        inserted += 1

    db.session.commit()
    msg = f'Imported {inserted} assignment question(s) for review.'
    if errors:
        msg += f' Errors: {len(errors)} line(s) skipped.'
    flash(msg)
    return redirect(url_for('view_questions') + '#assign-tab')

@app.route('/questions/assignment-pending/<int:qid>/approve', methods=['POST'])
@login_required
def approve_assignment_question(qid):
    q = AssignmentQuestion.query.get_or_404(qid)
    q.is_pending = False
    q.is_active = True
    db.session.commit()
    flash('Assignment question approved.')
    return redirect(url_for('view_questions') + '#assign-tab')

@app.route('/questions/assignment-pending/<int:qid>/reject', methods=['POST'])
@login_required
def reject_assignment_question(qid):
    q = AssignmentQuestion.query.get_or_404(qid)
    db.session.delete(q)
    db.session.commit()
    flash('Assignment question rejected.')
    return redirect(url_for('view_questions') + '#assign-tab')

@app.route('/questions/assignment-pending/approve-all', methods=['POST'])
@login_required
def approve_all_assignment_questions():
    pending = AssignmentQuestion.query.filter_by(is_pending=True, is_active=False).all()
    for q in pending:
        q.is_pending = False
        q.is_active = True
    db.session.commit()
    flash(f'Approved {len(pending)} assignment question(s).')
    return redirect(url_for('view_questions') + '#assign-tab')

@app.route('/questions/assignment-pending/reject-all', methods=['POST'])
@login_required
def reject_all_assignment_questions():
    pending = AssignmentQuestion.query.filter_by(is_pending=True, is_active=False).all()
    count = len(pending)
    for q in pending:
        db.session.delete(q)
    db.session.commit()
    flash(f'Rejected {count} assignment question(s).')
    return redirect(url_for('view_questions') + '#assign-tab')

# ── CO-PO MAPPING ──────────────────────────────────────────────────────────
@app.route('/co-po', methods=['GET'])
@login_required
def co_po_page():
    branches = Branch.query.order_by(Branch.branch_code).all()
    all_subjects = Subject.query.order_by(Subject.subject_name).all()
    branch_subjects = {}
    for b in branches:
        branch_subjects[b.branch_code] = sorted(
            [bs.subject for bs in b.subject_links], key=lambda s: s.subject_name
        )
    return render_template('co_po_mapping.html',
        subjects=all_subjects, branches=branches, branch_subjects=branch_subjects
    )


@app.route('/co-po/data/<subject_code>', methods=['GET'])
@login_required
def co_po_data(subject_code):
    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return jsonify({'success': False, 'error': 'Subject not found'})

    cos = CourseOutcome.query.filter_by(subject_id=subject.id).order_by(CourseOutcome.co_number).all()
    if not cos:
        return jsonify({'success': False, 'error': 'No COs found'})

    PO_COLS = ['PO1','PO2','PO3','PO4','PO5','PO6','PO7','PO8','PO9','PO10','PO11','PO12','PSO1','PSO2']

    grid = {}
    co_list = []
    for co in cos:
        # Use stored po_mapping if exists, else empty
        mapping = co.po_mapping if co.po_mapping else {po: '-' for po in PO_COLS}
        # Ensure all PO_COLS present
        for po in PO_COLS:
            if po not in mapping:
                mapping[po] = '-'
        grid[co.co_number] = mapping
        co_list.append({
            'co_number': co.co_number,
            'statement': co.statement,
            'co_avg': round(co.co_avg, 2) if co.co_avg else None
        })

    return jsonify({
        'success': True,
        'subject_name': subject.subject_name,
        'cos': co_list,
        'grid': grid
    })


@app.route('/co-po/export', methods=['POST'])
@login_required
@csrf.exempt
def co_po_export():
    import io, tempfile, os, subprocess
    data = request.get_json()
    subject_code = data.get('subject_code', '')
    subject_name = data.get('subject_name', '')
    rows = data.get('rows', [])
    fmt = data.get('format', 'word')

    PO_COLS = ['PO1','PO2','PO3','PO4','PO5','PO6','PO7','PO8','PO9','PO10','PO11','PO12','PSO1','PSO2']

    def val_color(v):
        if v == '3': return '#c6efce'
        if v == '2': return '#ffeb9c'
        if v == '1': return '#ffc7ce'
        return '#f2f2f2'

    po_headers = ''.join(f'<th style="background:#1a2340;color:#fff;padding:5px 4px;font-size:10px;min-width:32px;">{p}</th>' for p in PO_COLS)
    po_headers += '<th style="background:#7c3aed;color:#fff;padding:5px 4px;font-size:10px;min-width:44px;">CO AVG</th>'

    body_rows = ''
    avgs = {po: [] for po in PO_COLS}
    for row in rows:
        co = row['co']
        stmt = row['stmt']
        pos = row['pos']
        co_avg = row.get('co_avg', '-')
        cells = ''
        for po in PO_COLS:
            v = pos.get(po, '-')
            bg = val_color(v)
            cells += f'<td style="text-align:center;background:{bg};padding:5px 4px;font-size:10px;border:1px solid #d1d5db;">{v}</td>'
            if v not in ['-', '']:
                try: avgs[po].append(float(v))
                except: pass
        cells += f'<td style="text-align:center;background:#f3e8ff;color:#6d28d9;font-weight:700;padding:5px 4px;font-size:10px;border:1px solid #d1d5db;">{co_avg}</td>'
        body_rows += f'''<tr>
          <td style="font-weight:700;color:#1a56db;padding:5px 8px;font-size:10px;border:1px solid #d1d5db;white-space:nowrap;">{co}</td>
          <td style="padding:5px 8px;font-size:9.5px;border:1px solid #d1d5db;max-width:300px;">{stmt}</td>
          {cells}
        </tr>'''

    avg_cells = ''
    all_po_avgs = []
    for po in PO_COLS:
        vals = avgs[po]
        avg = sum(vals)/len(vals) if vals else None
        avg_str = f'{avg:.2f}' if avg is not None else '-'
        avg_cells += f'<td style="text-align:center;background:#fef3c7;font-weight:700;padding:5px 4px;font-size:10px;border:1px solid #d1d5db;">{avg_str}</td>'
        if avg is not None: all_po_avgs.append(avg)
    overall = f'{sum(all_po_avgs)/len(all_po_avgs):.2f}' if all_po_avgs else '-'
    avg_cells += f'<td style="text-align:center;background:#ede9fe;color:#6d28d9;font-weight:700;padding:5px 4px;font-size:10px;border:1px solid #d1d5db;">{overall}</td>'

    html = f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  body {{ font-family: Calibri, Arial, sans-serif; margin: 20px; }}
  h2 {{ color: #1a2340; margin-bottom: 2px; font-size: 14px; }}
  .code {{ display:inline-block;background:#e8f0fe;color:#1a56db;font-size:11px;padding:2px 8px;border-radius:10px;margin-bottom:12px;font-weight:600; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th {{ background:#1a2340;color:#fff;padding:6px 8px;font-size:11px;text-align:left; }}
  .legend {{ margin-top:14px;font-size:10px;color:#555; }}
  .ld {{ display:inline-block;width:12px;height:12px;border-radius:2px;vertical-align:middle;margin-right:3px; }}
</style>
</head><body>
<h2>CO-PO Mapping — {subject_name}</h2>
<span class="code">{subject_code}</span>
<table>
  <thead>
    <tr>
      <th style="min-width:50px;">CO</th>
      <th style="min-width:280px;">CO Statement</th>
      {po_headers}
    </tr>
  </thead>
  <tbody>{body_rows}</tbody>
  <tfoot>
    <tr>
      <td colspan="2" style="padding:5px 8px;font-size:10px;font-weight:700;border:1px solid #d1d5db;background:#fef9c3;">Average</td>
      {avg_cells}
    </tr>
  </tfoot>
</table>
<div class="legend">
  Mapping levels: &nbsp;
  <span class="ld" style="background:#c6efce;border:1px solid #16a34a;"></span>3 — High &nbsp;
  <span class="ld" style="background:#ffeb9c;border:1px solid #ca8a04;"></span>2 — Medium &nbsp;
  <span class="ld" style="background:#ffc7ce;border:1px solid #dc2626;"></span>1 — Low &nbsp;
  <span class="ld" style="background:#f2f2f2;border:1px solid #ccc;"></span>— No mapping
</div>
</body></html>'''

    if fmt == 'pdf':
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = os.path.join(tmpdir, 'copo.html')
            pdf_path = os.path.join(tmpdir, 'copo.pdf')
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            try:
                subprocess.run(['wkhtmltopdf', '--orientation', 'Landscape', '--page-size', 'A4',
                                html_path, pdf_path], check=True, capture_output=True)
            except Exception:
                subprocess.run(['soffice', '--headless', '--convert-to', 'pdf',
                                '--outdir', tmpdir, html_path], check=True, capture_output=True)
                pdf_path = html_path.replace('.html', '.pdf')
            with open(pdf_path, 'rb') as f:
                pdf_bytes = f.read()
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'CO_PO_{subject_code}.pdf'
        )

    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = os.path.join(tmpdir, 'copo.html')
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            subprocess.run(['soffice', '--headless', '--convert-to', 'docx',
                            '--outdir', tmpdir, html_path], check=True, capture_output=True)
            docx_path = html_path.replace('.html', '.docx')
            with open(docx_path, 'rb') as f:
                docx_bytes = f.read()
        return send_file(
            io.BytesIO(docx_bytes),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=f'CO_PO_{subject_code}.docx'
        )


# ── CO-PO SAVE ──────────────────────────────────────────────────────────────
@app.route('/co-po/save', methods=['POST'])
@login_required
@csrf.exempt
def co_po_save():
    data = request.get_json()
    subject_code = data.get('subject_code')
    rows = data.get('rows', [])

    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return jsonify({'success': False, 'error': 'Subject not found'})

    PO_COLS = ['PO1','PO2','PO3','PO4','PO5','PO6','PO7','PO8','PO9','PO10','PO11','PO12','PSO1','PSO2']
    updated = 0
    for row in rows:
        co_obj = CourseOutcome.query.filter_by(
            subject_id=subject.id, co_number=row['co']
        ).first()
        if not co_obj:
            continue
        mapping = {po: row['pos'].get(po, '-') for po in PO_COLS}
        co_obj.po_mapping = mapping
        vals = [float(v) for v in mapping.values() if v not in ('-', '', None) and str(v).isdigit()]
        co_obj.co_avg = round(sum(vals)/len(vals), 2) if vals else None
        updated += 1

    db.session.commit()
    return jsonify({'success': True, 'updated': updated})


# ── CO-PO EXPORT ALL EXCEL ───────────────────────────────────────────────────
@app.route('/co-po/export-all', methods=['GET'])
@login_required
def co_po_export_all():
    import io as _io
    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    except ImportError:
        return "openpyxl not installed", 500

    PO_COLS = ['PO1','PO2','PO3','PO4','PO5','PO6','PO7','PO8','PO9','PO10','PO11','PO12','PSO1','PSO2']

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    hdr_fill   = PatternFill("solid", fgColor="1A2340")
    hdr_font   = Font(color="FFFFFF", bold=True, size=9)
    avg_fill   = PatternFill("solid", fgColor="FEF3C7")
    coavg_fill = PatternFill("solid", fgColor="F3E8FF")
    c3_fill    = PatternFill("solid", fgColor="DCFCE7")
    c2_fill    = PatternFill("solid", fgColor="FEF9C3")
    c1_fill    = PatternFill("solid", fgColor="FEE2E2")
    thin = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    def vfill(v):
        if v == '3': return c3_fill
        if v == '2': return c2_fill
        if v == '1': return c1_fill
        return None

    branches = Branch.query.order_by(Branch.branch_code).all()
    for branch in branches:
        ws = wb.create_sheet(title=branch.branch_code)
        headers = ['Subject Code', 'Subject Name', 'CO', 'CO Statement'] + PO_COLS + ['CO AVG']
        for ci, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=ci, value=h)
            c.fill = hdr_fill; c.font = hdr_font
            c.alignment = Alignment(horizontal='center', wrap_text=True)
            c.border = thin

        ri = 2
        for bs in sorted(branch.subject_links, key=lambda x: x.subject.subject_name):
            subj = bs.subject
            cos = CourseOutcome.query.filter_by(subject_id=subj.id).order_by(CourseOutcome.co_number).all()
            if not cos:
                continue

            po_avgs = {po: [] for po in PO_COLS}
            for co in cos:
                mapping = co.po_mapping or {}
                row_vals = [subj.subject_code, subj.subject_name, co.co_number, co.statement]
                vals_row = []
                for po in PO_COLS:
                    v = str(mapping.get(po, '-') or '-')
                    row_vals.append(v)
                    if v not in ('-', ''):
                        try: po_avgs[po].append(float(v)); vals_row.append(float(v))
                        except: pass
                co_avg_val = round(sum(vals_row)/len(vals_row), 2) if vals_row else '-'
                row_vals.append(co_avg_val)

                for ci, val in enumerate(row_vals, 1):
                    c = ws.cell(row=ri, column=ci, value=val)
                    c.border = thin; c.font = Font(size=9)
                    c.alignment = Alignment(horizontal='center' if ci > 2 else 'left', wrap_text=True)
                    if 5 <= ci <= 4 + len(PO_COLS):
                        f = vfill(str(val)); 
                        if f: c.fill = f
                    if ci == 4 + len(PO_COLS) + 1:
                        c.fill = coavg_fill; c.font = Font(bold=True, size=9, color="6D28D9")
                ri += 1

            # AVG row
            avg_row = ['', '', 'AVG', '']
            all_avgs = []
            for po in PO_COLS:
                v = po_avgs[po]
                a = round(sum(v)/len(v), 2) if v else '-'
                avg_row.append(a)
                if v: all_avgs.append(sum(v)/len(v))
            avg_row.append(round(sum(all_avgs)/len(all_avgs), 2) if all_avgs else '-')
            for ci, val in enumerate(avg_row, 1):
                c = ws.cell(row=ri, column=ci, value=val)
                c.fill = avg_fill; c.font = Font(bold=True, size=9)
                c.alignment = Alignment(horizontal='center'); c.border = thin
            ri += 2

        ws.column_dimensions['A'].width = 14
        ws.column_dimensions['B'].width = 35
        ws.column_dimensions['C'].width = 8
        ws.column_dimensions['D'].width = 50
        for col in ['E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S']:
            ws.column_dimensions[col].width = 7

    buf = _io.BytesIO()
    wb.save(buf); buf.seek(0)
    return send_file(buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name='CO_PO_All_Subjects.xlsx')


# ── QUESTION DIFFICULTY ANALYTICS ───────────────────────────────────────────
@app.route('/analytics', methods=['GET'])
@login_required
def analytics_page():
    from sqlalchemy import func

    bloom_labels = ['Remember', 'Understand', 'Apply', 'Analyze', 'Evaluate', 'Create']

    branches = Branch.query.order_by(Branch.branch_code).all()
    branch_filter = request.args.get('branch', 'ALL')

    if branch_filter != 'ALL':
        branch_obj = Branch.query.filter_by(branch_code=branch_filter).first()
        subj_ids = [bs.subject_id for bs in branch_obj.subject_links] if branch_obj else []
    else:
        subj_ids = [s.id for s in Subject.query.all()]

    # PartAQuestion has subject_id directly
    parta_blooms = db.session.query(
        PartAQuestion.bloom_level, func.count(PartAQuestion.id)
    ).filter(PartAQuestion.subject_id.in_(subj_ids)).group_by(PartAQuestion.bloom_level).all()

    # QuestionPart → QuestionGroup (has subject_id)
    partb_blooms = db.session.query(
        QuestionPart.bloom_level, func.count(QuestionPart.id)
    ).join(QuestionGroup, QuestionPart.group_id == QuestionGroup.id
    ).filter(QuestionGroup.subject_id.in_(subj_ids)).group_by(QuestionPart.bloom_level).all()

    # bloom_level is stored as string e.g. 'Remember'
    parta_counts = {bl: cnt for bl, cnt in parta_blooms if bl}
    partb_counts = {bl: cnt for bl, cnt in partb_blooms if bl}

    parta_data = [parta_counts.get(l, 0) for l in bloom_labels]
    partb_data = [partb_counts.get(l, 0) for l in bloom_labels]

    subj_bloom = []
    for s in Subject.query.filter(Subject.id.in_(subj_ids)).all():
        pa = db.session.query(func.count(PartAQuestion.id)).filter(PartAQuestion.subject_id == s.id).scalar() or 0
        pb = db.session.query(func.count(QuestionPart.id)).join(QuestionGroup, QuestionPart.group_id == QuestionGroup.id).filter(QuestionGroup.subject_id == s.id).scalar() or 0
        if pa + pb > 0:
            subj_bloom.append({'name': s.subject_name, 'code': s.subject_code, 'parta': pa, 'partb': pb, 'total': pa+pb})

    subj_bloom.sort(key=lambda x: -x['total'])

    return render_template('analytics.html',
        branches=branches, branch_filter=branch_filter,
        bloom_labels=bloom_labels,
        parta_data=parta_data, partb_data=partb_data,
        top_subjects=subj_bloom[:25],
        total_parta=sum(parta_data), total_partb=sum(partb_data)
    )


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    print("\n🚀 Database verified and synchronized successfully.")
    print("👉 Open http://127.0.0.1:5000/ in your web browser to view your application.\n")
    app.run(debug=True)