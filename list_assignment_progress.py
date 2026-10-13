"""
list_assignment_progress.py
Run from qpgen root: python list_assignment_progress.py
Lists which subjects have assignment questions and which don't.
"""
import app
with app.app.app_context():
    from models import Subject, AssignmentQuestion

    subjects = Subject.query.order_by(Subject.subject_name).all()
    has = []
    no = []

    for s in subjects:
        a1 = AssignmentQuestion.query.filter_by(subject_id=s.id, assignment_number=1, is_active=True).count()
        a2 = AssignmentQuestion.query.filter_by(subject_id=s.id, assignment_number=2, is_active=True).count()
        total = a1 + a2
        entry = f"  {s.subject_code:<12} {s.subject_name:<50} A1:{a1:>3}  A2:{a2:>3}  Total:{total:>3}"
        (has if total > 0 else no).append(entry)

    print(f"\n{'='*80}")
    print(f"  HAS ASSIGNMENTS ({len(has)} subjects)")
    print(f"{'='*80}")
    for x in has:
        print(x)

    print(f"\n{'='*80}")
    print(f"  NO ASSIGNMENTS ({len(no)} subjects)")
    print(f"{'='*80}")
    for x in no:
        print(x)

    print(f"\n  Total subjects: {len(subjects)}  |  With: {len(has)}  |  Without: {len(no)}\n")