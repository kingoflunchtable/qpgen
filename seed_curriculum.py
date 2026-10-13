"""
seed_curriculum.py — Imports real curriculum data from the three R25 syllabus
PDFs (CSE, AIML, ECE) into Branch / Subject / BranchSubject.

This version adds ELECTIVE IMPORT on top of the previous core-curriculum-only
import. Electives are real, independently searchable Subjects — e.g.
"Computer Vision" for CSE and "Computer Vision" for AIML are two SEPARATE
Subject rows (different branches can teach a same-titled elective slightly
differently, and you want to attach branch-specific questions to each) — but
each is tagged via BranchSubject.elective_group with which slot it satisfies
(e.g. "Professional Elective-III"), so the UI can show that context without
making the option itself non-searchable or hidden behind the slot name.

Real PDF structure (verified against all three files):
- Pages 1-4 each contain exactly two core curriculum tables, for
  "<Year>-Year, Semester-I" and "<Year>-Year, Semester-II" in that order.
  Each table header is: S.No | Course Code | Course Title | L | T | P | Credits
- AIML page 7 and ECE page 6 are a STRAY DUPLICATE of the Year-I page, with
  blank course codes for subjects that already have real codes from page 1.
  These are skipped (matched and ignored by title, not re-imported).
- Year III/IV core tables have a genuinely blank Course Code cell for every
  subject; titles only, no codes assigned in the syllabus yet.
- Some III/IV rows are placeholders pointing at an elective pool (e.g.
  "Professional Elective-I", "Open Elective-II") rather than a real, single
  subject. These rows are captured (not imported as Subjects themselves),
  then matched up with their option pool elsewhere in the document.
- Elective option pools live on later pages, each headed by a slot name line
  immediately followed by a "Course Code  Course Title" header line, with
  each option title on its own line below. No option ever has a real course
  code — they all get a stable pseudo-code, same as title-only Y3/4 subjects.
- Slot name text is INCONSISTENT between the placeholder row and its pool
  header in two ways confirmed across all three PDFs:
    1. Dash variant: "Professional Elective–IV" (en-dash) vs
       "Professional Elective-IV" (hyphen).
    2. Word/numeral order: "Professional Elective-I Lab" (placeholder row)
       vs "Professional Elective Lab-I" (pool header), and CSE uses Roman
       numerals while AIML uses Arabic numerals for the SAME lab slot.
  normalize_slot_name() below collapses all of these to the same key.
"""

import re
import os
import hashlib

import pdfplumber

from app import app
from models import db, Branch, Subject, BranchSubject

ROMAN_TO_INT = {"I": 1, "II": 2, "III": 3, "IV": 4}
INT_TO_ROMAN_WORD = {1: "i", 2: "ii", 3: "iii", 4: "iv", 5: "v", 6: "vi"}

# Matches "I-Year, Semester-I" / "II-Year, Semester-II" / etc. precisely —
# captures the full Roman numeral so there's no substring ambiguity.
HEADER_PATTERN = re.compile(r"(I{1,3}|IV)-Year,\s*Semester-(I{1,2})\b")

# Row text that isn't a real subject — skip outright.
JUNK_TITLES = {"total credits", "induction program"}

# Title prefixes that mark elective-pool placeholder rows rather than a
# single real subject.
ELECTIVE_PREFIXES = ("professional elective", "open elective")

# A slot pool's header line is always exactly this (case-insensitive),
# immediately following the slot name line.
POOL_HEADER_TEXT = "course code course title"


def stable_pending_code(branch_code, academic_year, semester_number, title):
    """
    Deterministic placeholder code for a title-only subject, stable across
    runs. Uses md5 over the normalized title so the SAME subject always
    gets the SAME pseudo-code, every time this script runs.
    """
    normalized = title.strip().lower()
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:6].upper()
    return f"PEND-{branch_code}-{academic_year}{semester_number}-{digest}"


def normalize_slot_name(raw_name):
    """
    Collapses a slot name to a stable matching key, regardless of:
    - dash variant (en-dash vs hyphen vs no dash)
    - whether it's "Professional Elective-I Lab" or "Professional Elective Lab-I"
    - Roman vs Arabic numerals ("IV" vs "4")
    by: lowercasing, stripping punctuation, converting any standalone
    Arabic digit 1-6 to its lowercase Roman-numeral word, then sorting the
    resulting tokens alphabetically (so word order can't cause a mismatch).
    """
    text = raw_name.lower()
    text = text.replace("\u2013", "-").replace("\u2014", "-")  # dash variants -> hyphen
    text = re.sub(r"[^a-z0-9\s-]", "", text)                    # strip stray punctuation
    text = text.replace("-", " ")
    tokens = text.split()

    normalized_tokens = []
    for tok in tokens:
        if tok.isdigit() and int(tok) in INT_TO_ROMAN_WORD:
            normalized_tokens.append(INT_TO_ROMAN_WORD[int(tok)])
        else:
            normalized_tokens.append(tok)

    return " ".join(sorted(normalized_tokens))


def extract_core_tables_with_terms(page):
    """
    Pairs each core curriculum table on this page with its (year, semester)
    label, using document order. Tables that aren't core curriculum tables
    (wrong header shape — elective option pools) are left out entirely.
    """
    text = page.extract_text() or ""
    header_matches = HEADER_PATTERN.findall(text)
    terms = [(ROMAN_TO_INT[y], ROMAN_TO_INT[s]) for y, s in header_matches]

    tables = page.extract_tables()
    core_tables = []
    for table in tables:
        if not table or not table[0]:
            continue
        header = [str(c).replace("\n", " ").strip().lower() if c else "" for c in table[0]]
        if header[0] == "s.no" and len(header) == 7:
            core_tables.append(table)

    if len(core_tables) != len(terms):
        print(f"   ⚠️  Skipping a page for core-table extraction: found "
              f"{len(core_tables)} core table(s) but {len(terms)} year/semester "
              f"header(s) — counts don't match, not guessing which goes with which.")
        return []

    return [(yr, sem, tbl) for (yr, sem), tbl in zip(terms, core_tables)]


def extract_elective_slots_from_page(page):
    """
    Finds every elective slot pool on this page using TEXT LINES rather than
    pdfplumber's table-grid detection — grid detection was confirmed to
    silently mis-parse at least one real short table (missed the column
    split), which would have silently dropped real data. Text-line
    extraction is simpler and verified correct against all three PDFs.

    A slot looks like:
        <Slot Name>
        Course Code    Course Title
        <option 1 title>
        <option 2 title>
        ...
        (blank line, or next slot name, or end of page)

    Returns a list of (slot_name, [option_title, ...]) tuples, in document
    order, for every slot pool found on this page.
    """
    text = page.extract_text() or ""
    lines = [ln.strip() for ln in text.split("\n")]

    slots = []
    i = 0
    while i < len(lines):
        line = lines[i]
        next_line = lines[i + 1] if i + 1 < len(lines) else ""

        if next_line.lower().replace("  ", " ").strip() == POOL_HEADER_TEXT and line:
            slot_name = line
            options = []
            j = i + 2
            while j < len(lines):
                candidate = lines[j].strip()
                if not candidate:
                    j += 1
                    continue
                lookahead = lines[j + 1] if j + 1 < len(lines) else ""
                if lookahead.lower().replace("  ", " ").strip() == POOL_HEADER_TEXT:
                    break
                if candidate.lower() in {"useful links", "text books:", "reference books:"}:
                    break
                options.append(candidate)
                j += 1

            if options:
                slots.append((slot_name, options))
            i = j
        else:
            i += 1

    return slots


def parse_table_rows(table, branch_code, academic_year, semester_number, seen_titles, pending_slots):
    """
    Yields (code, title, code_pending) for each real subject row in one
    core curriculum table. Elective placeholder rows are NOT yielded here —
    they're recorded into pending_slots for later matching against the
    option pools found elsewhere in the document.
    """
    results = []
    for row in table[1:]:
        if not row or len(row) < 7:
            continue

        raw_code = (row[1] or "").strip()
        raw_title = (row[2] or "").replace("\n", " ").strip()

        if not raw_title:
            continue

        title_lower = raw_title.lower()
        if title_lower in JUNK_TITLES:
            continue

        # Skip non-theory subjects (labs, workshops, projects, internships)
        LAB_KEYWORDS = ("lab", "laboratory", "workshop", "project", "internship", "induction")
        if any(kw in title_lower for kw in LAB_KEYWORDS):
            print(f"   ⏭️  Skipping non-theory: '{raw_title}'")
            continue

        if title_lower.startswith(ELECTIVE_PREFIXES):
            pending_slots.append({
                "branch_code": branch_code,
                "academic_year": academic_year,
                "semester_number": semester_number,
                "slot_name_raw": raw_title,
                "slot_key": normalize_slot_name(raw_title),
            })
            print(f"   \U0001F4CC Captured elective placeholder: '{raw_title}' "
                  f"(Yr {academic_year} Sem {semester_number})")
            continue

        if title_lower in seen_titles:
            continue
        seen_titles.add(title_lower)

        if raw_code:
            results.append((raw_code, raw_title, False))
        else:
            code = stable_pending_code(branch_code, academic_year, semester_number, raw_title)
            results.append((code, raw_title, True))

    return results


def parse_syllabus(pdf_path, branch_code):
    """
    Two passes over the same PDF:
      Pass 1 — core curriculum tables -> Subjects + BranchSubject links,
               and collect elective placeholder rows into pending_slots.
      Pass 2 — elective option pools (anywhere in the doc) -> matched
               against pending_slots by normalized slot name, then each
               option imported as its own Subject + tagged BranchSubject.
    """
    with app.app_context():
        branch = Branch.query.filter_by(branch_code=branch_code).first()
        if not branch:
            print(f"Branch {branch_code} not found in database. Skipping parsing.")
            return

        print(f"\nProcessing {pdf_path} for {branch_code}...")
        seen_titles = set()
        pending_slots = []
        all_slot_pools = []   # (slot_name_raw, slot_key, [options])

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # ---- Pass 1 work: core tables on this page ----
                term_tables = extract_core_tables_with_terms(page)
                for academic_year, semester_number, table in term_tables:
                    rows = parse_table_rows(
                        table, branch_code, academic_year, semester_number,
                        seen_titles, pending_slots
                    )
                    for code, title, code_pending in rows:
                        # 1) Try exact code match first (real codes only)
                        subj = Subject.query.filter_by(subject_code=code).first() if not code_pending else None
                        # 2) Fall back: any existing subject with same normalized name (cross-branch dedup)
                        if not subj:
                            norm = re.sub(r'[^a-z0-9 ]', '', title.lower().strip())
                            norm = re.sub(r'\s+', ' ', norm)
                            for candidate in Subject.query.all():
                                cand_norm = re.sub(r'[^a-z0-9 ]', '', candidate.subject_name.lower().strip())
                                cand_norm = re.sub(r'\s+', ' ', cand_norm)
                                if cand_norm == norm:
                                    subj = candidate
                                    # upgrade to real code if we now have one
                                    if not code_pending and subj.code_pending:
                                        subj.subject_code = code
                                        subj.code_pending = False
                                    break
                        if not subj:
                            subj = Subject(
                                subject_code=code,
                                subject_name=title,
                                code_pending=code_pending,
                            )
                            db.session.add(subj)
                            db.session.flush()

                        link = BranchSubject.query.filter_by(
                            branch_id=branch.id, subject_id=subj.id,
                        ).first()
                        if not link:
                            link = BranchSubject(
                                branch_id=branch.id, subject_id=subj.id,
                                academic_year=academic_year,
                                semester_number=semester_number,
                            )
                            db.session.add(link)
                            pending_flag = " (code pending)" if code_pending else ""
                            print(f"   Linked: Yr {academic_year} Sem {semester_number} "
                                  f"| {code} - {title}{pending_flag}")

                # ---- Pass 2 collection: elective pools on this page ----
                # (collected on EVERY page regardless of whether it also had
                # core tables — confirmed both can appear on the same page)
                for slot_name_raw, options in extract_elective_slots_from_page(page):
                    all_slot_pools.append((slot_name_raw, normalize_slot_name(slot_name_raw), options))

            db.session.commit()

        # ---- Now match pending_slots against all_slot_pools and import ----
        pools_by_key = {}
        for slot_name_raw, slot_key, options in all_slot_pools:
            pools_by_key.setdefault(slot_key, (slot_name_raw, options))

        unmatched = []
        for pending in pending_slots:
            match = pools_by_key.get(pending["slot_key"])
            if not match:
                unmatched.append(pending["slot_name_raw"])
                continue

            pool_name_raw, options = match
            for option_title in options:
                option_title = option_title.strip()
                if not option_title:
                    continue

                # Check globally — same elective name across branches shares one Subject row
                norm_opt = re.sub(r'[^a-z0-9 ]', '', option_title.lower().strip())
                norm_opt = re.sub(r'\s+', ' ', norm_opt)
                existing = None
                for candidate in Subject.query.all():
                    cand_norm = re.sub(r'[^a-z0-9 ]', '', candidate.subject_name.lower().strip())
                    cand_norm = re.sub(r'\s+', ' ', cand_norm)
                    if cand_norm == norm_opt:
                        existing = candidate
                        break

                if existing:
                    subj = existing
                else:
                    code = stable_pending_code(
                        branch_code, pending["academic_year"],
                        pending["semester_number"], option_title
                    )
                    subj = Subject(
                        subject_code=code,
                        subject_name=option_title,
                        code_pending=True,
                    )
                    db.session.add(subj)
                    db.session.flush()

                link = BranchSubject.query.filter_by(
                    branch_id=branch.id, subject_id=subj.id,
                ).first()
                if not link:
                    link = BranchSubject(
                        branch_id=branch.id, subject_id=subj.id,
                        academic_year=pending["academic_year"],
                        semester_number=pending["semester_number"],
                        elective_group=pending["slot_name_raw"],
                    )
                    db.session.add(link)
                    print(f"   \U0001F3AF Elective linked: [{pending['slot_name_raw']}] "
                          f"Yr {pending['academic_year']} Sem {pending['semester_number']} "
                          f"| {option_title}")

        db.session.commit()

        if unmatched:
            print(f"\n   \u26A0\uFE0F  {len(unmatched)} elective placeholder(s) had NO matching "
                  f"option pool found in this document: {unmatched}")


def seed_all():
    with app.app_context():
        branches_info = {
            "CSE": "Computer Science and Engineering",
            "AIML": "CSE (Artificial Intelligence & Machine Learning)",
            "ECE": "Electronics and Communication Engineering",
        }

        print("Seeding foundational master branches...")
        for code, name in branches_info.items():
            b = Branch.query.filter_by(branch_code=code).first()
            if not b:
                b = Branch(branch_code=code, branch_name=name)
                db.session.add(b)
                print(f" -> Created missing branch record: {code}")
        db.session.commit()

        files = {
            "R25 B.Tech. CSE Syllabus.pdf": "CSE",
            "R25 B.Tech. AIML Syllabus.pdf": "AIML",
            "R25 B.Tech. ECE Syllabus.pdf": "ECE",
        }

        for filename, code in files.items():
            if os.path.exists(filename):
                parse_syllabus(filename, code)
            else:
                print(f"Warning: File {filename} not found. Skipping.")


if __name__ == '__main__':
    seed_all()