"""
Bulk-add MCQ and Fill-in-blank objective questions for mid exams.

Usage:
    python bulk_mid_objectives.py

Edit the QUESTIONS list below (or replace with JSON file loading).

Format for each question dict:
  {
    "subject_code": "A1234",
    "unit_number": 1,            # 1-5
    "obj_type": "mcq",           # "mcq" or "fill"
    "question_text": "...",
    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],  # MCQ only; None for fill
    "answer": "A",               # Option letter for MCQ; answer text for fill
    "bloom_level": "Remember",   # optional
  }

You need >= 10 MCQ and >= 10 Fill questions across the 3 units
involved in each mid (units 1,2,3 for mid-1; units 3,4,5 for mid-2).
"""

import json, os
from dotenv import load_dotenv
load_dotenv()

from app import app
from models import db, Subject, Unit, MidObjectiveQuestion

# -----------------------------------------------------------------------
# PASTE YOUR QUESTIONS HERE (or load from a JSON file)
# -----------------------------------------------------------------------
QUESTIONS = [
    # Example MCQ
    # {
    #     "subject_code": "A1234",
    #     "unit_number": 1,
    #     "obj_type": "mcq",
    #     "question_text": "Which of the following is used to declare a variable in Python?",
    #     "options": ["int x = 5", "x = 5", "var x = 5", "declare x = 5"],
    #     "answer": "B",
    #     "bloom_level": "Remember",
    # },
    # Example Fill
    # {
    #     "subject_code": "A1234",
    #     "unit_number": 1,
    #     "obj_type": "fill",
    #     "question_text": "The process of converting source code to machine code is called ______.",
    #     "options": None,
    #     "answer": "compilation",
    #     "bloom_level": "Remember",
    # },
]
# -----------------------------------------------------------------------

def run():
    with app.app_context():
        added = 0
        skipped = 0
        for q in QUESTIONS:
            subject = Subject.query.filter_by(subject_code=q['subject_code']).first()
            if not subject:
                print(f"  SKIP: subject {q['subject_code']} not found")
                skipped += 1
                continue
            unit = Unit.query.filter_by(subject_id=subject.id, unit_number=q['unit_number']).first()
            if not unit:
                print(f"  SKIP: unit {q['unit_number']} not found for {q['subject_code']}")
                skipped += 1
                continue

            obj = MidObjectiveQuestion(
                subject_id=subject.id,
                unit_id=unit.id,
                obj_type=q['obj_type'],
                question_text=q['question_text'],
                options_json=q.get('options'),
                answer=q.get('answer'),
                bloom_level=q.get('bloom_level', 'Remember'),
            )
            db.session.add(obj)
            added += 1

        db.session.commit()
        print(f"\n✓ Added {added} objective questions. Skipped {skipped}.")

        # Print counts per subject/unit
        print("\nCurrent objective question counts:")
        subjects_done = set()
        for q in QUESTIONS:
            if q['subject_code'] not in subjects_done:
                subjects_done.add(q['subject_code'])
                subj = Subject.query.filter_by(subject_code=q['subject_code']).first()
                if subj:
                    units = Unit.query.filter_by(subject_id=subj.id).order_by(Unit.unit_number).all()
                    print(f"\n  {subj.subject_code} — {subj.subject_name}")
                    for u in units:
                        mcq_c = MidObjectiveQuestion.query.filter_by(unit_id=u.id, obj_type='mcq', is_active=True).count()
                        fill_c = MidObjectiveQuestion.query.filter_by(unit_id=u.id, obj_type='fill', is_active=True).count()
                        print(f"    Unit {u.unit_number}: {mcq_c} MCQ, {fill_c} Fill")

if __name__ == '__main__':
    run()
