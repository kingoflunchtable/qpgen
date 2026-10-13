"""
seed_co_from_excel.py
Reads CO-PO_Mapping_R22_.xlsx and populates course_outcomes table.
Matches Excel subject names → DB subjects via fuzzy name matching.
Usage: python seed_co_from_excel.py [--apply]
"""
import sys, re
import openpyxl
from difflib import get_close_matches

DRY_RUN = '--apply' not in sys.argv
XLSX = 'CO-PO Mapping R22 .xlsx'   # adjust path if needed

from app import app
from models import db, Subject, CourseOutcome

def normalize(s):
    return re.sub(r'\s+', ' ', str(s).strip().upper())

with app.app_context():
    # Load all subjects
    subjects = Subject.query.all()
    subj_by_name = {normalize(s.subject_name): s for s in subjects}
    all_norm_names = list(subj_by_name.keys())

    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb.active

    PO_COLS = ['PO1','PO2','PO3','PO4','PO5','PO6','PO7',
               'PO8','PO9','PO10','PO11','PO12','PSO1','PSO2']

    current_subject = None
    current_subj_obj = None
    inserted = 0
    skipped = 0
    unmatched = set()

    rows = list(ws.iter_rows(values_only=True))
    # Row 0 is header
    for row in rows[1:]:
        sl, course, co_num, stmt = row[0], row[1], row[2], row[3]

        # New subject block
        if course and str(course).strip():
            norm = normalize(course)
            if norm in subj_by_name:
                current_subj_obj = subj_by_name[norm]
            else:
                matches = get_close_matches(norm, all_norm_names, n=1, cutoff=0.6)
                if matches:
                    current_subj_obj = subj_by_name[matches[0]]
                    print(f"  FUZZY: '{course}' → '{matches[0]}'")
                else:
                    print(f"  NO MATCH: '{course}'")
                    unmatched.add(str(course).strip())
                    current_subj_obj = None

        if not co_num or not stmt:
            continue
        co_num = str(co_num).strip()
        stmt = str(stmt).strip()
        if co_num.upper() == 'AVG' or not co_num.startswith('CO'):
            continue
        if not current_subj_obj:
            skipped += 1
            continue

        # Check duplicate
        exists = CourseOutcome.query.filter_by(
            subject_id=current_subj_obj.id,
            co_number=co_num
        ).first()
        if exists:
            if DRY_RUN:
                print(f"  EXISTS: {current_subj_obj.subject_code} {co_num}")
            skipped += 1
            continue

        print(f"  {'[DRY]' if DRY_RUN else '[ADD]'} {current_subj_obj.subject_code} | {co_num} | {stmt[:60]}")
        if not DRY_RUN:
            co = CourseOutcome(
                subject_id=current_subj_obj.id,
                co_number=co_num,
                statement=stmt
            )
            db.session.add(co)
        inserted += 1

    if not DRY_RUN:
        db.session.commit()
        print(f"\nDone. Inserted: {inserted}, Skipped: {skipped}")
    else:
        print(f"\nDRY RUN. Would insert: {inserted}, Skip: {skipped}")

    if unmatched:
        print(f"\nUnmatched subjects ({len(unmatched)}):")
        for u in sorted(unmatched):
            print(f"  - {u}")