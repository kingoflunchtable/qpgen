"""
list_mid_obj_progress.py — Read-only report: for every theory subject,
shows MidObjectiveQuestion coverage (MCQ + Fill counts per unit).

DONE   = all 5 units have >= 4 MCQ + >= 4 Fill (enough for both mids)
PARTIAL = some units done
TODO   = nothing yet

Usage:
    python list_mid_obj_progress.py
"""

from app import app
from models import db, Subject, Unit, MidObjectiveQuestion

SKIP_KEYWORDS = (
    "lab", "laboratory", "workshop", "project", "internship",
    "induction", "research project",
)
MIN_MCQ = 4
MIN_FILL = 4


def skip(name):
    return any(k in name.lower() for k in SKIP_KEYWORDS)


def run():
    with app.app_context():
        subjects = Subject.query.order_by(Subject.subject_code).all()
        done, partial, todo, no_units = [], [], [], []

        for s in subjects:
            if skip(s.subject_name):
                continue
            units = sorted(s.units, key=lambda u: u.unit_number)
            if not units:
                no_units.append(s)
                continue

            weak = []
            for u in units:
                mcq = MidObjectiveQuestion.query.filter_by(unit_id=u.id, question_type='mcq', is_active=True).count()
                fill = MidObjectiveQuestion.query.filter_by(unit_id=u.id, question_type='fib', is_active=True).count()
                if mcq < MIN_MCQ or fill < MIN_FILL:
                    weak.append((u.unit_number, mcq, fill))

            if not weak:
                done.append(s)
            elif len(weak) == len(units):
                todo.append(s)
            else:
                partial.append((s, weak))

        theory = len(subjects) - len(no_units)
        print(f"Theory subjects: {theory}  |  DONE: {len(done)}  PARTIAL: {len(partial)}  TODO: {len(todo)}")
        print(f"Threshold: >={MIN_MCQ} MCQ + >={MIN_FILL} Fill per unit\n")

        print(f"=== DONE ({len(done)}) ===")
        for s in done:
            print(f"  {s.subject_code or 'PEND':12s} {s.subject_name}")

        print(f"\n=== PARTIAL ({len(partial)}) ===")
        for s, weak in partial:
            detail = "  ".join(f"U{n}:mcq={m},fill={f}" for n, m, f in weak)
            print(f"  {s.subject_code or 'PEND':12s} {s.subject_name}")
            print(f"               weak → {detail}")

        print(f"\n=== TODO ({len(todo)}) ===")
        for s in todo:
            print(f"  {s.subject_code or 'PEND':12s} {s.subject_name}")

        if no_units:
            print(f"\n=== NO UNITS ({len(no_units)}) ===")
            for s in no_units:
                print(f"  {s.subject_code or 'PEND':12s} {s.subject_name}")


if __name__ == '__main__':
    run()