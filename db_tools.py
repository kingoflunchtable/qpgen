"""
db_tools.py — All one-time DB maintenance utilities in one place.

Usage:
    python db_tools.py dedupe [--apply]              # find & merge duplicate subjects by name
    python db_tools.py dedupe --remove-done-dupes [--apply]
    python db_tools.py merge [--apply]               # migrate drop-codes → keep-codes (PAIRS list)
    python db_tools.py delete [--apply]              # delete CODES_TO_DELETE list
    python db_tools.py fix-units [--apply]           # remove duplicate unit rows
    python db_tools.py remove-labs [--apply]         # delete lab/workshop/project subjects
    python db_tools.py verify [A2501]                # check branch links for a subject code
"""

import re
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app import app
from models import (
    db, Subject, BranchSubject, Unit, PartAQuestion, QuestionGroup,
    QuestionPart, PendingQuestion, GeneratedPaper, PaperUnitSlot
)

# ---------------------------------------------------------------------------
# CONFIG — edit these lists as needed
# ---------------------------------------------------------------------------

# merge: (keep_code, [drop_codes...])
PAIRS = [
    ("A2013", ["A1007", "A2425"]),
    ("A2601", ["A1611", "A1692"]),
    ("A2515", ["A1516", "A1592"]),
    ("A2415", ["A1429"]),
    ("A2524", ["A1528"]),
    ("A1556", ["PEND-CSE-41-C1F22D"]),
    ("A1754", ["PEND-CSE-41-FD99D2"]),
    ("A1574", ["A1669"]),
    ("A1613", ["A1596", "A1466", "PEND-CSE-32-DE0FE2"]),
    ("A1617", ["A1559"]),
    ("A1523", ["A1572", "A1595"]),
    ("A1554", ["A1654", "A1461", "PEND-ECE-41-D81E88"]),
    ("A1615", ["A1553", "PEND-AIML-31-D65D16"]),
    ("A1455", ["A1557"]),
    ("A1425", ["A1492"]),
    ("A1454", ["A1494"]),
    ("A1463", ["A1499"]),
    ("A1470", ["A1495"]),
    ("A1575", ["PEND-AIML-32-C96AB1"]),
    ("A1430", ["PEND-ECE-32-E81A7F"]),
    ("A1691", ["PEND-ECE-41-CE4093"]),
]

# delete: codes to wipe from DB entirely
CODES_TO_DELETE = [
    "A2522", "A2524",
    "PEND-AIML-41-28FFA3", "PEND-AIML-41-A8CF2C", "PEND-AIML-41-D70829",
    "PEND-AIML-41-E61AA9", "PEND-AIML-42-A86973",
    "PEND-CSE-31-37F4BE", "PEND-CSE-32-4DCFDA", "PEND-CSE-32-5BE145",
    "PEND-CSE-32-7F7A9C", "PEND-CSE-32-DD7EB2", "PEND-CSE-32-E361E8",
    "PEND-CSE-41-422D22", "PEND-CSE-41-D7DA98", "PEND-CSE-41-DE19E1",
    "PEND-CSE-42-09935B", "PEND-CSE-42-1491F2", "PEND-CSE-42-19AEB4",
    "PEND-CSE-42-A528B0", "PEND-CSE-42-E4C58E",
    "PEND-ECE-31-7DC2DD", "PEND-ECE-31-A083A1", "PEND-ECE-31-A526B2",
    "PEND-ECE-31-F44833", "PEND-ECE-31-FA969D",
    "PEND-ECE-32-2E86DE", "PEND-ECE-32-DEF5A3",
    "PEND-ECE-41-CE59A6", "PEND-ECE-42-D827B5",
]

# remove-labs: keyword match (same as seed_units.py)
LAB_KEYWORDS = ("lab", "laboratory", "workshop", "project", "internship", "induction", "research project")

# ---------------------------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------------------------

def _normalize(name):
    t = name.lower().strip().replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"[^a-z0-9\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()

def _is_pend(code):
    return bool(code) and code.startswith("PEND-")

def _content_score(s):
    score = 0
    for u in s.units:
        score += PartAQuestion.query.filter_by(unit_id=u.id, is_active=True).count()
        score += QuestionGroup.query.filter_by(unit_id=u.id, is_active=True).count()
        score += PendingQuestion.query.filter_by(unit_id=u.id, status='pending').count()
    return score

def _delete_subject(s):
    """Hard-delete subject + all dependents. No CASCADE configured on FKs."""
    gids = [g.id for g in QuestionGroup.query.filter_by(subject_id=s.id).all()]
    if gids:
        QuestionPart.query.filter(QuestionPart.group_id.in_(gids)).delete(synchronize_session=False)
    QuestionGroup.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    PartAQuestion.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    PendingQuestion.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    pids = [p.id for p in GeneratedPaper.query.filter_by(subject_id=s.id).all()]
    if pids:
        PaperUnitSlot.query.filter(PaperUnitSlot.paper_id.in_(pids)).delete(synchronize_session=False)
    GeneratedPaper.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    Unit.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    BranchSubject.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    db.session.delete(s)

# ---------------------------------------------------------------------------
# 1. DEDUPE  (python db_tools.py dedupe [--apply] [--remove-done-dupes])
# ---------------------------------------------------------------------------

def cmd_dedupe(apply, remove_done_dupes=False):
    with app.app_context():
        if remove_done_dupes:
            _dedupe_remove_done(apply)
        else:
            _dedupe_run(apply)

def _is_done(s):
    if not s.units:
        return False
    for u in s.units:
        if (PartAQuestion.query.filter_by(unit_id=u.id, is_active=True).count() < 2 or
                QuestionGroup.query.filter_by(unit_id=u.id, is_active=True).count() < 2):
            return False
    return True

def _dedupe_run(apply):
    all_subjects = Subject.query.all()
    groups = defaultdict(list)
    for s in all_subjects:
        groups[_normalize(s.subject_name)].append(s)

    dup_groups = {n: r for n, r in groups.items() if len(r) > 1}
    print(f"Total subjects: {len(all_subjects)}")
    print(f"Duplicate name-groups: {len(dup_groups)}")

    safe, review, ambig = [], [], []

    for name, group in dup_groups.items():
        real_coded = [s for s in group if s.subject_code and not _is_pend(s.subject_code)]
        if len(real_coded) > 1:
            ambig.append((name, group))
            continue
        canonical = (real_coded[0] if len(real_coded) == 1
                     else max(group, key=lambda s: (-_content_score(s), s.id)))
        for s in group:
            if s.id == canonical.id:
                continue
            score = _content_score(s)
            if score == 0 or (_is_pend(s.subject_code) and not _is_pend(canonical.subject_code)):
                safe.append((canonical, s))
            else:
                review.append((name, canonical, s, score))

    print(f"Safe auto-merge: {len(safe)} | Needs review: {len(review)} | Ambiguous: {len(ambig)}")

    if review:
        print("\n--- NEEDS REVIEW ---")
        for name, canonical, dup, score in review:
            print(f"  {name!r}")
            print(f"    keep: {canonical.subject_code:20s} id={canonical.id}")
            print(f"    dup:  {dup.subject_code:20s} id={dup.id}  score={score}")

    if ambig:
        print("\n--- AMBIGUOUS (multiple real codes, same name) ---")
        for name, group in ambig:
            print(f"  {name!r}: {[s.subject_code for s in group]}")

    if not apply:
        print("\nDRY RUN. Add --apply to commit.")
        for canonical, dup in safe:
            print(f"  DELETE {dup.subject_code:20s} -> KEEP {canonical.subject_code}")
        return

    merged = 0
    for canonical, dup in safe:
        try:
            dup_links = db.session.execute(
                text("SELECT id, branch_id, academic_year, semester_number FROM branch_subjects WHERE subject_id = :sid"),
                {"sid": dup.id}
            ).fetchall()
            for link_id, branch_id, dup_year, dup_sem in dup_links:
                existing = db.session.execute(
                    text("SELECT id FROM branch_subjects WHERE branch_id = :bid AND subject_id = :cid"),
                    {"bid": branch_id, "cid": canonical.id}
                ).fetchone()
                if existing:
                    db.session.execute(text("DELETE FROM branch_subjects WHERE id = :lid"), {"lid": link_id})
                else:
                    db.session.execute(text("UPDATE branch_subjects SET subject_id = :cid WHERE id = :lid"),
                                       {"cid": canonical.id, "lid": link_id})
            db.session.execute(text("DELETE FROM units WHERE subject_id = :sid"), {"sid": dup.id})
            db.session.execute(text("DELETE FROM subjects WHERE id = :sid"), {"sid": dup.id})
            db.session.commit()
            merged += 1
        except Exception as e:
            db.session.rollback()
            print(f"  SKIP {dup.subject_name!r} id={dup.id}: {e}")

    print(f"\n✅ Merged {merged}. Left untouched (has content): {len(review)}.")

def _dedupe_remove_done(apply):
    subjects = Subject.query.order_by(Subject.subject_code).all()
    theory = [s for s in subjects if not any(kw in s.subject_name.lower() for kw in LAB_KEYWORDS)]
    done_norms = {_normalize(s.subject_name): s for s in theory if _is_done(s)}
    to_del = [(s, done_norms[_normalize(s.subject_name)])
               for s in theory if not _is_done(s) and _normalize(s.subject_name) in done_norms]
    print(f"DONE subjects: {len(done_norms)} | Will delete: {len(to_del)}")
    for s, keeper in to_del:
        print(f"  DEL {s.subject_code or '(pending)':20s} {s.subject_name} -> keep {keeper.subject_code}")
    if not apply:
        print("\nDRY RUN. Add --apply.")
        return
    deleted = 0
    for s, _ in to_del:
        try:
            _delete_subject(s)
            db.session.commit()
            deleted += 1
        except Exception as e:
            db.session.rollback()
            print(f"  FAIL {s.subject_code}: {e}")
    print(f"\n✅ Deleted {deleted}.")

# ---------------------------------------------------------------------------
# 2. MERGE  (python db_tools.py merge [--apply])
# ---------------------------------------------------------------------------

def cmd_merge(apply):
    with app.app_context():
        print("=== merge ===")
        for keep_code, drop_codes in PAIRS:
            _migrate_and_drop(keep_code, drop_codes)
        if apply:
            db.session.commit()
            print("\n✅ done")
        else:
            db.session.rollback()
            print("\nDRY RUN. Add --apply.")

def _migrate_and_drop(keep_code, drop_codes):
    keep = Subject.query.filter_by(subject_code=keep_code).first()
    if not keep:
        print(f"  ✗ keep not found: {keep_code}")
        return
    for drop_code in drop_codes:
        drop = Subject.query.filter_by(subject_code=drop_code).first()
        if not drop:
            print(f"  - already gone: {drop_code}")
            continue
        print(f"  merge [{drop_code}] → [{keep_code}]  ({drop.subject_name})")
        for unit in Unit.query.filter_by(subject_id=drop.id).all():
            unit.subject_id = keep.id
            for qg in QuestionGroup.query.filter_by(unit_id=unit.id).all():
                qg.subject_id = keep.id
            for pa in PartAQuestion.query.filter_by(unit_id=unit.id).all():
                pa.subject_id = keep.id
            for pq in PendingQuestion.query.filter_by(unit_id=unit.id).all():
                pq.subject_id = keep.id
        for qg in QuestionGroup.query.filter_by(subject_id=drop.id).all():
            qg.subject_id = keep.id
        for pa in PartAQuestion.query.filter_by(subject_id=drop.id).all():
            pa.subject_id = keep.id
        for pq in PendingQuestion.query.filter_by(subject_id=drop.id).all():
            pq.subject_id = keep.id
        for gp in GeneratedPaper.query.filter_by(subject_id=drop.id).all():
            gp.subject_id = keep.id
        existing = {l.branch_id for l in BranchSubject.query.filter_by(subject_id=keep.id).all()}
        for link in BranchSubject.query.filter_by(subject_id=drop.id).all():
            if link.branch_id in existing:
                db.session.delete(link)
            else:
                link.subject_id = keep.id
                existing.add(link.branch_id)
        db.session.flush()
        db.session.delete(drop)
        db.session.flush()
        print(f"    ✓ dropped {drop_code}")
    keep.code_pending = False

# ---------------------------------------------------------------------------
# 3. DELETE  (python db_tools.py delete [--apply])
# ---------------------------------------------------------------------------

def cmd_delete(apply):
    with app.app_context():
        deleted, not_found = 0, []
        for code in CODES_TO_DELETE:
            subj = Subject.query.filter_by(subject_code=code).first()
            if not subj:
                not_found.append(code)
                continue
            name = subj.subject_name
            if apply:
                _delete_subject(subj)
                db.session.commit()
                print(f"DELETED: {code} — {name}")
            else:
                print(f"WOULD DELETE: {code} — {name}")
            deleted += 1
        print(f"\nDone. {'Deleted' if apply else 'Would delete'}={deleted}  NotFound={len(not_found)}")
        if not_found:
            print("NOT FOUND:", not_found)
        if not apply:
            print("\nDRY RUN. Add --apply.")

# ---------------------------------------------------------------------------
# 4. FIX-UNITS  (python db_tools.py fix-units [--apply])
# ---------------------------------------------------------------------------

"""
db_tools.py — All one-time DB maintenance utilities in one place.

Usage:
    python db_tools.py dedupe [--apply]              # find & merge duplicate subjects by name
    python db_tools.py dedupe --remove-done-dupes [--apply]
    python db_tools.py merge [--apply]               # migrate drop-codes → keep-codes (PAIRS list)
    python db_tools.py delete [--apply]              # delete CODES_TO_DELETE list
    python db_tools.py fix-units [--apply]           # remove duplicate unit rows
    python db_tools.py remove-labs [--apply]         # delete lab/workshop/project subjects
    python db_tools.py verify [A2501]                # check branch links for a subject code
"""

import re
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app import app
from models import (
    db, Subject, BranchSubject, Unit, PartAQuestion, QuestionGroup,
    QuestionPart, PendingQuestion, GeneratedPaper, PaperUnitSlot
)

# ---------------------------------------------------------------------------
# CONFIG — edit these lists as needed
# ---------------------------------------------------------------------------

# merge: (keep_code, [drop_codes...])
PAIRS = [
    ("A2013", ["A1007", "A2425"]),
    ("A2601", ["A1611", "A1692"]),
    ("A2515", ["A1516", "A1592"]),
    ("A2415", ["A1429"]),
    ("A2524", ["A1528"]),
    ("A1556", ["PEND-CSE-41-C1F22D"]),
    ("A1754", ["PEND-CSE-41-FD99D2"]),
    ("A1574", ["A1669"]),
    ("A1613", ["A1596", "A1466", "PEND-CSE-32-DE0FE2"]),
    ("A1617", ["A1559"]),
    ("A1523", ["A1572", "A1595"]),
    ("A1554", ["A1654", "A1461", "PEND-ECE-41-D81E88"]),
    ("A1615", ["A1553", "PEND-AIML-31-D65D16"]),
    ("A1455", ["A1557"]),
    ("A1425", ["A1492"]),
    ("A1454", ["A1494"]),
    ("A1463", ["A1499"]),
    ("A1470", ["A1495"]),
    ("A1575", ["PEND-AIML-32-C96AB1"]),
    ("A1430", ["PEND-ECE-32-E81A7F"]),
    ("A1691", ["PEND-ECE-41-CE4093"]),
]

# delete: codes to wipe from DB entirely
CODES_TO_DELETE = [
    "A2522", "A2524",
    "PEND-AIML-41-28FFA3", "PEND-AIML-41-A8CF2C", "PEND-AIML-41-D70829",
    "PEND-AIML-41-E61AA9", "PEND-AIML-42-A86973",
    "PEND-CSE-31-37F4BE", "PEND-CSE-32-4DCFDA", "PEND-CSE-32-5BE145",
    "PEND-CSE-32-7F7A9C", "PEND-CSE-32-DD7EB2", "PEND-CSE-32-E361E8",
    "PEND-CSE-41-422D22", "PEND-CSE-41-D7DA98", "PEND-CSE-41-DE19E1",
    "PEND-CSE-42-09935B", "PEND-CSE-42-1491F2", "PEND-CSE-42-19AEB4",
    "PEND-CSE-42-A528B0", "PEND-CSE-42-E4C58E",
    "PEND-ECE-31-7DC2DD", "PEND-ECE-31-A083A1", "PEND-ECE-31-A526B2",
    "PEND-ECE-31-F44833", "PEND-ECE-31-FA969D",
    "PEND-ECE-32-2E86DE", "PEND-ECE-32-DEF5A3",
    "PEND-ECE-41-CE59A6", "PEND-ECE-42-D827B5",
]

# remove-labs: keyword match (same as seed_units.py)
LAB_KEYWORDS = ("lab", "laboratory", "workshop", "project", "internship", "induction", "research project")

# ---------------------------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------------------------

def _normalize(name):
    t = name.lower().strip().replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"[^a-z0-9\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()

def _is_pend(code):
    return bool(code) and code.startswith("PEND-")

def _content_score(s):
    score = 0
    for u in s.units:
        score += PartAQuestion.query.filter_by(unit_id=u.id, is_active=True).count()
        score += QuestionGroup.query.filter_by(unit_id=u.id, is_active=True).count()
        score += PendingQuestion.query.filter_by(unit_id=u.id, status='pending').count()
    return score

def _delete_subject(s):
    """Hard-delete subject + all dependents. No CASCADE configured on FKs."""
    gids = [g.id for g in QuestionGroup.query.filter_by(subject_id=s.id).all()]
    if gids:
        QuestionPart.query.filter(QuestionPart.group_id.in_(gids)).delete(synchronize_session=False)
    QuestionGroup.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    PartAQuestion.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    PendingQuestion.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    pids = [p.id for p in GeneratedPaper.query.filter_by(subject_id=s.id).all()]
    if pids:
        PaperUnitSlot.query.filter(PaperUnitSlot.paper_id.in_(pids)).delete(synchronize_session=False)
    GeneratedPaper.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    Unit.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    BranchSubject.query.filter_by(subject_id=s.id).delete(synchronize_session=False)
    db.session.delete(s)

# ---------------------------------------------------------------------------
# 1. DEDUPE  (python db_tools.py dedupe [--apply] [--remove-done-dupes])
# ---------------------------------------------------------------------------

def cmd_dedupe(apply, remove_done_dupes=False):
    with app.app_context():
        if remove_done_dupes:
            _dedupe_remove_done(apply)
        else:
            _dedupe_run(apply)

def _is_done(s):
    if not s.units:
        return False
    for u in s.units:
        if (PartAQuestion.query.filter_by(unit_id=u.id, is_active=True).count() < 2 or
                QuestionGroup.query.filter_by(unit_id=u.id, is_active=True).count() < 2):
            return False
    return True

def _dedupe_run(apply):
    all_subjects = Subject.query.all()
    groups = defaultdict(list)
    for s in all_subjects:
        groups[_normalize(s.subject_name)].append(s)

    dup_groups = {n: r for n, r in groups.items() if len(r) > 1}
    print(f"Total subjects: {len(all_subjects)}")
    print(f"Duplicate name-groups: {len(dup_groups)}")

    safe, review, ambig = [], [], []

    for name, group in dup_groups.items():
        real_coded = [s for s in group if s.subject_code and not _is_pend(s.subject_code)]
        if len(real_coded) > 1:
            ambig.append((name, group))
            continue
        canonical = (real_coded[0] if len(real_coded) == 1
                     else max(group, key=lambda s: (-_content_score(s), s.id)))
        for s in group:
            if s.id == canonical.id:
                continue
            score = _content_score(s)
            if score == 0 or (_is_pend(s.subject_code) and not _is_pend(canonical.subject_code)):
                safe.append((canonical, s))
            else:
                review.append((name, canonical, s, score))

    print(f"Safe auto-merge: {len(safe)} | Needs review: {len(review)} | Ambiguous: {len(ambig)}")

    if review:
        print("\n--- NEEDS REVIEW ---")
        for name, canonical, dup, score in review:
            print(f"  {name!r}")
            print(f"    keep: {canonical.subject_code:20s} id={canonical.id}")
            print(f"    dup:  {dup.subject_code:20s} id={dup.id}  score={score}")

    if ambig:
        print("\n--- AMBIGUOUS (multiple real codes, same name) ---")
        for name, group in ambig:
            print(f"  {name!r}: {[s.subject_code for s in group]}")

    if not apply:
        print("\nDRY RUN. Add --apply to commit.")
        for canonical, dup in safe:
            print(f"  DELETE {dup.subject_code:20s} -> KEEP {canonical.subject_code}")
        return

    merged = 0
    for canonical, dup in safe:
        try:
            dup_links = db.session.execute(
                text("SELECT id, branch_id, academic_year, semester_number FROM branch_subjects WHERE subject_id = :sid"),
                {"sid": dup.id}
            ).fetchall()
            for link_id, branch_id, dup_year, dup_sem in dup_links:
                existing = db.session.execute(
                    text("SELECT id FROM branch_subjects WHERE branch_id = :bid AND subject_id = :cid"),
                    {"bid": branch_id, "cid": canonical.id}
                ).fetchone()
                if existing:
                    db.session.execute(text("DELETE FROM branch_subjects WHERE id = :lid"), {"lid": link_id})
                else:
                    db.session.execute(text("UPDATE branch_subjects SET subject_id = :cid WHERE id = :lid"),
                                       {"cid": canonical.id, "lid": link_id})
            db.session.execute(text("DELETE FROM units WHERE subject_id = :sid"), {"sid": dup.id})
            db.session.execute(text("DELETE FROM subjects WHERE id = :sid"), {"sid": dup.id})
            db.session.commit()
            merged += 1
        except Exception as e:
            db.session.rollback()
            print(f"  SKIP {dup.subject_name!r} id={dup.id}: {e}")

    print(f"\n✅ Merged {merged}. Left untouched (has content): {len(review)}.")

def _dedupe_remove_done(apply):
    subjects = Subject.query.order_by(Subject.subject_code).all()
    theory = [s for s in subjects if not any(kw in s.subject_name.lower() for kw in LAB_KEYWORDS)]
    done_norms = {_normalize(s.subject_name): s for s in theory if _is_done(s)}
    to_del = [(s, done_norms[_normalize(s.subject_name)])
               for s in theory if not _is_done(s) and _normalize(s.subject_name) in done_norms]
    print(f"DONE subjects: {len(done_norms)} | Will delete: {len(to_del)}")
    for s, keeper in to_del:
        print(f"  DEL {s.subject_code or '(pending)':20s} {s.subject_name} -> keep {keeper.subject_code}")
    if not apply:
        print("\nDRY RUN. Add --apply.")
        return
    deleted = 0
    for s, _ in to_del:
        try:
            _delete_subject(s)
            db.session.commit()
            deleted += 1
        except Exception as e:
            db.session.rollback()
            print(f"  FAIL {s.subject_code}: {e}")
    print(f"\n✅ Deleted {deleted}.")

# ---------------------------------------------------------------------------
# 2. MERGE  (python db_tools.py merge [--apply])
# ---------------------------------------------------------------------------

def cmd_merge(apply):
    with app.app_context():
        print("=== merge ===")
        for keep_code, drop_codes in PAIRS:
            _migrate_and_drop(keep_code, drop_codes)
        if apply:
            db.session.commit()
            print("\n✅ done")
        else:
            db.session.rollback()
            print("\nDRY RUN. Add --apply.")

def _migrate_and_drop(keep_code, drop_codes):
    keep = Subject.query.filter_by(subject_code=keep_code).first()
    if not keep:
        print(f"  ✗ keep not found: {keep_code}")
        return
    for drop_code in drop_codes:
        drop = Subject.query.filter_by(subject_code=drop_code).first()
        if not drop:
            print(f"  - already gone: {drop_code}")
            continue
        print(f"  merge [{drop_code}] → [{keep_code}]  ({drop.subject_name})")
        for unit in Unit.query.filter_by(subject_id=drop.id).all():
            unit.subject_id = keep.id
            for qg in QuestionGroup.query.filter_by(unit_id=unit.id).all():
                qg.subject_id = keep.id
            for pa in PartAQuestion.query.filter_by(unit_id=unit.id).all():
                pa.subject_id = keep.id
            for pq in PendingQuestion.query.filter_by(unit_id=unit.id).all():
                pq.subject_id = keep.id
        for qg in QuestionGroup.query.filter_by(subject_id=drop.id).all():
            qg.subject_id = keep.id
        for pa in PartAQuestion.query.filter_by(subject_id=drop.id).all():
            pa.subject_id = keep.id
        for pq in PendingQuestion.query.filter_by(subject_id=drop.id).all():
            pq.subject_id = keep.id
        for gp in GeneratedPaper.query.filter_by(subject_id=drop.id).all():
            gp.subject_id = keep.id
        existing = {l.branch_id for l in BranchSubject.query.filter_by(subject_id=keep.id).all()}
        for link in BranchSubject.query.filter_by(subject_id=drop.id).all():
            if link.branch_id in existing:
                db.session.delete(link)
            else:
                link.subject_id = keep.id
                existing.add(link.branch_id)
        db.session.flush()
        db.session.delete(drop)
        db.session.flush()
        print(f"    ✓ dropped {drop_code}")
    keep.code_pending = False

# ---------------------------------------------------------------------------
# 3. DELETE  (python db_tools.py delete [--apply])
# ---------------------------------------------------------------------------

def cmd_delete(apply):
    with app.app_context():
        deleted, not_found = 0, []
        for code in CODES_TO_DELETE:
            subj = Subject.query.filter_by(subject_code=code).first()
            if not subj:
                not_found.append(code)
                continue
            name = subj.subject_name
            if apply:
                _delete_subject(subj)
                db.session.commit()
                print(f"DELETED: {code} — {name}")
            else:
                print(f"WOULD DELETE: {code} — {name}")
            deleted += 1
        print(f"\nDone. {'Deleted' if apply else 'Would delete'}={deleted}  NotFound={len(not_found)}")
        if not_found:
            print("NOT FOUND:", not_found)
        if not apply:
            print("\nDRY RUN. Add --apply.")

# ---------------------------------------------------------------------------
# 4. FIX-UNITS  (python db_tools.py fix-units [--apply])
# ---------------------------------------------------------------------------

def cmd_fix_units(apply):
    with app.app_context():
        rows = db.session.execute(text("""
            SELECT subject_id, unit_number, COUNT(*) as cnt
            FROM units
            GROUP BY subject_id, unit_number
            HAVING cnt > 1
        """)).fetchall()

        print(f"Dupe unit groups: {len(rows)}")
        deleted = 0

        for subject_id, unit_number, cnt in rows:
            dupes = db.session.execute(text(
                "SELECT id FROM units WHERE subject_id=:s AND unit_number=:n ORDER BY id"
            ), {"s": subject_id, "n": unit_number}).fetchall()

            keeper_id = dupes[0][0]
            for row in dupes[1:]:
                drop_id = row[0]
                print(f"  MIGRATE unit id={drop_id} -> {keeper_id} (subj={subject_id} unit={unit_number})")
                if apply:
                    for tbl in ("part_a_questions", "question_groups", "pending_questions", "paper_unit_slots"):
                        db.session.execute(text(
                            f"UPDATE {tbl} SET unit_id=:k WHERE unit_id=:d"
                        ), {"k": keeper_id, "d": drop_id})
                    db.session.execute(text("DELETE FROM units WHERE id=:d"), {"d": drop_id})
                    db.session.commit()
                deleted += 1

        if apply:
            print(f"\n✅ Deleted {deleted} dupe units.")
        else:
            print(f"\nDRY RUN — would delete {deleted}. Add --apply.")

# ---------------------------------------------------------------------------
# 5. REMOVE-LABS  (python db_tools.py remove-labs [--apply])
# ---------------------------------------------------------------------------

def cmd_remove_labs(apply):
    with app.app_context():
        subjects = Subject.query.order_by(Subject.subject_code).all()
        to_delete, has_content_skip, kept = [], [], []
        for s in subjects:
            if not any(kw in s.subject_name.lower() for kw in LAB_KEYWORDS):
                kept.append(s)
                continue
            has_content = (PartAQuestion.query.filter_by(subject_id=s.id).first() or
                           QuestionGroup.query.filter_by(subject_id=s.id).first() or
                           PendingQuestion.query.filter_by(subject_id=s.id).first() or
                           GeneratedPaper.query.filter_by(subject_id=s.id).first())
            if has_content:
                has_content_skip.append(s)
            else:
                to_delete.append(s)

        print(f"Total: {len(subjects)} | Theory kept: {len(kept)} | "
              f"Has content (skip): {len(has_content_skip)} | Will delete: {len(to_delete)}")
        if has_content_skip:
            print("\n--- HAS CONTENT, SKIPPING ---")
            for s in has_content_skip:
                print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}")
        print(f"\n--- {'DELETING' if apply else 'WOULD DELETE'} ---")
        for s in to_delete:
            print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}")
        if not apply:
            print("\nDRY RUN. Add --apply.")
            return
        deleted = 0
        for s in to_delete:
            try:
                _delete_subject(s)
                db.session.commit()
                deleted += 1
            except Exception as e:
                db.session.rollback()
                print(f"  FAIL {s.subject_code}: {e}")
        print(f"\n✅ Deleted {deleted} of {len(to_delete)}.")

# ---------------------------------------------------------------------------
# 6. VERIFY  (python db_tools.py verify [subject_code])
# ---------------------------------------------------------------------------

def cmd_verify(code="A2501"):
    with app.app_context():
        s = Subject.query.filter_by(subject_code=code).first()
        if not s:
            print(f"Not found: {code}")
            return
        print(f"{s.subject_name} ({s.subject_code})")
        print(f"Branches: {s.branch_codes()}")
        for link in s.branch_links:
            print(f"  {link.branch.branch_code}: Year {link.academic_year}, "
                  f"Sem {link.semester_number} ({link.get_roman_term()})")

# ---------------------------------------------------------------------------
# DISPATCH
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    apply = "--apply" in args
    cmd = args[0] if args else ""

    if cmd == "dedupe":
        cmd_dedupe(apply, remove_done_dupes="--remove-done-dupes" in args)
    elif cmd == "merge":
        cmd_merge(apply)
    elif cmd == "delete":
        cmd_delete(apply)
    elif cmd == "fix-units":
        cmd_fix_units(apply)
    elif cmd == "remove-labs":
        cmd_remove_labs(apply)
    elif cmd == "verify":
        code = next((a for a in args[1:] if not a.startswith("--")), "A2501")
        cmd_verify(code)
    else:
        print(__doc__)

# ---------------------------------------------------------------------------
# 5. REMOVE-LABS  (python db_tools.py remove-labs [--apply])
# ---------------------------------------------------------------------------

def cmd_remove_labs(apply):
    with app.app_context():
        subjects = Subject.query.order_by(Subject.subject_code).all()
        to_delete, has_content_skip, kept = [], [], []
        for s in subjects:
            if not any(kw in s.subject_name.lower() for kw in LAB_KEYWORDS):
                kept.append(s)
                continue
            has_content = (PartAQuestion.query.filter_by(subject_id=s.id).first() or
                           QuestionGroup.query.filter_by(subject_id=s.id).first() or
                           PendingQuestion.query.filter_by(subject_id=s.id).first() or
                           GeneratedPaper.query.filter_by(subject_id=s.id).first())
            if has_content:
                has_content_skip.append(s)
            else:
                to_delete.append(s)

        print(f"Total: {len(subjects)} | Theory kept: {len(kept)} | "
              f"Has content (skip): {len(has_content_skip)} | Will delete: {len(to_delete)}")
        if has_content_skip:
            print("\n--- HAS CONTENT, SKIPPING ---")
            for s in has_content_skip:
                print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}")
        print(f"\n--- {'DELETING' if apply else 'WOULD DELETE'} ---")
        for s in to_delete:
            print(f"  {s.subject_code or '(pending)':20s} {s.subject_name}")
        if not apply:
            print("\nDRY RUN. Add --apply.")
            return
        deleted = 0
        for s in to_delete:
            try:
                _delete_subject(s)
                db.session.commit()
                deleted += 1
            except Exception as e:
                db.session.rollback()
                print(f"  FAIL {s.subject_code}: {e}")
        print(f"\n✅ Deleted {deleted} of {len(to_delete)}.")

# ---------------------------------------------------------------------------
# 6. VERIFY  (python db_tools.py verify [subject_code])
# ---------------------------------------------------------------------------

def cmd_verify(code="A2501"):
    with app.app_context():
        s = Subject.query.filter_by(subject_code=code).first()
        if not s:
            print(f"Not found: {code}")
            return
        print(f"{s.subject_name} ({s.subject_code})")
        print(f"Branches: {s.branch_codes()}")
        for link in s.branch_links:
            print(f"  {link.branch.branch_code}: Year {link.academic_year}, "
                  f"Sem {link.semester_number} ({link.get_roman_term()})")

# ---------------------------------------------------------------------------
# DISPATCH
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    apply = "--apply" in args
    cmd = args[0] if args else ""

    if cmd == "dedupe":
        cmd_dedupe(apply, remove_done_dupes="--remove-done-dupes" in args)
    elif cmd == "merge":
        cmd_merge(apply)
    elif cmd == "delete":
        cmd_delete(apply)
    elif cmd == "fix-units":
        cmd_fix_units(apply)
    elif cmd == "remove-labs":
        cmd_remove_labs(apply)
    elif cmd == "verify":
        code = next((a for a in args[1:] if not a.startswith("--")), "A2501")
        cmd_verify(code)
    else:
        print(__doc__)