"""
add_aiml_year4_electives.py — Adds the elective option Subjects found in the
new "Final IV syllabus V2 modified bos.pdf" document that aren't present in
the original three R25 syllabus PDFs seed_curriculum.py was built against.

WHY THIS EXISTS: the original seed_curriculum.py parsed CSE/AIML/ECE R25
syllabus PDFs that only had detailed Year 1 unit content plus Year 1-4
*overview* tables (codes/titles/credits, no elective option breakdowns).
This new PDF is a separate, AIML-specific document with the actual elective
option lists for Year 4 (Professional Elective III-VI, Open Elective II-III)
spelled out — which the original PDFs never had. So these 8 subjects never
got created as Subject rows at all; this script fills that specific gap
without re-running the original importer against a document it wasn't
designed to parse.

SCOPE: branch=AIML only. The new PDF's title page says "B.Tech. in CSE
(AI & ML)" — there's no evidence in it about whether CSE/ECE offer the same
elective options, so this script does NOT assume that and does NOT touch
those branches. If CSE/ECE turn out to offer the same electives, that's a
separate, deliberate decision — not something to guess here.

Subjects added, with their real slot/term from the curriculum overview
table on pages 1-2 of the new PDF:

    Mobile Computing            Professional Elective-IV   Year 4, Sem 1
    Semantic Web                Professional Elective-IV   Year 4, Sem 1
    Social Network Analysis     Professional Elective-V    Year 4, Sem 2
    Federated Machine Learning  Professional Elective-V    Year 4, Sem 2
    Speech and Video Processing Professional Elective-VI   Year 4, Sem 2
    Randomized Algorithms       Professional Elective-VI   Year 4, Sem 2
    Conversational AI           Professional Elective-VI   Year 4, Sem 2
    Evolutionary Computing      Open Elective-III          Year 4, Sem 2

Uses the SAME stable_pending_code() scheme as seed_curriculum.py (md5 of
the normalized title), so re-running this script is idempotent and the
codes it generates are stable across runs — matching the convention
already established for every other elective subject in this project.

Usage:
    python add_aiml_year4_electives.py            # dry run — prints the plan, writes nothing
    python add_aiml_year4_electives.py --apply     # actually inserts
"""

import sys
import hashlib

from app import app
from models import db, Branch, Subject, BranchSubject

BRANCH_CODE = "AIML"

# (title, elective_group, academic_year, semester_number)
NEW_ELECTIVES = [
    ("Mobile Computing",            "Professional Elective-IV", 4, 1),
    ("Semantic Web",                "Professional Elective-IV", 4, 1),
    ("Social Network Analysis",     "Professional Elective-V",  4, 2),
    ("Federated Machine Learning",  "Professional Elective-V",  4, 2),
    ("Speech and Video Processing", "Professional Elective-VI", 4, 2),
    ("Randomized Algorithms",       "Professional Elective-VI", 4, 2),
    ("Conversational AI",           "Professional Elective-VI", 4, 2),
    ("Evolutionary Computing",      "Open Elective-III",        4, 2),
]


def stable_pending_code(branch_code, academic_year, semester_number, title):
    """Identical to seed_curriculum.py's version — same scheme, so codes
    generated here are consistent with every other elective subject in
    the project and stable across repeated runs of this script."""
    normalized = title.strip().lower()
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:6].upper()
    return f"PEND-{branch_code}-{academic_year}{semester_number}-{digest}"


def run(apply_changes):
    with app.app_context():
        branch = Branch.query.filter_by(branch_code=BRANCH_CODE).first()
        if not branch:
            print(f"❌ Branch '{BRANCH_CODE}' not found in the database — "
                  f"nothing to link these subjects to. Aborting.")
            return

        to_create = []
        already_exists = []

        for title, elective_group, year, sem in NEW_ELECTIVES:
            code = stable_pending_code(BRANCH_CODE, year, sem, title)
            existing = Subject.query.filter_by(subject_code=code).first()

            if existing:
                link = BranchSubject.query.filter_by(
                    branch_id=branch.id, subject_id=existing.id
                ).first()
                if link:
                    already_exists.append((title, code))
                    continue

            to_create.append((title, elective_group, year, sem, code))

        print(f"Branch: {BRANCH_CODE} (id={branch.id})")
        print(f"Already present, skipping: {len(already_exists)}")
        for title, code in already_exists:
            print(f"  {code:25s} {title}")

        print(f"\nWill create: {len(to_create)}")
        for title, elective_group, year, sem, code in to_create:
            print(f"  {code:25s} Yr{year} Sem{sem}  [{elective_group}]  {title}")

        if not apply_changes:
            print("\nDRY RUN — no changes written. Re-run with --apply to commit.")
            return

        created_count = 0
        for title, elective_group, year, sem, code in to_create:
            subj = Subject.query.filter_by(subject_code=code).first()
            if not subj:
                subj = Subject(subject_code=code, subject_name=title, code_pending=True)
                db.session.add(subj)
                db.session.flush()

            link = BranchSubject(
                branch_id=branch.id,
                subject_id=subj.id,
                academic_year=year,
                semester_number=sem,
                elective_group=elective_group,
            )
            db.session.add(link)
            try:
                db.session.commit()
                created_count += 1
            except Exception as e:
                db.session.rollback()
                print(f"  ⚠️  Failed to create {code} ({title}): {e}")

        print(f"\n✅ Created {created_count} of {len(to_create)} subjects.")


if __name__ == '__main__':
    run(apply_changes='--apply' in sys.argv)