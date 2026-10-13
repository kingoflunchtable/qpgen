"""
list_subject_progress.py — Read-only report: for every theory subject,
shows whether it already has real Part-A + Question Group content
("DONE") or still needs it ("TODO"). Makes zero changes to the database.

A subject counts as DONE if it has at least 2 live Part-A questions AND
at least 2 live Question Groups for EVERY one of its units (matching
generator.py's minimum requirement to actually generate a paper) —
partial subjects (some units done, some not) are reported with the
specific units still missing, so nothing gets silently skipped.

Usage:
    python list_subject_progress.py
"""

from app import app
from models import db, Subject, PartAQuestion, QuestionGroup

SKIP_KEYWORDS = (
    "lab", "laboratory", "workshop", "project", "internship",
    "induction", "research project",
)


def looks_like_non_theory(subject_name):
    return any(kw in subject_name.lower() for kw in SKIP_KEYWORDS)


def run():
    with app.app_context():
        subjects = Subject.query.order_by(Subject.subject_code).all()

        done = []
        todo = []
        partial = []
        no_units = []

        for s in subjects:
            if looks_like_non_theory(s.subject_name):
                continue
            units = sorted(s.units, key=lambda u: u.unit_number)
            if not units:
                no_units.append(s)
                continue

            missing_units = []
            for u in units:
                pa = PartAQuestion.query.filter_by(unit_id=u.id, is_active=True).count()
                grp = QuestionGroup.query.filter_by(unit_id=u.id, is_active=True).count()
                if pa < 2 or grp < 2:
                    missing_units.append(u.unit_number)

            if not missing_units:
                done.append(s)
            elif len(missing_units) == len(units):
                todo.append(s)
            else:
                partial.append((s, missing_units))

        print(f"Total theory subjects: {len(subjects) - len(no_units)} (+{len(no_units)} with no units yet)")
        print(f"\n=== DONE ({len(done)}) ===")
        for s in done:
            print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}")

        print(f"\n=== PARTIAL ({len(partial)}) — some units still missing ===")
        for s, missing in partial:
            print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}  (missing units: {missing})")

        print(f"\n=== TODO ({len(todo)}) — nothing yet ===")
        for s in todo:
            print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}")

        if no_units:
            print(f"\n=== NO UNITS YET ({len(no_units)}) — run seed_units.py first ===")
            for s in no_units:
                print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}")


if __name__ == '__main__':
    run()