"""
bulk_parser.py — Parses the manual Admin "bulk paste" text format into a
list of dicts shaped exactly like AI-generated payload_json, so they can be
stored as PendingQuestion rows using the SAME approve/reject code path as
AI-generated questions.

Expected format (case-insensitive section headers, blank lines optional):

[UNIT:1]
[PART-A]
Define an algorithm. | Remember
What is the difference between a constant and a variable in C? | Understand

[PART-B-SINGLE]
Write a C program to find sum and average of array elements. | 10 | Apply | Medium

[PART-B-COMPOUND]
Explain pointer arithmetic with examples. | 5 | Understand | Easy
Differentiate malloc and calloc. | 5 | Understand | Easy

[UNIT:2]
[PART-A]
...

Rules:
- [UNIT:N] is OPTIONAL. If the paste never has one, every question is
  tagged with unit_number=None, and the caller (app.py) falls back to
  whatever single unit_id was chosen in the form — this keeps the
  original one-unit-at-a-time form working unchanged.
- Once a [UNIT:N] marker appears, it's "sticky": every question after it
  belongs to that unit, until the next [UNIT:N] marker switches it.
- N must be a positive integer. A non-numeric or missing N is an error for
  that line only — parsing continues with whatever unit was active before.
- [PART-A] lines:            text | bloom_level
- [PART-B-SINGLE] lines:     text | marks | bloom_level | difficulty
- [PART-B-COMPOUND] lines:   ALWAYS come in pairs (part a, then part b).
                              Each line: text | marks | bloom_level | difficulty
                              The pair's difficulty is taken from the FIRST line.
                              An odd trailing compound line (no pair) is an error
                              for that line, not a crash for the whole paste.
                              A compound pair must stay within the SAME unit —
                              a [UNIT:N] marker between part (a) and part (b) is
                              an error for that dangling part (a), same as
                              switching [SECTION] mid-pair already was.

Difficulty defaults to "Medium" if omitted. Bloom level defaults to
"Understand" if omitted (Part-A defaults to "Remember" if omitted).

Returns: {"part_a": [...], "groups": [...], "errors": [...]}
  - Every item in "part_a" and "groups" now also carries a "unit_number"
    key (int, or None if no [UNIT:N] marker was ever seen before it).
  - "errors" is a list of human-readable strings for any line that couldn't
    be parsed, so the admin form can show "Imported 8 questions, 1 error"
    rather than silently dropping bad lines or crashing on the whole paste.
"""

VALID_BLOOM_LEVELS = {"Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"}
VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}

SECTION_PART_A = "PART-A"
SECTION_SINGLE = "PART-B-SINGLE"
SECTION_COMPOUND = "PART-B-COMPOUND"
KNOWN_SECTIONS = {SECTION_PART_A, SECTION_SINGLE, SECTION_COMPOUND}


def _normalize_bloom(raw, default="Understand"):
    if not raw:
        return default
    raw = raw.strip()
    # Case-insensitive match against known levels, fall back to default if junk
    for level in VALID_BLOOM_LEVELS:
        if raw.lower() == level.lower():
            return level
    return default


def _normalize_difficulty(raw, default="Medium"):
    if not raw:
        return default
    raw = raw.strip()
    for level in VALID_DIFFICULTIES:
        if raw.lower() == level.lower():
            return level
    return default


def parse_bulk_text(raw_text):
    """
    Parses the full bulk-paste text block into part_a + groups lists,
    matching the same shape ai_integration.py produces, plus an "errors"
    list. Every parsed question/group also carries "unit_number" (int or
    None — see [UNIT:N] handling in the module docstring).
    """
    part_a = []
    groups = []
    errors = []

    current_section = None
    current_unit_number = None    # None until a [UNIT:N] marker is seen
    pending_compound_first_line = None   # holds part (a) while waiting for part (b)
    pending_compound_line_no = None
    pending_compound_unit_number = None  # unit the held part (a) belongs to

    lines = raw_text.splitlines()

    def _flush_dangling_compound(reason):
        nonlocal pending_compound_first_line, pending_compound_line_no
        if pending_compound_first_line is not None:
            errors.append(
                f"Line {pending_compound_line_no}: compound question part (a) has no "
                f"matching part (b) {reason} — skipped."
            )
            pending_compound_first_line = None
            pending_compound_line_no = None

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        if not line:
            continue  # blank lines are just spacing, always allowed

        # Unit marker line, e.g. "[UNIT:2]"
        if line.upper().startswith("[UNIT") and line.endswith("]"):
            _flush_dangling_compound("before the next [UNIT] marker started")
            inner = line[1:-1].strip()
            # Accept "[UNIT:2]" or "[UNIT 2]" — be lenient about the separator
            num_part = inner.split(":", 1)[-1] if ":" in inner else inner[4:]
            num_part = num_part.strip()
            try:
                current_unit_number = int(num_part)
            except ValueError:
                errors.append(
                    f"Line {line_no}: '{line}' doesn't have a valid unit number — "
                    f"keeping the previously active unit."
                )
            continue

        # Section header line, e.g. "[PART-A]"
        if line.startswith("[") and line.endswith("]"):
            header = line[1:-1].strip().upper()
            if header in KNOWN_SECTIONS:
                # Switching section while a compound pair was half-built is an
                # error for that dangling line, not a crash.
                if current_section == SECTION_COMPOUND:
                    _flush_dangling_compound("before the next section started")
                current_section = header
            else:
                errors.append(f"Line {line_no}: unknown section header '{line}' — ignored.")
            continue

        if current_section is None:
            errors.append(f"Line {line_no}: text found before any [SECTION] header — ignored: '{line[:60]}'")
            continue

        fields = [f.strip() for f in line.split("|")]

        # ---------------- PART-A ----------------
        if current_section == SECTION_PART_A:
            if len(fields) < 1 or not fields[0]:
                errors.append(f"Line {line_no}: empty Part-A question text — skipped.")
                continue
            text = fields[0]
            bloom = _normalize_bloom(fields[1] if len(fields) > 1 else None, default="Remember")
            part_a.append({
                "question_text": text, "bloom_level": bloom,
                "unit_number": current_unit_number,
            })

        # ---------------- PART-B-SINGLE ----------------
        elif current_section == SECTION_SINGLE:
            if len(fields) < 2 or not fields[0]:
                errors.append(
                    f"Line {line_no}: Single question needs at least 'text | marks' — skipped: '{line[:60]}'"
                )
                continue
            text = fields[0]
            try:
                marks = int(fields[1])
            except ValueError:
                errors.append(f"Line {line_no}: marks '{fields[1]}' is not a number — skipped.")
                continue
            bloom = _normalize_bloom(fields[2] if len(fields) > 2 else None)
            difficulty = _normalize_difficulty(fields[3] if len(fields) > 3 else None)

            groups.append({
                "question_type": "Single",
                "difficulty": difficulty,
                "unit_number": current_unit_number,
                "parts": [
                    {"part_label": None, "part_order": 1, "question_text": text,
                     "marks": marks, "bloom_level": bloom}
                ]
            })

        # ---------------- PART-B-COMPOUND ----------------
        elif current_section == SECTION_COMPOUND:
            if len(fields) < 2 or not fields[0]:
                errors.append(
                    f"Line {line_no}: Compound question part needs at least 'text | marks' — skipped: '{line[:60]}'"
                )
                continue
            text = fields[0]
            try:
                marks = int(fields[1])
            except ValueError:
                errors.append(f"Line {line_no}: marks '{fields[1]}' is not a number — skipped.")
                continue
            bloom = _normalize_bloom(fields[2] if len(fields) > 2 else None)
            difficulty = _normalize_difficulty(fields[3] if len(fields) > 3 else None)

            if pending_compound_first_line is None:
                # This is part (a) — hold it until we see part (b)
                pending_compound_first_line = {
                    "text": text, "marks": marks, "bloom": bloom, "difficulty": difficulty
                }
                pending_compound_line_no = line_no
                pending_compound_unit_number = current_unit_number
            else:
                # This is part (b) — combine with the held part (a)
                a = pending_compound_first_line
                groups.append({
                    "question_type": "Compound",
                    "difficulty": a["difficulty"],  # difficulty comes from part (a)
                    "unit_number": pending_compound_unit_number,
                    "parts": [
                        {"part_label": "a", "part_order": 1, "question_text": a["text"],
                         "marks": a["marks"], "bloom_level": a["bloom"]},
                        {"part_label": "b", "part_order": 2, "question_text": text,
                         "marks": marks, "bloom_level": bloom},
                    ]
                })
                pending_compound_first_line = None
                pending_compound_line_no = None
                pending_compound_unit_number = None

    # If the paste ended mid-compound-pair, flag it rather than silently dropping
    _flush_dangling_compound("at end of input")

    return {"part_a": part_a, "groups": groups, "errors": errors}