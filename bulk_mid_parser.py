"""
bulk_mid_parser.py — Parses bulk-paste text for Mid Exam objective questions
(MCQ + Fill-in-the-blank). Returns structured dicts ready to insert as
MidObjectiveQuestion rows.

Expected format:

[UNIT:1]
[MCQ]
Which of the following is NOT an OOP concept? | Inheritance | Encapsulation | Compilation | Polymorphism | C | Remember
What is the default value of an int in Java? | 0 | null | 1 | undefined | A | Remember

[FILL]
The process of hiding internal details is called ______. | encapsulation | Remember
A class that cannot be instantiated is called an ______ class. | abstract | Remember

[UNIT:2]
[MCQ]
...

Rules:
- [UNIT:N] sets the active unit (sticky until next [UNIT:N]).
- [MCQ] lines:  question_text | optA | optB | optC | optD | correct_letter | bloom
  - correct_letter: A / B / C / D
  - bloom optional (defaults to Remember)
- [FILL] lines: question_text | answer | bloom
  - bloom optional (defaults to Remember)
- Blank lines ignored.

Returns: {"mcq": [...], "fill": [...], "errors": [...]}
Each item has: unit_number, question_text, options (MCQ only), answer, bloom_level, obj_type
"""

VALID_BLOOM_LEVELS = {"Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"}
VALID_ANSWER_LETTERS = {"A", "B", "C", "D"}

SECTION_MCQ = "MCQ"
SECTION_FILL = "FILL"
KNOWN_SECTIONS = {SECTION_MCQ, SECTION_FILL}


def _normalize_bloom(raw, default="Remember"):
    if not raw:
        return default
    raw = raw.strip()
    for level in VALID_BLOOM_LEVELS:
        if raw.lower() == level.lower():
            return level
    return default


def parse_mid_bulk_text(raw_text):
    """
    Parse bulk-pasted mid exam objective questions.
    Returns {"mcq": [...], "fill": [...], "errors": [...]}.
    """
    mcq = []
    fill = []
    errors = []

    current_section = None
    current_unit_number = None

    lines = raw_text.splitlines()

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue

        # [UNIT:N] marker
        if line.upper().startswith("[UNIT") and line.endswith("]"):
            inner = line[1:-1].strip()
            num_part = inner.split(":", 1)[-1] if ":" in inner else inner[4:]
            num_part = num_part.strip()
            try:
                current_unit_number = int(num_part)
            except ValueError:
                errors.append(
                    f"Line {line_no}: invalid unit marker '{line}' — keeping previous unit."
                )
            continue

        # Section header [MCQ] or [FILL]
        if line.startswith("[") and line.endswith("]"):
            header = line[1:-1].strip().upper()
            if header in KNOWN_SECTIONS:
                current_section = header
            else:
                errors.append(f"Line {line_no}: unknown section '{line}' — ignored.")
            continue

        if current_section is None:
            errors.append(f"Line {line_no}: text before any section header — ignored.")
            continue

        if current_unit_number is None:
            errors.append(f"Line {line_no}: text before any [UNIT:N] marker — ignored.")
            continue

        fields = [f.strip() for f in line.split("|")]

        # ---- MCQ ----
        if current_section == SECTION_MCQ:
            # question | optA | optB | optC | optD | correct | bloom?
            if len(fields) < 6:
                errors.append(
                    f"Line {line_no}: MCQ needs at least 6 pipe-fields "
                    f"(question|A|B|C|D|correct) — skipped: '{line[:60]}'"
                )
                continue
            q_text = fields[0]
            opts = [fields[1], fields[2], fields[3], fields[4]]
            correct = fields[5].strip().upper()
            if correct not in VALID_ANSWER_LETTERS:
                errors.append(
                    f"Line {line_no}: answer '{correct}' not in A/B/C/D — skipped."
                )
                continue
            bloom = _normalize_bloom(fields[6] if len(fields) > 6 else None)
            mcq.append({
                "obj_type": "mcq",
                "unit_number": current_unit_number,
                "question_text": q_text,
                "options": opts,
                "answer": correct,
                "bloom_level": bloom,
            })

        # ---- FILL ----
        elif current_section == SECTION_FILL:
            # question | answer | bloom?
            if len(fields) < 2 or not fields[0]:
                errors.append(
                    f"Line {line_no}: Fill needs at least 'question|answer' — skipped: '{line[:60]}'"
                )
                continue
            q_text = fields[0]
            answer = fields[1]
            bloom = _normalize_bloom(fields[2] if len(fields) > 2 else None)
            fill.append({
                "obj_type": "fill",
                "unit_number": current_unit_number,
                "question_text": q_text,
                "options": None,
                "answer": answer,
                "bloom_level": bloom,
            })

    return {"mcq": mcq, "fill": fill, "errors": errors}
