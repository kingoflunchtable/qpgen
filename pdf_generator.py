"""pdf_generator.py — Renders a generated paper into a PDF matching the exact
layout of the Sreyas Institute reference paper (Course Code / Set / Regulation
header box, college name + logo, PART-A table, PART-B with OR internal choice
and a/b sub-parts).

Usage:
    from pdf_generator import render_paper_pdf
    render_paper_pdf(paper_data, output_path="output/paper_123.pdf", **paper_format)

`paper_data` is the exact dict shape returned by generator.generate_paper().
`paper_format` is the dict of person-entered details (exam title, date,
regulation, set number, branch, academic year) collected by the "Format
Paper" step in the UI before download — see app.py's /export-pdf route.
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# Points to the qpgen/ folder (where static/ lives), regardless of cwd
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGO = os.path.join(BASE_DIR, "static", "images", "autonomous.png")

styles = getSampleStyleSheet()

style_normal = ParagraphStyle('normal', parent=styles['Normal'], fontSize=10, leading=13)
style_bold_center = ParagraphStyle('boldCenter', parent=styles['Normal'],
                                    fontSize=12, alignment=TA_CENTER, fontName='Helvetica-Bold')
style_small_center = ParagraphStyle('smallCenter', parent=styles['Normal'],
                                     fontSize=9, alignment=TA_CENTER)
style_italic_center = ParagraphStyle('italicCenter', parent=styles['Normal'],
                                      fontSize=9, alignment=TA_CENTER, fontName='Helvetica-Oblique')
style_question = ParagraphStyle('question', parent=styles['Normal'], fontSize=10, leading=14)
style_or = ParagraphStyle('orLabel', parent=styles['Normal'], fontSize=10,
                           alignment=TA_CENTER, fontName='Helvetica-Bold')
style_right = ParagraphStyle('right', parent=styles['Normal'], fontSize=9, alignment=TA_RIGHT)


ROMAN_NUMERALS = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}


def _unit_no_roman(unit_name):
    if not unit_name:
        return ""
    parts = unit_name.strip().split()
    if parts and parts[-1].isdigit():
        return ROMAN_NUMERALS.get(int(parts[-1]), parts[-1])
    return unit_name


# ----------------------------------------------------------------------
# MAIN ENTRY POINT
# ----------------------------------------------------------------------
def render_paper_pdf(
    paper_data, output_path,
    college_name="Sreyas Institute of Engineering and Technology",
    logo_path=_LOGO,
    regulation="R22",
    set_number=1,
    branch="COMMON TO ALL",
    academic_year_label="I",
    semester_label="I",
    exam_session="Regular/Supplementary",
    exam_month_year="",
    academic_year_range="",
):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=12 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm
    )
    elements = []
    elements.extend(_build_header(
        paper_data, college_name, logo_path, regulation, set_number, branch,
        academic_year_label, semester_label, exam_session, exam_month_year,
        academic_year_range,
    ))
    elements.append(Spacer(1, 8))
    elements.extend(_build_part_a(paper_data))
    elements.append(Spacer(1, 10))
    elements.extend(_build_part_b(paper_data))
    doc.build(elements)
    return output_path


# ----------------------------------------------------------------------
# HEADER
# ----------------------------------------------------------------------
def _build_header(paper_data, college_name, logo_path, regulation, set_number, branch,
                   academic_year_label, semester_label, exam_session, exam_month_year,
                   academic_year_range):
    elements = []

    course_code_cell = Paragraph(f"Course Code : <b>{paper_data.get('subject_code', '')}</b>", style_normal)
    set_reg_cell = Paragraph(
        f"Set: <b>{set_number}</b><br/>Regulation: <b>{regulation}</b>", style_normal
    )
    top_row = Table(
        [[course_code_cell, "", set_reg_cell]],
        colWidths=[60 * mm, 70 * mm, 50 * mm]
    )
    top_row.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.75, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(top_row)

    if logo_path and os.path.exists(logo_path):
        logo = Image(logo_path, width=16 * mm, height=16 * mm)
        logo.hAlign = 'CENTER'
        elements.append(logo)
    elements.append(Paragraph(f"<b>{college_name.upper()}</b>", style_bold_center))
    elements.append(Paragraph("<i>An Autonomous Institution</i>", style_small_center))

    exam_title = (
        f"B.Tech {academic_year_label} Year {semester_label} Semester "
        f"({exam_session}) End Examinations"
    )
    if exam_month_year:
        exam_title += f" {exam_month_year}"
    elements.append(Paragraph(exam_title, style_bold_center))

    if academic_year_range:
        elements.append(Paragraph(f"(For the Academic year {academic_year_range})", style_small_center))

    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"Subject: <b>{paper_data.get('subject_name', '').upper()}</b>", style_bold_center))
    elements.append(Paragraph(f"Branch: <b>{branch.upper()}</b>", style_bold_center))
    elements.append(Spacer(1, 6))

    time_marks_row = Table(
        [[
            Paragraph(f"Time: {paper_data.get('duration_minutes', 180) // 60}:00 Hours", style_normal),
            Paragraph(f"Max. Marks: {paper_data.get('total_marks', 60)}", style_right)
        ]],
        colWidths=[90 * mm, 90 * mm]
    )
    elements.append(time_marks_row)
    elements.append(Spacer(1, 4))

    note = Paragraph(
        "<b>Note:</b> This Question Paper Contains two parts A &amp; B.<br/>"
        "1) Answer ALL questions from <b>PART-A</b><br/>"
        "2) Answer any five questions choosing at least one from each Unit in <b>PART-B</b>",
        style_normal
    )
    elements.append(note)
    return elements


# ----------------------------------------------------------------------
# PART A
# ----------------------------------------------------------------------
def _build_part_a(paper_data):
    elements = []
    elements.append(Paragraph("<b>PART-A [MARKS: 10]</b>", style_bold_center))
    elements.append(Spacer(1, 4))

    part_a = paper_data.get("part_a", [])
    instruction_row = Table(
        [[
            Paragraph("<i>Answer All the Questions. All Questions carry equal marks</i>", style_normal),
            Paragraph(f"<b>{len(part_a)}X1={len(part_a)} Marks</b>", style_right),
        ]],
        colWidths=[140 * mm, 40 * mm]
    )
    elements.append(instruction_row)
    elements.append(Spacer(1, 4))

    table_data = [["S.No", "Unit\nNo.", "Question", "Marks", "Bloom's\nLevel"]]
    for i, q in enumerate(part_a, start=1):
        table_data.append([
            str(i),
            _unit_no_roman(q.get("unit_name", "")),
            Paragraph(q["text"], style_question),
            "1 Mark",
            _bloom_short(q.get("bloom", ""))
        ])

    table = Table(table_data, colWidths=[10 * mm, 14 * mm, 116 * mm, 18 * mm, 20 * mm])
    table.setStyle(_default_table_style(num_cols=5))
    elements.append(table)
    return elements


# ----------------------------------------------------------------------
# PART B
# ----------------------------------------------------------------------
def _build_part_b(paper_data):
    elements = []
    elements.append(Paragraph("<b>PART-B [MARKS: 50]</b>", style_bold_center))
    elements.append(Spacer(1, 6))

    part_b = paper_data.get("part_b", [])
    q_number = 11

    for slot in part_b:
        unit_roman = _unit_no_roman(slot["unit_name"])
        elements.append(_render_group_block(q_number, unit_roman, slot["primary"]))
        q_number += 1
        elements.append(Spacer(1, 2))
        elements.append(Paragraph("OR", style_or))
        elements.append(Spacer(1, 2))
        elements.append(_render_group_block(q_number, unit_roman, slot["alternative"]))
        q_number += 1
        elements.append(Spacer(1, 8))

    return elements


def _render_group_block(q_number, unit_roman, group):
    rows = []
    if group["question_type"] == "Single":
        part = group["parts"][0]
        rows.append([
            f"{q_number}", unit_roman,
            Paragraph(part["text"], style_question),
            f"{part['marks']} Marks",
            _bloom_short(part.get("bloom", ""))
        ])
    else:
        for idx, part in enumerate(group["parts"]):
            label = part.get("label") or ""
            text = f"<b>{label}.</b> {part['text']}" if label else part["text"]
            rows.append([
                f"{q_number}" if idx == 0 else "",
                unit_roman if idx == 0 else "",
                Paragraph(text, style_question),
                f"{part['marks']} Marks",
                _bloom_short(part.get("bloom", ""))
            ])
    table = Table(rows, colWidths=[10 * mm, 14 * mm, 116 * mm, 18 * mm, 20 * mm])
    table.setStyle(_default_table_style(num_cols=5))
    return table


def _default_table_style(num_cols=5):
    style = TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (max(1, num_cols - 2), 0), (-1, -1), 'CENTER'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.whitesmoke),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ])
    return style


def _bloom_short(bloom_level):
    mapping = {
        "Remember": "1", "Understand": "2", "Apply": "3",
        "Analyze": "4", "Evaluate": "5", "Create": "6"
    }
    return mapping.get(bloom_level, "")


# ----------------------------------------------------------------------
# IMPORTANT QUESTIONS PDF
# ----------------------------------------------------------------------
def render_important_questions_pdf(data, output_path,
                                     college_name="Sreyas Institute of Engineering and Technology"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm
    )
    elements = []
    elements.append(Paragraph(f"<b>{college_name}</b>", style_bold_center))
    elements.append(Paragraph("<i>Important Questions — For Student Preparation</i>", style_small_center))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
        f"<b>Subject:</b> {data.get('subject_name', '').upper()} "
        f"({data.get('subject_code', '')})", style_bold_center
    ))
    elements.append(Spacer(1, 10))

    for unit in data.get("units", []):
        elements.append(Paragraph(f"<b>{unit['unit_name']}</b>", style_question))
        elements.append(Spacer(1, 4))
        q_number = 1

        if unit.get("part_a"):
            elements.append(Paragraph("Part-A Questions", style_small_center))
            elements.append(Spacer(1, 2))
            rows = [["S.No", "Question", "Bloom's Level"]]
            for q in unit["part_a"]:
                rows.append([str(q_number), Paragraph(q["text"], style_question), _bloom_short(q.get("bloom", ""))])
                q_number += 1
            table = Table(rows, colWidths=[12 * mm, 148 * mm, 20 * mm])
            table.setStyle(_default_table_style(num_cols=3))
            elements.append(table)
            elements.append(Spacer(1, 10))

        if unit.get("groups"):
            elements.append(Paragraph("Part-B Questions", style_small_center))
            elements.append(Spacer(1, 2))
            rows = [["S.No", "Question", "Marks", "Bloom's\nLevel"]]
            for group in unit["groups"]:
                if group["question_type"] == "Single":
                    part = group["parts"][0]
                    rows.append([str(q_number), Paragraph(part["text"], style_question),
                                 f"{part['marks']}", _bloom_short(part.get("bloom", ""))])
                    q_number += 1
                else:
                    for idx, part in enumerate(group["parts"]):
                        label = part.get("label") or ""
                        number_cell = str(q_number) if idx == 0 else ""
                        text = f"<b>{label}.</b> {part['text']}" if label else part["text"]
                        rows.append([number_cell, Paragraph(text, style_question),
                                     f"{part['marks']}", _bloom_short(part.get("bloom", ""))])
                    q_number += 1
            table = Table(rows, colWidths=[12 * mm, 130 * mm, 18 * mm, 20 * mm])
            table.setStyle(_default_table_style(num_cols=4))
            elements.append(table)

        elements.append(Spacer(1, 14))

    doc.build(elements)
    return output_path


# ======================================================================
# MID EXAM PAPER PDF RENDERER
# ======================================================================

def render_mid_paper_pdf(
    paper_data, output_path,
    college_name="Sreyas Institute of Engineering and Technology",
    logo_path=_LOGO,
    regulation="R22",
    set_number=1,
    branch="COMMON TO ALL",
    academic_year_label="I",
    semester_label="I",
    exam_session="Regular",
    exam_month_year="",
    academic_year_range="",
):
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=12 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm
    )
    elements = []
    mid_num = paper_data.get("mid_number", 1)

    # CIE header (same as separate obj/subj PDFs)
    elements.extend(_build_cie_header(
        paper_data, college_name, logo_path, mid_num,
        regulation, branch, exam_month_year, academic_year_range,
        time_str="1:30 Hours", max_marks=30, set_number=set_number,
        show_hall_ticket=False
    ))
    elements.append(Spacer(1, 4))

    # Note
    units_covered = ", ".join(paper_data.get("units_covered", []))
    note = Paragraph(
        "<b>Note:</b> This Question Paper Contains two parts <b>A &amp; B</b>.<br/>"
        f"Units Covered: <b>{units_covered}</b><br/>"
        "1) <b>PART-A</b>: Answer ALL Questions (10 MCQ + 10 Fill-in-the-Blanks) — 10 Marks<br/>"
        "2) <b>PART-B</b>: Answer any <b>Four</b> questions out of <b>Six</b>. "
        "Each question carries 5 marks and may have <b>a, b</b> as sub Questions.",
        style_normal
    )
    elements.append(note)
    elements.append(Spacer(1, 6))

    elements.extend(_build_mid_part_a_cie(paper_data))
    elements.append(Spacer(1, 8))
    elements.extend(_build_mid_part_b_cie(paper_data))
    doc.build(elements)
    return output_path


def _build_mid_header(paper_data, college_name, logo_path, regulation, set_number, branch,
                       academic_year_label, semester_label, exam_session, exam_month_year,
                       academic_year_range):
    elements = []
    mid_num = paper_data.get("mid_number", 1)
    mid_label = f"Mid-{mid_num}"

    top_row = Table(
        [[
            Paragraph(f"Course Code : <b>{paper_data.get('subject_code', '')}</b>", style_normal),
            "",
            Paragraph(f"Set: <b>{set_number}</b><br/>Regulation: <b>{regulation}</b>", style_normal),
        ]],
        colWidths=[60 * mm, 70 * mm, 50 * mm]
    )
    top_row.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.75, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(top_row)

    if logo_path and os.path.exists(logo_path):
        logo_img = Image(logo_path, width=18 * mm, height=18 * mm)
        header_row = Table(
            [[logo_img, Paragraph(f"<b>{college_name.upper()}</b><br/><i>An Autonomous Institution</i>", style_bold_center), ""]],
            colWidths=[22 * mm, 136 * mm, 22 * mm]
        )
        header_row.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ]))
        elements.append(header_row)
    else:
        elements.append(Paragraph(f"<b>{college_name.upper()}</b>", style_bold_center))
        elements.append(Paragraph("<i>An Autonomous Institution</i>", style_small_center))

    exam_title = (
        f"B.Tech {academic_year_label} Year {semester_label} Semester "
        f"({exam_session}) {mid_label} Examinations"
    )
    if exam_month_year:
        exam_title += f" {exam_month_year}"
    elements.append(Paragraph(exam_title, style_bold_center))

    if academic_year_range:
        elements.append(Paragraph(f"(For the Academic year {academic_year_range})", style_small_center))

    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"Subject: <b>{paper_data.get('subject_name', '').upper()}</b>", style_bold_center))
    elements.append(Paragraph(f"Branch: <b>{branch.upper()}</b>", style_bold_center))
    elements.append(Spacer(1, 6))

    time_marks_row = Table(
        [[
            Paragraph("Time: 1:30 Hours", style_normal),
            Paragraph("Max. Marks: 30", style_right),
        ]],
        colWidths=[90 * mm, 90 * mm]
    )
    elements.append(time_marks_row)
    elements.append(Spacer(1, 4))

    units_covered = ", ".join(paper_data.get("units_covered", []))
    note = Paragraph(
        f"<b>Note:</b> This Question Paper Contains two parts A &amp; B.<br/>"
        f"Units Covered: <b>{units_covered}</b><br/>"
        "1) <b>PART-A</b>: Answer ALL Questions (10 MCQ + 10 Fill-in-the-Blanks) — 10 Marks<br/>"
        "2) <b>PART-B</b>: Answer ALL 6 Questions — 20 Marks",
        style_normal
    )
    elements.append(note)
    return elements


def _build_mid_part_a(paper_data, show_key=False):
    elements = []
    elements.append(Paragraph("<b>PART-A [MARKS: 10]</b>", style_bold_center))
    elements.append(Spacer(1, 4))

    mcq_list = paper_data.get("part_a_mcq", [])
    fib_list = paper_data.get("part_a_fib", [])

    elements.append(Paragraph("<b>Section I: Multiple Choice Questions</b>", style_question))
    elements.append(Paragraph(
        "<i>Choose the correct answer. Each question carries 0.5 marks.</i>  "
        f"<b>10 × 0.5 = 5 Marks</b>", style_normal))
    elements.append(Spacer(1, 4))

    for i, q in enumerate(mcq_list, start=1):
        elements.append(Paragraph(f"<b>{i}.</b> {q['text']}", style_question))
        if q.get("option_a"):
            opts = Table(
                [[
                    Paragraph(f"(A) {q.get('option_a','')}", style_normal),
                    Paragraph(f"(B) {q.get('option_b','')}", style_normal),
                    Paragraph(f"(C) {q.get('option_c','')}", style_normal),
                    Paragraph(f"(D) {q.get('option_d','')}", style_normal),
                ]],
                colWidths=[43 * mm, 43 * mm, 43 * mm, 43 * mm]
            )
            opts.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ]))
            elements.append(opts)
        if show_key and q.get('correct_answer'):
            elements.append(Paragraph(f"<i>Ans: ({q['correct_answer']})</i>", style_normal))
        elements.append(Spacer(1, 3))

    elements.append(Spacer(1, 6))

    elements.append(Paragraph("<b>Section II: Fill in the Blanks</b>", style_question))
    elements.append(Paragraph(
        "<i>Fill in the blanks. Each question carries 0.5 marks.</i>  "
        f"<b>10 × 0.5 = 5 Marks</b>", style_normal))
    elements.append(Spacer(1, 4))

    for i, q in enumerate(fib_list, start=1):
        elements.append(Paragraph(f"<b>{i + 10}.</b> {q['text']}", style_question))
        if show_key and q.get('answer'):
            elements.append(Paragraph(f"<i>Ans: {q['answer']}</i>", style_normal))
        elements.append(Spacer(1, 3))

    return elements


def _build_mid_part_b(paper_data):
    elements = []
    elements.append(Paragraph("<b>PART-B [MARKS: 20]</b>", style_bold_center))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        "<i>Answer any 4 out of 6 Questions. Each question carries 5 Marks.</i>",
        style_normal))
    elements.append(Spacer(1, 6))

    part_b = paper_data.get("part_b", [])
    rows = [["Q.No", "Unit", "Question", "Marks", "Bloom's\nLevel"]]
    q_num = 1
    for q in part_b:
        unit_cell = _unit_no_roman(q.get("unit_name", ""))
        bloom_cell = _bloom_short(q.get("bloom", ""))
        q_type = q.get("question_type", "Single")

        if q_type == "Compound":
            parts = q.get("parts", [])
            if parts:
                for idx, p in enumerate(parts):
                    label = p.get("label", "")
                    text = f"({label}) {p['text']}" if label else p["text"]
                    rows.append([
                        str(q_num) if idx == 0 else "",
                        unit_cell if idx == 0 else "",
                        Paragraph(text, style_question),
                        "2.5",
                        _bloom_short(p.get("bloom", "")),
                    ])
            else:
                rows.append([str(q_num), unit_cell,
                              Paragraph("(compound question)", style_question),
                              "5", bloom_cell])
        else:
            rows.append([
                str(q_num), unit_cell,
                Paragraph(q.get("text", ""), style_question),
                "5", bloom_cell,
            ])
        q_num += 1

    table = Table(rows, colWidths=[10 * mm, 14 * mm, 116 * mm, 18 * mm, 20 * mm])
    table.setStyle(_default_table_style(num_cols=5))
    elements.append(table)
    return elements


def render_mid_objective_pdf(paper_data, output_path,
                              college_name="Sreyas Institute of Engineering and Technology",
                              logo_path=_LOGO,
                              show_key=False,
                              regulation="R22", branch="CSE",
                              exam_month_year="", academic_year_range="",
                              set_number=1):
    """Export Part-A (MCQ + FIB) with full CIE header matching reference paper."""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            topMargin=12*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    elements = []
    mid_num = paper_data.get('mid_number', 1)
    elements.extend(_build_cie_header(
        paper_data, college_name, logo_path, mid_num,
        regulation, branch, exam_month_year, academic_year_range,
        time_str="20 Min.", max_marks=10, set_number=set_number,
        show_hall_ticket=True
    ))
    # Note row
    note_data = [[Paragraph(
        "<b>PART-A [MARKS: 10]</b> (All questions carry equal marks)",
        style_bold_center
    )]]
    note_tbl = Table(note_data, colWidths=[180*mm])
    note_tbl.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.75,colors.black),
        ('TOPPADDING',(0,0),(-1,-1),4),
        ('BOTTOMPADDING',(0,0),(-1,-1),4),
    ]))
    elements.append(note_tbl)
    elements.append(Spacer(1, 6))
    elements.extend(_build_mid_part_a_cie(paper_data, show_key=show_key))
    doc.build(elements)
    return output_path


def render_mid_subjective_pdf(paper_data, output_path,
                               college_name="Sreyas Institute of Engineering and Technology",
                               logo_path=_LOGO,
                               regulation="R22", branch="CSE",
                               exam_month_year="", academic_year_range="",
                               set_number=1):
    """Export Part-B (subjective) with full CIE header matching reference paper."""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            topMargin=12*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    elements = []
    mid_num = paper_data.get('mid_number', 1)
    elements.extend(_build_cie_header(
        paper_data, college_name, logo_path, mid_num,
        regulation, branch, exam_month_year, academic_year_range,
        time_str="2 Hours", max_marks=20, set_number=set_number,
        show_hall_ticket=False
    ))
    elements.append(Spacer(1, 4))
    # Note
    note = Paragraph(
        "<b>Note:</b> This Question Paper Contains <b>PART-B</b> only.<br/>"
        "Answer any <b>Four</b> questions out of <b>Six</b>. "
        "Each question carries 5 marks and may have <b>a, b</b> as sub Questions.",
        style_normal
    )
    elements.append(note)
    elements.append(Spacer(1, 6))
    elements.extend(_build_mid_part_b_cie(paper_data))
    doc.build(elements)
    return output_path


# ======================================================================
# HELPER: Build CIE-style header table (matches reference paper exactly)
# ======================================================================
def _build_cie_header(paper_data, college_name, logo_path, mid_num,
                       regulation, branch, exam_month_year, academic_year_range,
                       time_str, max_marks, set_number, show_hall_ticket=False):
    """
    Builds the full bordered CIE header block matching reference PDFs.
    Returns list of flowables.
    """
    elements = []

    # --- Logo + college name row ---
    if logo_path and os.path.exists(logo_path):
        logo_img = Image(logo_path, width=18*mm, height=18*mm)
        hrow = Table(
            [[logo_img, Paragraph(
                f"<b>{college_name}</b><br/>"
                f"<i>An Autonomous Institution</i><br/>"
                f"<font size=7>Approved by AICTE, Affiliated to JNTUH<br/>"
                f"Accredited by NAAC-A Grade, NBA (CSE, ECE &amp; ME) &amp; ISO 9001:2015 Certified</font>",
                ParagraphStyle('hdr', parent=styles['Normal'], fontSize=13,
                               fontName='Helvetica-Bold', alignment=TA_LEFT, leading=16)
            )]],
            colWidths=[24*mm, 156*mm]
        )
        hrow.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
        elements.append(hrow)
    else:
        elements.append(Paragraph(f"<b>{college_name}</b>", style_bold_center))

    elements.append(Spacer(1, 4))

    # Horizontal rule
    from reportlab.platypus import HRFlowable
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.black))
    elements.append(Spacer(1, 2))

    # Big title box
    exam_title = f"CONTINUOUS INTERNAL EVALUATION-{['I','II','III'][mid_num-1] if mid_num <= 3 else str(mid_num)}"
    elements.append(Paragraph(f"<b>{exam_title}</b>", style_bold_center))
    if exam_month_year or academic_year_range:
        sub = f"{exam_month_year}" + (f" – Academic Year {academic_year_range}" if academic_year_range else "")
        elements.append(Paragraph(sub, style_small_center))

    elements.append(Spacer(1, 3))

    # Row 1: Program | Branch | Year&Sem | Hall Ticket (if show)
    if show_hall_ticket:
        r1 = Table([[
            Paragraph(f"Program: B.Tech<br/>{regulation} Regulation", style_normal),
            Paragraph(f"Branch: {branch}", style_normal),
            Paragraph("Year &amp; Sem: II-II", style_normal),
            Paragraph("<b>HALL TICKET NO:</b>", style_normal),
            ""  # boxes for hall ticket
        ]], colWidths=[38*mm, 35*mm, 35*mm, 35*mm, 37*mm])
        r1.setStyle(TableStyle([
            ('BOX',(0,0),(-1,-1),0.75,colors.black),
            ('INNERGRID',(0,0),(-1,-1),0.75,colors.black),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),4),
            ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]))
    else:
        r1 = Table([[
            Paragraph(f"Program: B.Tech - {regulation} Regulation", style_normal),
            Paragraph(f"Branch: {branch}", style_normal),
            Paragraph("Year &amp; Sem: II-II", style_normal),
        ]], colWidths=[60*mm, 60*mm, 60*mm])
        r1.setStyle(TableStyle([
            ('BOX',(0,0),(-1,-1),0.75,colors.black),
            ('INNERGRID',(0,0),(-1,-1),0.75,colors.black),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),4),
            ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]))
    elements.append(r1)

    # Row 2: Date | Time | MaxMarks
    exam_date = paper_data.get('exam_date', '')
    r2 = Table([[
        Paragraph(f"{'Date of Exam: ' + exam_date if exam_date else 'Date of Exam:'}", style_normal),
        Paragraph(f"Time: {time_str}", style_normal),
        Paragraph(f"Max. Marks: {max_marks}", style_normal),
    ]], colWidths=[60*mm, 60*mm, 60*mm])
    r2.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.75,colors.black),
        ('INNERGRID',(0,0),(-1,-1),0.75,colors.black),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),4),
        ('BOTTOMPADDING',(0,0),(-1,-1),4),
    ]))
    elements.append(r2)

    # Row 3: Subject Code | Subject Name | Set No
    r3 = Table([[
        Paragraph("Subject Code", style_normal),
        Paragraph(f"Subject: <b>{paper_data.get('subject_name','').upper()}</b>", style_bold_center),
        Paragraph("Set No.", style_normal),
    ],[
        Paragraph(f"<b>{paper_data.get('subject_code','')}</b>", style_bold_center),
        Paragraph("", style_normal),
        Paragraph(f"<b>{set_number}</b>", style_bold_center),
    ]], colWidths=[25*mm, 130*mm, 25*mm])
    r3.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.75,colors.black),
        ('INNERGRID',(0,0),(-1,-1),0.75,colors.black),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('SPAN',(1,0),(1,1)),
        ('TOPPADDING',(0,0),(-1,-1),3),
        ('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
    ]))
    elements.append(r3)

    return elements




# ======================================================================
# CIE-style Part-A builder (MCQ with [ ], FIB plain)
# ======================================================================
def _build_mid_part_a_cie(paper_data, show_key=False):
    elements = []
    mcq_list = paper_data.get("part_a_mcq", [])
    fib_list = paper_data.get("part_a_fib", [])

    # --- Section I: MCQ ---
    elements.append(Paragraph("<b>I.&nbsp;&nbsp;Choose the correct alternative.</b>", style_question))
    elements.append(Spacer(1, 4))

    for i, q in enumerate(mcq_list, start=1):
        # Question row with [ ] on right
        q_row = Table([[
            Paragraph(f"<b>{i}</b>", style_normal),
            Paragraph(q['text'], style_question),
            Paragraph("[ &nbsp;&nbsp; ]", style_normal),
        ]], colWidths=[8*mm, 158*mm, 14*mm])
        q_row.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),2),
            ('RIGHTPADDING',(0,0),(-1,-1),2),
            ('TOPPADDING',(0,0),(-1,-1),2),
            ('BOTTOMPADDING',(0,0),(-1,-1),1),
        ]))
        elements.append(q_row)

        # Options row (4 columns)
        if q.get("option_a"):
            opts = Table([[
                Paragraph(f"A) {q.get('option_a','')}", style_normal),
                Paragraph(f"B) {q.get('option_b','')}", style_normal),
                Paragraph(f"C) {q.get('option_c','')}", style_normal),
                Paragraph(f"D) {q.get('option_d','')}", style_normal),
            ]], colWidths=[43*mm, 43*mm, 43*mm, 43*mm])
            opts.setStyle(TableStyle([
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LEFTPADDING',(0,0),(-1,-1),6),
                ('TOPPADDING',(0,0),(-1,-1),1),
                ('BOTTOMPADDING',(0,0),(-1,-1),3),
            ]))
            elements.append(opts)

        if show_key and q.get('correct_answer'):
            elements.append(Paragraph(f"<i>Ans: ({q['correct_answer']})</i>", style_normal))
        elements.append(Spacer(1, 3))

    elements.append(Spacer(1, 6))

    # --- Section II: FIB ---
    elements.append(Paragraph("<b>II&nbsp;&nbsp;Fill in the blanks:</b>", style_question))
    elements.append(Spacer(1, 4))

    for i, q in enumerate(fib_list, start=1):
        fib_row = Table([[
            Paragraph(f"<b>{i}</b>", style_normal),
            Paragraph(q['text'], style_question),
        ]], colWidths=[8*mm, 172*mm])
        fib_row.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),2),
            ('TOPPADDING',(0,0),(-1,-1),2),
            ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]))
        elements.append(fib_row)
        if show_key and q.get('answer'):
            elements.append(Paragraph(f"<i>Ans: {q['answer']}</i>", style_normal))

    return elements


# ======================================================================
# CIE-style Part-B builder (Q numbered 1-6, with CO/BTL/Marks columns)
# ======================================================================
def _build_mid_part_b_cie(paper_data):
    elements = []
    elements.append(Paragraph("<b>PART-B [MARKS: 20]</b>", style_bold_center))
    elements.append(Spacer(1, 4))

    part_b = paper_data.get("part_b", [])

    rows = [["", "CO's", "BTL", "Marks"]]
    q_num = 1
    for q in part_b:
        bloom_btl = q.get("bloom", "")
        btl_num = _bloom_short(bloom_btl) or "2"
        co = q.get("co", "CO1")
        q_type = q.get("question_type", "Single")

        if q_type == "Compound":
            parts = q.get("parts", [])
            if parts:
                for idx, p in enumerate(parts):
                    label = p.get("label", chr(96 + idx + 1))  # a, b
                    text = f"{label})&nbsp;&nbsp;{p['text']}"
                    p_co = p.get("co", co)
                    p_btl = _bloom_short(p.get("bloom", bloom_btl)) or btl_num
                    rows.append([
                        Paragraph(f"{'<b>' + str(q_num) + '</b>' if idx == 0 else ''}", style_normal),
                        Paragraph(text, style_question),
                        p_co, p_btl, "2.5M"
                    ])
            else:
                rows.append([str(q_num), Paragraph(q.get("text",""), style_question), co, btl_num, "5M"])
        else:
            rows.append([
                Paragraph(f"<b>{q_num}</b>", style_normal),
                Paragraph(q.get("text", ""), style_question),
                co, btl_num, "5M"
            ])
        q_num += 1

    # Fix: first col is Q number, not separate
    # Build proper table: Q# | Question | CO | BTL | Marks
    rows2 = [["", "CO's", "BTL", "Marks"]]
    q_num = 1
    for q in part_b:
        bloom_btl = q.get("bloom", "")
        btl_num = _bloom_short(bloom_btl) or "2"
        co = q.get("co", "CO1")
        q_type = q.get("question_type", "Single")

        if q_type == "Compound":
            parts = q.get("parts", [])
            for idx, p in enumerate(parts):
                label = chr(96 + idx + 1)
                text = f"<b>{label})</b>&nbsp;&nbsp;{p['text']}"
                p_co = p.get("co", co)
                p_btl = _bloom_short(p.get("bloom", bloom_btl)) or btl_num
                if idx == 0:
                    rows2.append([
                        Paragraph(f"<b>{q_num}</b>", style_normal),
                        Paragraph(text, style_question),
                        p_co, p_btl, "2.5M"
                    ])
                else:
                    rows2.append([
                        Paragraph("", style_normal),
                        Paragraph(text, style_question),
                        p_co, p_btl, "2.5M"
                    ])
        else:
            rows2.append([
                Paragraph(f"<b>{q_num}</b>", style_normal),
                Paragraph(q.get("text",""), style_question),
                co, btl_num, "5M"
            ])
        q_num += 1

    table = Table(rows2, colWidths=[8*mm, 130*mm, 16*mm, 12*mm, 14*mm])
    table.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.75,colors.black),
        ('INNERGRID',(0,0),(-1,-1),0.5,colors.black),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('ALIGN',(0,0),(0,-1),'CENTER'),
        ('ALIGN',(2,0),(-1,-1),'CENTER'),
        ('BACKGROUND',(0,0),(-1,0),colors.whitesmoke),
        ('FONTSIZE',(0,0),(-1,-1),9),
        ('TOPPADDING',(0,0),(-1,-1),6),
        ('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(1,0),(1,-1),4),
    ]))
    elements.append(table)
    elements.append(Spacer(1,10))
    elements.append(Paragraph("---oo0oo---", style_small_center))
    return elements

# ══════════════════════════════════════════════════════════════════════
#  ASSIGNMENT PDF
# ══════════════════════════════════════════════════════════════════════

def render_assignment_pdf(
    paper_data, output_path,
    college_name="Sreyas Institute of Engineering and Technology",
    logo_path=_LOGO,
    regulation="R22",
    academic_year_range="",
):
    """Render an assignment sheet as PDF.

    paper_data keys:
        subject_name, subject_code, assignment_number, question_count,
        questions: list of {sno, unit_number, question_text, assignment_type, co_mapping, marks}
        course_outcomes: list of {co_number, statement}
    """
    import os
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=12 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm
    )
    elements = []

    subject_name = paper_data.get('subject_name', '')
    subject_code = paper_data.get('subject_code', '')
    assign_no = paper_data.get('assignment_number', 1)
    questions = paper_data.get('questions', [])
    cos = paper_data.get('course_outcomes', [])

    # ── Header ────────────────────────────────────────────────────────
    top_row = Table(
        [[
            Paragraph(f"Course Code: <b>{subject_code}</b>", style_normal),
            "",
            Paragraph(f"Regulation: <b>{regulation}</b>", style_normal),
        ]],
        colWidths=[60 * mm, 70 * mm, 50 * mm]
    )
    top_row.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.75, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(top_row)

    if logo_path and os.path.exists(logo_path):
        logo_img = Image(logo_path, width=18 * mm, height=18 * mm)
        name_para = Paragraph(
            f"<b>{college_name.upper()}</b><br/><i>An Autonomous Institution</i>",
            style_bold_center
        )
        header_row = Table(
            [[logo_img, name_para, ""]],
            colWidths=[25 * mm, 130 * mm, 25 * mm]
        )
        header_row.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
            ('SPAN', (1, 0), (2, 0)),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(header_row)
    else:
        elements.append(Paragraph(f"<b>{college_name.upper()}</b>", style_bold_center))

    # Title row
    title_row = Table(
        [[Paragraph(f"<b>ASSIGNMENT – {assign_no}</b>", style_bold_center),
          Paragraph(f"<b>{subject_name.upper()}</b>", style_bold_center)]],
        colWidths=[90 * mm, 90 * mm]
    )
    title_row.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.75, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(title_row)

    # Student info row
    info_row = Table(
        [[
            Paragraph("Name: ___________________________", style_normal),
            Paragraph("Roll No: _______________", style_normal),
            Paragraph("Section: _______", style_normal),
        ]],
        colWidths=[80 * mm, 70 * mm, 30 * mm]
    )
    info_row.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.75, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_row)
    elements.append(Spacer(1, 6))

    # ── CO table ──────────────────────────────────────────────────────
    if cos:
        elements.append(Paragraph("<b>Course Outcomes (COs):</b>", style_normal))
        elements.append(Spacer(1, 3))
        co_data = [["CO", "Statement"]]
        for co in cos:
            co_data.append([
                Paragraph(f"<b>{co['co_number']}</b>", style_normal),
                Paragraph(co['statement'], style_normal),
            ])
        co_table = Table(co_data, colWidths=[15 * mm, 165 * mm])
        co_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(co_table)
        elements.append(Spacer(1, 8))

    # ── Questions table ───────────────────────────────────────────────
    elements.append(Paragraph("<b>Questions:</b>", style_normal))
    elements.append(Spacer(1, 3))

    q_data = [["S.No", "Unit", "Question", "Type", "CO", "Marks"]]
    for q in questions:
        q_data.append([
            Paragraph(str(q['sno']), style_normal),
            Paragraph(str(q.get('unit_number', '')), style_normal),
            Paragraph(q['question_text'], style_normal),
            Paragraph(q.get('assignment_type', '').replace('_', ' ').title(), style_normal),
            Paragraph(q.get('co_mapping', ''), style_normal),
            Paragraph(str(q['marks']), style_normal),
        ])

    q_table = Table(q_data, colWidths=[10 * mm, 13 * mm, 100 * mm, 24 * mm, 18 * mm, 15 * mm])
    q_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(q_table)

    elements.append(Spacer(1, 10))
    elements.append(Paragraph(
        f"<b>Note:</b> Assignment {assign_no} covers Units "
        f"{'1–3' if assign_no == 1 else '4–5'} of the syllabus. "
        "Answer all questions as per the type specified.",
        style_normal
    ))

    doc.build(elements)
    return output_path
