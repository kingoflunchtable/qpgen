"""
seed_co_po_values.py
Reads PO mapping values + CO AVG from excel → updates course_outcomes table.
Run AFTER migrate_copo_fields.sql
Usage: python seed_co_po_values.py [--apply]
"""
import sys, re
import openpyxl
from difflib import get_close_matches

DRY_RUN = '--apply' not in sys.argv
XLSX = 'CO-PO Mapping R22 .xlsx'

PO_COLS = ['PO1','PO2','PO3','PO4','PO5','PO6','PO7','PO8','PO9','PO10','PO11','PO12','PSO1','PSO2']
# Excel columns: SL(0) COURSE(1) CO(2) STMT(3) PO1(4)..PSO2(17) CO_AVG(18)
PO_COL_INDICES = list(range(4, 18))  # indices 4-17
CO_AVG_IDX = 18

from app import app
from models import db, Subject, CourseOutcome

def normalize(s):
    return re.sub(r'\s+', ' ', str(s).strip().upper())

def clean_val(v):
    """Convert cell value to string: '1','2','3' or '-'"""
    if v is None or str(v).strip() in ('', 'None', '--'):
        return '-'
    s = str(v).strip()
    if s == '-':
        return '-'
    try:
        f = float(s)
        i = int(f)
        if i in (1, 2, 3):
            return str(i)
        return '-'
    except:
        return '-'

with app.app_context():
    subjects = Subject.query.all()
    subj_by_name = {normalize(s.subject_name): s for s in subjects}
    all_norm_names = list(subj_by_name.keys())

    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    current_subj_obj = None
    updated = 0
    skipped = 0
    unmatched = set()

    for row in rows[1:]:
        sl, course, co_num = row[0], row[1], row[2]

        if course and str(course).strip():
            norm = normalize(course)
            if norm in subj_by_name:
                current_subj_obj = subj_by_name[norm]
            else:
                matches = get_close_matches(norm, all_norm_names, n=1, cutoff=0.6)
                if matches:
                    current_subj_obj = subj_by_name[matches[0]]
                else:
                    current_subj_obj = None
                    unmatched.add(str(course).strip())

        if not co_num:
            continue
        co_num = str(co_num).strip()
        if co_num.upper() == 'AVG' or not co_num.startswith('CO'):
            continue
        if not current_subj_obj:
            skipped += 1
            continue

        co_obj = CourseOutcome.query.filter_by(
            subject_id=current_subj_obj.id,
            co_number=co_num
        ).first()
        if not co_obj:
            skipped += 1
            continue

        # Build po_mapping
        mapping = {}
        for i, po in enumerate(PO_COLS):
            mapping[po] = clean_val(row[PO_COL_INDICES[i]])

        # CO AVG
        co_avg = None
        try:
            raw = row[CO_AVG_IDX]
            if raw is not None:
                co_avg = float(raw)
        except:
            pass

        print(f"  {'[DRY]' if DRY_RUN else '[UPD]'} {current_subj_obj.subject_code} {co_num} | {mapping} | avg={co_avg}")

        if not DRY_RUN:
            co_obj.po_mapping = mapping
            co_obj.co_avg = co_avg
        updated += 1

    if not DRY_RUN:
        db.session.commit()
        print(f"\nDone. Updated: {updated}, Skipped: {skipped}")
    else:
        print(f"\nDRY RUN. Would update: {updated}, Skip: {skipped}")

    if unmatched:
        print(f"\nUnmatched ({len(unmatched)}): {sorted(unmatched)}")