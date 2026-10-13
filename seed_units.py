"""
seed_units.py — Creates 5 default Unit rows ("Unit 1".."Unit 5") for every
Subject that looks like a theory course and doesn't have any Units yet.

WHY: bulk question entry, AI-generate, and paper generation all key off
Unit, but seed_curriculum.py only ever created Subject/BranchSubject rows.
Without at least one Unit per theory subject, the Admin Bulk Entry and
Generator pages have nothing to attach questions to.

WHY NOT EVERY SUBJECT: lab courses, workshops, projects, and internships
don't get a written Part-A/Part-B paper the same way theory subjects do,
so they're skipped rather than given empty placeholder units. The skip
heuristic is just a keyword match on the subject name — review the
"SKIPPED" list below before running with --apply, and tell me about any
that's wrong (e.g. a subject that SHOULD get units but got excluded, or
vice versa) so the keyword list can be corrected.

These are GENERIC placeholder names ("Unit 1", not a real topic title).
Renaming them to the real syllabus unit titles is a separate, optional
follow-up — ask if you'd like that built out per-subject later.

Usage:
    python seed_units.py            # dry run — prints the plan, writes nothing
    python seed_units.py --apply    # actually creates the Unit rows
"""

import sys

from app import app
from models import db, Subject, Unit

SKIP_KEYWORDS = (
    "lab", "laboratory", "workshop", "project", "internship",
    "induction", "research project",
)

DEFAULT_UNIT_COUNT = 5


def looks_like_non_theory(subject_name):
    name_lower = subject_name.lower()
    return any(kw in name_lower for kw in SKIP_KEYWORDS)


def run(apply_changes):
    with app.app_context():
        subjects = Subject.query.order_by(Subject.subject_code).all()

        to_create = []
        skipped_non_theory = []
        already_has_units = []

        for subject in subjects:
            if subject.units:
                already_has_units.append(subject)
                continue
            if looks_like_non_theory(subject.subject_name):
                skipped_non_theory.append(subject)
                continue
            to_create.append(subject)

        print(f"Total subjects in DB:        {len(subjects)}")
        print(f"Already have units (skip):   {len(already_has_units)}")
        print(f"Skipped as non-theory:       {len(skipped_non_theory)}")
        print(f"Will get 5 default units:    {len(to_create)}")

        print("\n--- SKIPPED AS NON-THEORY (review this list) ---")
        for s in skipped_non_theory:
            print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}")

        if not apply_changes:
            print("\nDRY RUN — no changes written. Re-run with --apply to commit.")
            print(f"\n--- WOULD CREATE units for ({len(to_create)} subjects) ---")
            for s in to_create:
                print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}")
            return

        for s in to_create:
            existing_nums = {u.unit_number for u in s.units}
            for n in range(1, DEFAULT_UNIT_COUNT + 1):
                if n not in existing_nums:
                    db.session.add(Unit(subject_id=s.id, unit_number=n, unit_name=f"Unit {n}"))
        db.session.commit()
        print(f"\n✅ Created {DEFAULT_UNIT_COUNT} default units for {len(to_create)} subjects.")


if __name__ == '__main__':
    run(apply_changes='--apply' in sys.argv)