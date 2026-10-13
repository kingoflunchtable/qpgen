import random

from models import db, Subject, Unit, PartAQuestion, QuestionGroup, GeneratedPaper, PaperUnitSlot





def get_important_questions(subject_code, unit_id=None, limit_per_unit=None):
    """
    Returns this subject's Part-A questions and Question Groups, ranked by
    usage_count descending (most frequently selected into generated papers
    first) within each unit. This backs the public "Important Questions"
    lookup page: a question that keeps getting picked across many
    generated papers is a reasonable proxy for "important" without needing
    a separate manual-flagging workflow.

    unit_id        : optional, restricts to a single Unit.
    limit_per_unit : optional int, caps how many of EACH kind (Part-A,
                     Question Group) are returned per unit. None = all.

    Returns: {"success": True, "subject_name":..., "subject_code":...,
              "units": [ {"unit_id":, "unit_name":, "part_a": [...], "groups": [...]} ]}
    Each part_a item: {id, text, bloom, usage_count}
    Each group item:  {group_id, total_marks, question_type, usage_count, parts: [...]}
    """
    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return {"success": False, "error": f"Subject '{subject_code}' not found."}

    units_query = Unit.query.filter_by(subject_id=subject.id)
    if unit_id:
        units_query = units_query.filter_by(id=unit_id)
    units = units_query.order_by(Unit.unit_number).all()

    result_units = []
    for unit in units:
        part_a_pool = PartAQuestion.query.filter_by(
            unit_id=unit.id, is_active=True
        ).order_by(PartAQuestion.usage_count.desc(), PartAQuestion.id.asc()).all()

        group_pool = QuestionGroup.query.filter_by(
            unit_id=unit.id, is_active=True
        ).order_by(QuestionGroup.usage_count.desc(), QuestionGroup.id.asc()).all()

        if limit_per_unit:
            part_a_pool = part_a_pool[:limit_per_unit]
            group_pool = group_pool[:limit_per_unit]

        serialized_groups = []
        for g in group_pool:
            g_dict = _serialize_group(g)
            g_dict["usage_count"] = g.usage_count or 0
            serialized_groups.append(g_dict)

        # Objective questions (MCQ + FIB) for mid exams
        from models import MidObjectiveQuestion
        mcq_pool = MidObjectiveQuestion.query.filter_by(
            unit_id=unit.id, question_type='mcq', is_active=True
        ).order_by(MidObjectiveQuestion.usage_count.desc(), MidObjectiveQuestion.id.asc()).all()
        fib_pool = MidObjectiveQuestion.query.filter_by(
            unit_id=unit.id, question_type='fib', is_active=True
        ).order_by(MidObjectiveQuestion.usage_count.desc(), MidObjectiveQuestion.id.asc()).all()
        if limit_per_unit:
            mcq_pool = mcq_pool[:limit_per_unit]
            fib_pool = fib_pool[:limit_per_unit]

        result_units.append({
            "unit_id": unit.id,
            "unit_name": unit.unit_name,
            "part_a": [
                {"id": q.id, "text": q.question_text, "bloom": q.bloom_level,
                 "usage_count": q.usage_count or 0}
                for q in part_a_pool
            ],
            "groups": serialized_groups,
            "mcq": [
                {"id": q.id, "text": q.question_text, "bloom": q.bloom_level,
                 "usage_count": q.usage_count or 0}
                for q in mcq_pool
            ],
            "fib": [
                {"id": q.id, "text": q.question_text, "bloom": q.bloom_level,
                 "usage_count": q.usage_count or 0}
                for q in fib_pool
            ],
        })

    return {
        "success": True,
        "subject_name": subject.subject_name,
        "subject_code": subject.subject_code,
        "units": result_units,
    }


def generate_paper(subject_code, selected_unit_ids=None, difficulty=None):

    """

    Generates a full paper for the given subject:

      - Part A: 2 PartAQuestion per unit (10 total if all units used)

      - Part B: For each unit, picks 2 DIFFERENT QuestionGroups

                (primary + alternative) to form the "Q OR Q" pair.



    selected_unit_ids : optional list/set of Unit.id to restrict generation to.

                         If None or empty, ALL units for the subject are used

                         (this preserves the original behaviour exactly).

                         NOTE: marks scale with how many units are picked —

                         e.g. picking 3 of 5 units gives 6 Part-A marks and

                         3 Part-B slots instead of the subject's full total.



    difficulty        : optional 'Easy' / 'Medium' / 'Hard' / 'Mixed' (or None).

                         This is a SOFT preference: for each unit we first try

                         to build the OR-pair from QuestionGroups matching this

                         difficulty. If a unit doesn't have a matching pair,

                         we silently fall back to using any difficulty for

                         that unit, so generation never fails purely because

                         of the difficulty filter.



    Returns a dict ready to hand to a template or PDF renderer, and also

    saves the result into generated_papers + paper_unit_slots.

    """

    subject = Subject.query.filter_by(subject_code=subject_code).first()

    if not subject:

        return {"success": False, "error": f"Subject '{subject_code}' not found."}



    all_units = Unit.query.filter_by(subject_id=subject.id).order_by(Unit.unit_number).all()

    if not all_units:

        return {"success": False, "error": "No units found for this subject."}



    if selected_unit_ids:

        selected_unit_ids = set(int(u) for u in selected_unit_ids)

        units = [u for u in all_units if u.id in selected_unit_ids]

        if not units:

            return {"success": False, "error": "None of the selected units belong to this subject."}

    else:

        units = all_units  # original behaviour: use everything



    normalized_difficulty = difficulty if difficulty and difficulty != "Mixed" else None



    # ---------------- PART A ----------------

    part_a_selected = []

    for unit in units:

        pool = PartAQuestion.query.filter_by(unit_id=unit.id, is_active=True).all()

        if len(pool) < 2:

            return {

                "success": False,

                "error": f"Unit '{unit.unit_name}' has fewer than 2 Part-A questions. "

                         f"Add more before generating."

            }

        chosen = random.sample(pool, 2)
        for q in chosen:
            q.usage_count = (q.usage_count or 0) + 1

        part_a_selected.extend(chosen)



    # ---------------- PART B ----------------

    computed_part_a_marks = len(part_a_selected) * 1   # 1 mark each

    # total_marks is finalized after Part B below, once we know real part_b marks



    paper = GeneratedPaper(

        subject_id=subject.id,

        total_marks=subject.total_marks,   # placeholder, corrected below if units were filtered

        requested_difficulty=difficulty,

        selected_unit_ids=[u.id for u in units],

        part_a_question_ids=[q.id for q in part_a_selected],

        status="Draft"

    )

    db.session.add(paper)

    db.session.flush()  # gets paper.id without committing yet



    part_b_slots = []

    errors = []

    computed_part_b_marks = 0



    for position, unit in enumerate(units, start=1):

        base_pool = QuestionGroup.query.filter_by(unit_id=unit.id, is_active=True).all()



        if len(base_pool) < 2:

            errors.append(

                f"Unit '{unit.unit_name}' has fewer than 2 Question Groups "

                f"(found {len(base_pool)}). Cannot build an internal-choice pair."

            )

            continue



        # Try the difficulty-matching pool first (soft preference), fall back to full pool

        pool = base_pool

        if normalized_difficulty:

            filtered = [g for g in base_pool if g.difficulty == normalized_difficulty]

            if len(filtered) >= 2:

                pool = filtered

            # else: not enough at this difficulty -> silently fall back to base_pool



        # Prefer pairing groups with the SAME total_marks, since both sides

        # of an "OR" must be worth equal marks

        marks_buckets = {}

        for g in pool:

            marks_buckets.setdefault(g.total_marks, []).append(g)



        valid_bucket_marks = [m for m, grp in marks_buckets.items() if len(grp) >= 2]



        # If the difficulty-filtered pool couldn't form a pair, retry with the full pool

        if not valid_bucket_marks and pool is not base_pool:

            pool = base_pool

            marks_buckets = {}

            for g in pool:

                marks_buckets.setdefault(g.total_marks, []).append(g)

            valid_bucket_marks = [m for m, grp in marks_buckets.items() if len(grp) >= 2]



        if not valid_bucket_marks:

            errors.append(

                f"Unit '{unit.unit_name}' has no two Question Groups sharing the "

                f"same mark value — cannot pair them as OR."

            )

            continue



        chosen_marks = random.choice(valid_bucket_marks)

        primary, alternative = random.sample(marks_buckets[chosen_marks], 2)



        slot = PaperUnitSlot(

            paper_id=paper.id,

            unit_id=unit.id,

            slot_position=position,

            primary_group_id=primary.id,

            alternative_group_id=alternative.id

        )

        db.session.add(slot)

        part_b_slots.append(slot)

        computed_part_b_marks += chosen_marks



        # track usage for future "avoid repetition" logic

        primary.usage_count = (primary.usage_count or 0) + 1

        alternative.usage_count = (alternative.usage_count or 0) + 1



    if errors:

        db.session.rollback()

        return {"success": False, "error": " | ".join(errors)}



    # Correct total_marks to reflect what was ACTUALLY built (matters when

    # selected_unit_ids is a subset of all units, so marks don't silently

    # claim the subject's full total when fewer units were used).

    paper.total_marks = computed_part_a_marks + computed_part_b_marks

    db.session.commit()



    return {

        "success": True,

        "paper_id": paper.id,

        "subject_name": subject.subject_name,

        "subject_code": subject.subject_code,

        "total_marks": paper.total_marks,

        "duration_minutes": subject.duration_minutes,

        "requested_difficulty": difficulty,

        "units_used": [{"id": u.id, "unit_name": u.unit_name} for u in units],

        "part_a": [

            {"id": q.id, "text": q.question_text, "bloom": q.bloom_level,

             "unit_id": q.unit_id, "unit_name": Unit.query.get(q.unit_id).unit_name}

            for q in part_a_selected

        ],

        "part_b": [

            {

                "slot_position": slot.slot_position,

                "unit_name": Unit.query.get(slot.unit_id).unit_name,

                "primary": _serialize_group(slot.primary_group),

                "alternative": _serialize_group(slot.alternative_group),

            }

            for slot in part_b_slots

        ]

    }





def _serialize_group(group):

    """Helper: turns a QuestionGroup + its parts into a clean dict for rendering."""

    return {

        "group_id": group.id,

        "total_marks": group.total_marks,

        "question_type": group.question_type,

        "parts": [

            {

                "label": p.part_label,

                "text": p.question_text,

                "marks": p.marks,

                "bloom": p.bloom_level

            }

            for p in group.parts

        ]

    }





def get_paper_data_for_export(paper_id):

    """

    Rebuilds the same dict shape that generate_paper() returns, but reads

    directly from the DB for an EXISTING paper_id. This is what the PDF

    export route calls, so any swaps already made are reflected correctly.

    """

    paper = GeneratedPaper.query.get(paper_id)

    if not paper:

        return {"success": False, "error": f"Paper with id {paper_id} not found."}



    subject = Subject.query.get(paper.subject_id)



    part_a_ids = paper.part_a_question_ids or []

    part_a_questions = PartAQuestion.query.filter(PartAQuestion.id.in_(part_a_ids)).all()



    slots = PaperUnitSlot.query.filter_by(paper_id=paper.id).order_by(PaperUnitSlot.slot_position).all()



    used_unit_ids = paper.selected_unit_ids or [s.unit_id for s in slots]

    units_used = Unit.query.filter(Unit.id.in_(used_unit_ids)).order_by(Unit.unit_number).all()



    return {

        "success": True,

        "paper_id": paper.id,

        "subject_name": subject.subject_name,

        "subject_code": subject.subject_code,

        "total_marks": paper.total_marks or subject.total_marks,

        "duration_minutes": subject.duration_minutes,

        "requested_difficulty": paper.requested_difficulty,

        "units_used": [{"id": u.id, "unit_name": u.unit_name} for u in units_used],

        "part_a": [

            {"id": q.id, "text": q.question_text, "bloom": q.bloom_level,

             "unit_id": q.unit_id, "unit_name": Unit.query.get(q.unit_id).unit_name}

            for q in part_a_questions

        ],

        "part_b": [

            {

                "slot_position": slot.slot_position,

                "unit_name": Unit.query.get(slot.unit_id).unit_name,

                "primary": _serialize_group(slot.primary_group),

                "alternative": _serialize_group(slot.alternative_group),

            }

            for slot in slots

        ]

    }





def swap_question_group(paper_id, slot_position, side):

    """

    side = 'primary' or 'alternative'

    Replaces that side of the slot with a different QuestionGroup of the

    same unit and same total_marks, excluding groups already used in this slot.

    """

    slot = PaperUnitSlot.query.filter_by(paper_id=paper_id, slot_position=slot_position).first()

    if not slot:

        return {"success": False, "error": "Slot not found."}



    current_group = slot.primary_group if side == "primary" else slot.alternative_group

    other_group_id = slot.alternative_group_id if side == "primary" else slot.primary_group_id



    candidates = QuestionGroup.query.filter(

        QuestionGroup.unit_id == slot.unit_id,

        QuestionGroup.total_marks == current_group.total_marks,

        QuestionGroup.is_active == True,

        QuestionGroup.id != current_group.id,

        QuestionGroup.id != other_group_id

    ).all()



    if not candidates:

        return {"success": False, "error": "No alternative question available to swap with."}



    new_group = random.choice(candidates)



    if side == "primary":

        slot.primary_group_id = new_group.id

    else:

        slot.alternative_group_id = new_group.id



    db.session.commit()



    return {"success": True, "new_group": _serialize_group(new_group)}

# ======================================================================
# MID EXAM GENERATION
# ======================================================================

from models import MidObjectiveQuestion, GeneratedMidPaper, QuestionPart


def generate_mid_paper(subject_code, mid_number, difficulty=None):
    """
    Generate a 30-mark mid examination paper.

    mid_number: 1 or 2
      Mid-1 covers units 1, 2, and first-half of unit 3
      Mid-2 covers second-half of unit 3, units 4, and 5

    Structure:
      Part-A (10 marks): 10 MCQ (0.5 each) + 10 Fill-in-blank (0.5 each)
      Part-B (20 marks): 6 subjective questions
        Mid-1: 2 from unit1 + 2 from unit2 + 1 from unit3-first-half + 1 random
        Mid-2: 2 from unit4 + 2 from unit5 + 1 from unit3-second-half + 1 random

    Returns dict compatible with render_mid_paper_pdf().
    """
    from models import db, Subject, Unit

    subject = Subject.query.filter_by(subject_code=subject_code).first()
    if not subject:
        return {"success": False, "error": f"Subject '{subject_code}' not found."}

    all_units = Unit.query.filter_by(subject_id=subject.id).order_by(Unit.unit_number).all()
    if len(all_units) < 5:
        return {"success": False, "error": f"Subject needs 5 units, found {len(all_units)}."}

    # Units indexed 0-4 → unit numbers 1-5
    unit_map = {u.unit_number: u for u in all_units}

    if mid_number == 1:
        # Units 1, 2, first-half of unit 3
        primary_units = [unit_map[1], unit_map[2]]
        boundary_unit = unit_map[3]
        boundary_half = 'first'
        all_mid_units = [unit_map[1], unit_map[2], unit_map[3]]
    else:
        # Units 4, 5, second-half of unit 3
        primary_units = [unit_map[4], unit_map[5]]
        boundary_unit = unit_map[3]
        boundary_half = 'second'
        all_mid_units = [unit_map[3], unit_map[4], unit_map[5]]

    # ---- PART A: MCQ ----
    mcq_pool = MidObjectiveQuestion.query.filter(
        MidObjectiveQuestion.subject_id == subject.id,
        MidObjectiveQuestion.unit_id.in_([u.id for u in all_mid_units]),
        MidObjectiveQuestion.question_type == 'mcq',
        MidObjectiveQuestion.is_active == True
    ).all()

    if len(mcq_pool) < 10:
        return {"success": False,
                "error": f"Need 10 MCQ questions for mid-{mid_number}, found {len(mcq_pool)}."}

    mcq_selected = random.sample(mcq_pool, 10)
    for q in mcq_selected:
        q.usage_count = (q.usage_count or 0) + 1

    # ---- PART A: Fill-in-blank ----
    fib_pool = MidObjectiveQuestion.query.filter(
        MidObjectiveQuestion.subject_id == subject.id,
        MidObjectiveQuestion.unit_id.in_([u.id for u in all_mid_units]),
        MidObjectiveQuestion.question_type == 'fib',
        MidObjectiveQuestion.is_active == True
    ).all()

    if len(fib_pool) < 10:
        return {"success": False,
                "error": f"Need 10 FIB questions for mid-{mid_number}, found {len(fib_pool)}."}

    fib_selected = random.sample(fib_pool, 10)
    for q in fib_selected:
        q.usage_count = (q.usage_count or 0) + 1

    # ---- PART B: 6 QuestionGroups (4 Single @ 5M + 2 Compound @ 5M) ----
    # Answer any 4 out of 6, 5M each.
    # Unit coverage: pick from all_mid_units, at least 1 per primary unit.
    part_b_group_ids = []
    part_b_groups = []
    errors = []

    def pick_groups(unit, q_type, count, exclude_ids):
        """Pick QuestionGroups of q_type from unit, excluding already picked."""
        pool = QuestionGroup.query.filter(
            QuestionGroup.subject_id == subject.id,
            QuestionGroup.unit_id == unit.id,
            QuestionGroup.question_type == q_type,
            QuestionGroup.is_active == True,
            QuestionGroup.id.notin_(exclude_ids),
        ).all()
        if difficulty and difficulty != 'Mixed':
            filtered = [g for g in pool if g.difficulty == difficulty]
            if len(filtered) >= count:
                pool = filtered
        if len(pool) < count:
            return None, (f"Unit '{unit.unit_name}' type={q_type}: "
                          f"need {count}, found {len(pool)}.")
        return random.sample(pool, count), None

    # Strategy: 1 Single from each primary unit (2 total), 1 Single from boundary,
    # 1 more Single from any mid unit = 4 Singles.
    # 2 Compound from any mid unit.

    # 1 Single per primary unit
    for unit in primary_units:
        chosen, err = pick_groups(unit, 'Single', 1, part_b_group_ids)
        if err:
            errors.append(err)
            continue
        part_b_groups.extend(chosen)
        part_b_group_ids.extend([g.id for g in chosen])

    # 1 Single from boundary unit
    chosen, err = pick_groups(boundary_unit, 'Single', 1, part_b_group_ids)
    if err:
        errors.append(err)
    else:
        part_b_groups.extend(chosen)
        part_b_group_ids.extend([g.id for g in chosen])

    # 1 more Single from any mid unit (random)
    single_pool = QuestionGroup.query.filter(
        QuestionGroup.subject_id == subject.id,
        QuestionGroup.unit_id.in_([u.id for u in all_mid_units]),
        QuestionGroup.question_type == 'Single',
        QuestionGroup.is_active == True,
        QuestionGroup.id.notin_(part_b_group_ids),
    ).all()
    if not single_pool:
        errors.append("No remaining Single group for 4th Single slot.")
    else:
        g = random.choice(single_pool)
        part_b_groups.append(g)
        part_b_group_ids.append(g.id)

    # 2 Compound from any mid unit
    compound_pool = QuestionGroup.query.filter(
        QuestionGroup.subject_id == subject.id,
        QuestionGroup.unit_id.in_([u.id for u in all_mid_units]),
        QuestionGroup.question_type == 'Compound',
        QuestionGroup.is_active == True,
        QuestionGroup.id.notin_(part_b_group_ids),
    ).all()
    if len(compound_pool) < 2:
        errors.append(f"Need 2 Compound groups, found {len(compound_pool)}.")
    else:
        chosen = random.sample(compound_pool, 2)
        part_b_groups.extend(chosen)
        part_b_group_ids.extend([g.id for g in chosen])

    if errors:
        return {"success": False, "error": " | ".join(errors)}

    # Update usage counts
    for g in part_b_groups:
        g.usage_count = (g.usage_count or 0) + 1

    # Save to DB
    mid_paper = GeneratedMidPaper(
        subject_id=subject.id,
        mid_number=mid_number,
        mcq_question_ids=[q.id for q in mcq_selected],
        fib_question_ids=[q.id for q in fib_selected],
        part_b_group_ids=part_b_group_ids,
        total_marks=30,
        status='Draft',
    )
    db.session.add(mid_paper)
    db.session.commit()

    return {
        "success": True,
        "paper_id": mid_paper.id,
        "paper_type": "mid",
        "mid_number": mid_number,
        "subject_name": subject.subject_name,
        "subject_code": subject.subject_code,
        "total_marks": 30,
        "units_covered": [u.unit_name for u in all_mid_units],
        "part_a_mcq": [_serialize_objective(q) for q in mcq_selected],
        "part_a_fib": [_serialize_objective(q) for q in fib_selected],
        "part_b": [_serialize_mid_group(g) for g in part_b_groups],
    }


def get_mid_paper_data_for_export(paper_id):
    """Rebuild mid paper dict from DB for PDF export."""
    from models import db, Subject, Unit

    paper = GeneratedMidPaper.query.get(paper_id)
    if not paper:
        return {"success": False, "error": f"Mid paper {paper_id} not found."}

    subject = Subject.query.get(paper.subject_id)

    mcq_qs = MidObjectiveQuestion.query.filter(
        MidObjectiveQuestion.id.in_(paper.mcq_question_ids or [])).all()
    fib_qs = MidObjectiveQuestion.query.filter(
        MidObjectiveQuestion.id.in_(paper.fib_question_ids or [])).all()

    group_ids = paper.part_b_group_ids or []
    groups = QuestionGroup.query.filter(QuestionGroup.id.in_(group_ids)).all()

    # Preserve original order
    mcq_map = {q.id: q for q in mcq_qs}
    fib_map = {q.id: q for q in fib_qs}
    group_map = {g.id: g for g in groups}

    mcq_ordered = [mcq_map[i] for i in paper.mcq_question_ids if i in mcq_map]
    fib_ordered = [fib_map[i] for i in paper.fib_question_ids if i in fib_map]
    groups_ordered = [group_map[i] for i in group_ids if i in group_map]

    unit_ids = list({g.unit_id for g in groups_ordered})
    units = Unit.query.filter(Unit.id.in_(unit_ids)).all()

    return {
        "success": True,
        "paper_id": paper.id,
        "paper_type": "mid",
        "mid_number": paper.mid_number,
        "subject_name": subject.subject_name,
        "subject_code": subject.subject_code,
        "total_marks": 30,
        "units_covered": [u.unit_name for u in units],
        "part_a_mcq": [_serialize_objective(q) for q in mcq_ordered],
        "part_a_fib": [_serialize_objective(q) for q in fib_ordered],
        "part_b": [_serialize_mid_group(g) for g in groups_ordered],
    }


def _serialize_objective(q):
    if q.question_type == 'mcq' and q.option_a:
        letters = ['A', 'B', 'C', 'D']
        opts = [q.option_a, q.option_b, q.option_c, q.option_d]
        # find which index holds the correct answer
        correct_idx = letters.index(q.correct_answer.upper()) if q.correct_answer and q.correct_answer.upper() in letters else 0
        correct_text = opts[correct_idx]
        # shuffle options
        random.shuffle(opts)
        # remap correct_answer to new position
        new_correct = letters[opts.index(correct_text)]
        return {
            "id": q.id,
            "question_type": q.question_type,
            "text": q.question_text,
            "option_a": opts[0],
            "option_b": opts[1],
            "option_c": opts[2],
            "option_d": opts[3],
            "correct_answer": new_correct,
            "answer_text": q.answer_text,
            "bloom": q.bloom_level,
            "unit_name": q.unit.unit_name if q.unit else "",
        }
    return {
        "id": q.id,
        "question_type": q.question_type,
        "text": q.question_text,
        "option_a": q.option_a,
        "option_b": q.option_b,
        "option_c": q.option_c,
        "option_d": q.option_d,
        "correct_answer": q.correct_answer,
        "answer_text": q.answer_text,
        "bloom": q.bloom_level,
        "unit_name": q.unit.unit_name if q.unit else "",
    }


def _serialize_mid_group(g):
    """
    Serialize a QuestionGroup for mid Part-B.
    Single  → one entry with 'text' (the part's question_text), marks=5
    Compound → one entry with 'parts': [{label, text, marks}, ...], total marks=5
    PDF renderer checks g['question_type'] to render appropriately.
    """
    unit_name = g.unit.unit_name if g.unit else ""
    bloom = g.parts[0].bloom_level if g.parts else "Understand"
    if g.question_type == 'Single':
        part = g.parts[0] if g.parts else None
        return {
            "id": g.id,
            "question_type": "Single",
            "text": part.question_text if part else "",
            "marks": 5,
            "bloom": bloom,
            "difficulty": g.difficulty,
            "unit_name": unit_name,
        }
    else:  # Compound
        return {
            "id": g.id,
            "question_type": "Compound",
            "text": "",   # not used for compound
            "marks": 5,
            "bloom": bloom,
            "difficulty": g.difficulty,
            "unit_name": unit_name,
            "parts": [
                {
                    "label": p.part_label or "",
                    "text": p.question_text,
                    "marks": p.marks,
                    "bloom": p.bloom_level,
                }
                for p in g.parts
            ],
        }