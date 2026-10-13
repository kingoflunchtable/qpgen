"""
replace_upper_semesters.py
--------------------------
Removes ALL subjects linked to years 3 & 4 (academic_year 3 and 4)
for CSE, AIML, ECE branches, then re-seeds them from the R22 syllabus
data captured from the provided screenshots.

Safe to run multiple times (idempotent).

Subject rows that have no other branch links AND no questions/units are
also deleted to avoid orphans. Subjects shared across branches (or that
have questions attached) are kept — only the BranchSubject link is removed.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Branch, Subject, BranchSubject, Unit, QuestionGroup, PartAQuestion, PendingQuestion

# ---------------------------------------------------------------------------
# R22 CURRICULUM DATA  (Extracted from Official Curriculum)
# Format: (subject_code, subject_name, elective_group or None)
#         elective_group = None  →  core subject
#         elective_group = str   →  elective option belonging to that slot
# ---------------------------------------------------------------------------

R22 = {
    "CSE": {
        (3, 1): {
            "core": [
                ("A1523", "Design and Analysis of Algorithms"),
                ("A1524", "Computer Networks"),
                ("A1526", "Web Technologies"),
                ("A1525", "Computer Networks Lab"),
                ("A1527", "Web Technologies Lab"),
                ("A1019", "Advanced English Communication Skills Lab"),
                ("A1021", "Logical Reasoning – I"),
                ("A1020", "Intellectual Property Rights"),
                ("A1528", "Skill Development Course(UI Design-Flutter)"),
            ],
            "electives": {
                "Professional Elective - I": [
                    ("A1551", "Artificial Intelligence"),
                    ("A1552", "Advanced Computer Architecture"),
                    ("A1553", "Data Analytics"),
                    ("A1554", "Image Processing"),
                    ("A1555", "Principles of Programming Languages"),
                ],
                "Professional Elective - II": [
                    ("A1556", "Cyber Security"),
                    ("A1557", "Embedded Systems"),
                    ("A1558", "Information Retrieval Systems"),
                    ("A1655", "Soft Computing"),
                    ("A1559", "Natural Language Processing"),
                ],
            },
        },
        (3, 2): {
            "core": [
                ("A1529", "Cloud Computing"),
                ("A1606", "Automata Theory and Compiler Design"),
                ("A1611", "Machine Learning"),
                ("A1612", "Machine Learning Lab"),
                ("A1530", "Cloud Computing Lab"),
                ("A1022", "Logical Reasoning – II"),
                ("A1531", "Industrial Oriented Mini Project/ Internship/ Skill Development Course (Big data-Spark)"),
                ("A1007", "Environmental Science"),
            ],
            "electives": {
                "Professional Elective - III": [
                    ("A1560", "Full Stack Development"),
                    ("A1562", "Internet of Things"),
                    ("A1564", "Scripting Languages"),
                    ("A1566", "Mobile Application Development"),
                    ("A1568", "Software Testing Methodologies"),
                ],
                "Professional Elective - III Lab": [
                    ("A1561", "Full Stack Development Lab"),
                    ("A1563", "Internet of Things Lab"),
                    ("A1565", "Scripting Languages Lab"),
                    ("A1567", "Mobile Application Development Lab"),
                    ("A1569", "Software Testing Methodologies Lab"),
                ],
                "Open Elective - I": [
                    ("A1591", "Data Structures"),
                    ("A1592", "Database Management System"),
                ],
            },
        },
        (4, 1): {
            "core": [
                ("A1532", "Cryptography and Network Security"),
                ("A1534", "Dev Ops"),
                ("A1533", "Cryptography and Network Security Lab"),
                ("A1535", "Dev Ops Lab"),
                ("A1536", "Project Stage - I"),
            ],
            "electives": {
                "Professional Elective - IV": [
                    ("A1651", "Graph Theory"),
                    ("A1570", "Distributed Databases"),
                    ("A1571", "Quantum Computing"),
                    ("A1752", "Computer Graphics"),
                    ("A1754", "Data Mining"),
                ],
                "Professional Elective - V": [
                    ("A1572", "Advanced Algorithms"),
                    ("A1573", "Agile Methodology"),
                    ("A1574", "Robotic Process Automation"),
                    ("A1575", "Block chain Technology"),
                    ("A1576", "Software Process & Project Management"),
                ],
                "Open Elective - II": [
                    ("A1593", "Python Programming"),
                    ("A1594", "Software Engineering"),
                ],
            },
        },
        (4, 2): {
            "core": [
                ("A1024", "Organizational Behavior"),
                ("A1537", "Project Stage – II including Seminar"),
            ],
            "electives": {
                "Professional Elective - VI": [
                    ("A1663", "Reinforcement Learning"),
                    ("A1577", "Distributed Systems"),
                    ("A1578", "Big Data Analytics"),
                    ("A1579", "Human Computer Interaction"),
                    ("A1580", "Cyber Forensics"),
                ],
                "Open Elective - III": [
                    ("A1595", "Algorithms Design and Analysis"),
                    ("A1596", "Deep Learning"),
                ],
            },
        },
    },

    "AIML": {
        (3, 1): {
            "core": [
                ("A1523", "Design and Analysis of Algorithms"),
                ("A1611", "Machine Learning"),
                ("A1524", "Computer Networks"),
                ("A1016", "Business Economics & Financial Analysis"),
                ("A1612", "Machine Learning Lab"),
                ("A1525", "Computer Networks Lab"),
                ("A1019", "Advanced English Communication Skills lab"),
                ("A1020", "Intellectual Property Rights"),
                ("A1021", "Logical Reasoning- I"),
                ("A1528", "Skill Development Course (UI design- Flutter)"),
            ],
            "electives": {
                "Professional Elective-I": [
                    ("A1651", "Graph Theory"),
                    ("A1652", "Introduction to Data Science"),
                    ("A1653", "Web Programming"),
                    ("A1654", "Image Processing"),
                    ("A1655", "Soft Computing"),
                ],
            },
        },
        (3, 2): {
            "core": [
                ("A1613", "Deep Learning"),
                ("A1615", "Data Analytics"),
                ("A1617", "Natural Language Processing"),
                ("A1618", "Natural Language Processing Lab/Full Stack Development Lab"),
                ("A1614", "Deep Learning Lab"),
                ("A1022", "Logical Reasoning- II"),
                ("A1616", "Data Analytics Lab"),
                ("A1007", "Environmental Science"),
                ("A1619", "Industrial Oriented Mini Project/ Internship/Skill Development Course (DevOps)"),
            ],
            "electives": {
                "Professional Elective - II": [
                    ("A1568", "Software Testing Methodologies"),
                    ("A1558", "Information Retrieval Systems"),
                    ("A1656", "Pattern Recognition"),
                    ("A1560", "Full Stack Development"),
                    ("A1751", "Data Warehousing and Business Intelligence"),
                ],
                "Open Elective - I": [
                    ("A1691", "Fundamentals of AI"),
                    ("A1692", "Machine Learning Basics"),
                ],
            },
        },
        (4, 1): {
            "core": [
                ("A1534", "DevOps"),
                ("A1620", "Nature Inspired Computing"),
                ("A1535", "DevOps Lab"),
                ("A1621", "Project Stage-I"),
            ],
            "electives": {
                "Professional Elective-III": [
                    ("A1754", "Data Mining"),
                    ("A1564", "Scripting Languages"),
                    ("A1566", "Mobile Application Development"),
                    ("A1756", "Cloud Computing"),
                    ("A1657", "Generative AI"),
                ],
                "Professional Elective Lab-III": [
                    ("A1763", "Data Mining Lab"),
                    ("A1565", "Scripting Languages Lab"),
                    ("A1567", "Mobile Application Development Lab"),
                    ("A1764", "Cloud Computing Lab"),
                    ("A1658", "Generative AI Lab"),
                ],
                "Professional Elective-IV": [
                    ("A1571", "Quantum Computing"),
                    ("A1659", "Expert Systems"),
                    ("A1660", "Semantic Web"),
                    ("A1661", "Game Theory"),
                    ("A1662", "Mobile Computing"),
                    ("A1663", "Reinforcement Learning"),
                ],
                "Open Elective- II": [
                    ("A1693", "Introduction To Natural Language Processing"),
                    ("A1694", "AI Applications"),
                ],
            },
        },
        (4, 2): {
            "core": [
                ("A1622", "Project Stage–II including Seminar"),
            ],
            "electives": {
                "Professional Elective-V": [
                    ("A1664", "Social Network Analysis"),
                    ("A1665", "Federated Machine Learning"),
                    ("A1666", "Augmented Reality & Virtual Reality"),
                    ("A1556", "Cyber Security"),
                    ("A1667", "Ad-hoc & Sensor Networks"),
                ],
                "Professional Elective–VI": [
                    ("A1668", "Speech and Video Processing"),
                    ("A1669", "Robotic Process Automation"),
                    ("A1670", "Randomized Algorithms"),
                    ("A1671", "Cognitive Computing"),
                    ("A1672", "Conversational AI"),
                ],
                "Open Elective III": [
                    ("A1695", "Chatbots"),
                    ("A1696", "Evolutionary Computing"),
                ],
            },
        },
    },

    "ECE": {
        (3, 1): {
            "core": [
                ("A1425", "Microcontrollers"),
                ("A1427", "Data Communications and Computer Networks"),
                ("A1429", "Control Systems"),
                ("A1016", "Business Economics & Financial Analysis"),
                ("A1426", "Microcontrollers Laboratory"),
                ("A1428", "Data Communications and Computer Networks Laboratory"),
                ("A1019", "Advanced English Communication Skills Laboratory"),
                ("A1020", "Intellectual Property Rights"),
                ("A1021", "Logical Reasoning - 1"),
            ],
            "electives": {
                "Professional Elective – I": [
                    ("A1451", "Computer Organization and Architecture"),
                    ("A1452", "Data Structures"),
                    ("A1453", "Telecommunication Switching Systems and Networks"),
                    ("A1454", "Error Correcting Codes"),
                ],
                "Professional Elective – II": [
                    ("A1455", "Embedded System Design"),
                    ("A1456", "Object Oriented Programming through Java"),
                    ("A1457", "Radar Systems"),
                    ("A1458", "Wireless Communications"),
                ],
            },
        },
        (3, 2): {
            "core": [
                ("A1430", "Antennas and Wave Propagation"),
                ("A1431", "Digital Signal Processing"),
                ("A1433", "CMOS VLSI Design"),
                ("A1432", "Digital Signal Processing Laboratory"),
                ("A1434", "CMOS VLSI Design Laboratory"),
                ("A1435", "Advanced Communication Laboratory"),
                ("A1436", "Industry Oriented Mini Project/ Internship"),
                ("A1007", "Environmental Science"),
                ("A1009", "Human Value and Ethics"),
                ("A1022", "Logical Reasoning - 2"),
            ],
            "electives": {
                "Professional Elective – III": [
                    ("A1459", "IoT Architectures and Protocols"),
                    ("A1460", "Introduction to Artificial Intelligence"),
                    ("A1461", "Digital Image Processing"),
                    ("A1462", "Mobile Communications and Networks"),
                ],
                "Open Elective (OE – I)": [
                    ("A1491", "Digital Electronics for Engineering"),
                    ("A1492", "Microcontrollers"),
                    ("A1493", "Principles of Signal Processing"),
                ],
            },
        },
        (4, 1): {
            "core": [
                ("A1437", "Microwave and Optical Communications"),
                ("A1023", "Professional Practice, Law and Ethics"),
                ("A1438", "Microwave and Optical Communications Laboratory"),
                ("A1439", "Project Stage - I"),
            ],
            "electives": {
                "Professional Elective – IV": [
                    ("A1463", "Real Time Operating Systems"),
                    ("A1464", "CMOS Analog IC Design"),
                    ("A1465", "Satellite Communications"),
                    ("A1466", "Artificial Neural Networks and Deep Learning"),
                ],
                "Professional Elective – V": [
                    ("A1467", "Low Power VLSI"),
                    ("A1468", "Multimedia Database Management Systems"),
                    ("A1756", "Cloud Computing"),
                    ("A1469", "5G and beyond Communication"),
                ],
                "Open Elective (OE – II)": [
                    ("A1494", "Error Correcting Codes"),
                    ("A1495", "System on Chip Architecture"),
                    ("A1496", "Introduction to Embedded Systems"),
                ],
            },
        },
        (4, 2): {
            "core": [
                ("A1440", "Project Stage – II including Seminar"),
            ],
            "electives": {
                "Professional Elective – VI": [
                    ("A1470", "System on Chip Architecture"),
                    ("A1471", "Wireless Sensor Networks"),
                    ("A1575", "Blockchain Technology"),
                    ("A1472", "Network Security and Cryptography"),
                ],
                "Open Elective (OE – III)": [
                    ("A1497", "Fundamentals of Internet of Things"),
                    ("A1498", "Communication Technologies"),
                    ("A1499", "Real Time Operating Systems"),
                ],
            },
        },
    },
}


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def subject_has_data(subj_id):
    """True if this subject has units, questions, or pending questions."""
    if Unit.query.filter_by(subject_id=subj_id).first():
        return True
    if QuestionGroup.query.filter_by(subject_id=subj_id).first():
        return True
    if PartAQuestion.query.filter_by(subject_id=subj_id).first():
        return True
    if PendingQuestion.query.filter_by(subject_id=subj_id).first():
        return True
    return False


def remove_upper_semesters(branch_code):
    branch = Branch.query.filter_by(branch_code=branch_code).first()
    if not branch:
        print(f"  ⚠️  Branch {branch_code} not found — skipping removal.")
        return

    links = BranchSubject.query.filter(
        BranchSubject.branch_id == branch.id,
        BranchSubject.academic_year.in_([3, 4]),
    ).all()

    removed_subjects = 0
    removed_links = 0

    # Collect subject ids before deleting links
    subject_ids = [link.subject_id for link in links]

    for link in links:
        db.session.delete(link)
        removed_links += 1

    # Flush all link deletes first so orphan check is accurate
    db.session.flush()

    # Now safely check which subjects are truly orphaned
    for subj_id in set(subject_ids):
        other_links = BranchSubject.query.filter_by(subject_id=subj_id).count()
        if other_links == 0:
            subj = Subject.query.get(subj_id)
            if subj and not subject_has_data(subj_id):
                db.session.delete(subj)
                removed_subjects += 1

    db.session.commit()
    print(f"  ✓ {branch_code}: removed {removed_links} links, {removed_subjects} orphan subject rows.")


def seed_upper_semesters(branch_code):
    branch = Branch.query.filter_by(branch_code=branch_code).first()
    if not branch:
        print(f"  ⚠️  Branch {branch_code} not found — skipping seed.")
        return

    curriculum = R22.get(branch_code, {})
    added_subjects = 0
    added_links = 0

    LAB_KW = ("lab", "laboratory", "workshop", "project", "internship", "induction")

    for (year, sem), sem_data in sorted(curriculum.items()):
        # --- core subjects ---
        for code, name in sem_data.get("core", []):
            if any(kw in name.lower() for kw in LAB_KW):
                print(f"    ⏭️  skip non-theory | {code}  {name}")
                continue
            subj = Subject.query.filter_by(subject_code=code).first()
            if not subj:
                subj = Subject(
                    subject_code=code,
                    subject_name=name,
                    code_pending=False,
                )
                db.session.add(subj)
                db.session.flush()
                added_subjects += 1

            link = BranchSubject.query.filter_by(
                branch_id=branch.id, subject_id=subj.id
            ).first()
            if not link:
                link = BranchSubject(
                    branch_id=branch.id,
                    subject_id=subj.id,
                    academic_year=year,
                    semester_number=sem,
                    elective_group=None,
                )
                db.session.add(link)
                added_links += 1
                print(f"    + Yr{year}-S{sem} core  | {code}  {name}")

        # --- electives ---
        for slot_name, options in sem_data.get("electives", {}).items():
            if any(kw in slot_name.lower() for kw in LAB_KW):
                print(f"    ⏭️  skip lab elective slot | [{slot_name}]")
                continue
            for code, name in options:
                if any(kw in name.lower() for kw in LAB_KW):
                    print(f"    ⏭️  skip non-theory | {code}  {name}")
                    continue
                subj = Subject.query.filter_by(subject_code=code).first()
                if not subj:
                    subj = Subject(
                        subject_code=code,
                        subject_name=name,
                        code_pending=False,
                    )
                    db.session.add(subj)
                    db.session.flush()
                    added_subjects += 1

                link = BranchSubject.query.filter_by(
                    branch_id=branch.id, subject_id=subj.id
                ).first()
                if not link:
                    link = BranchSubject(
                        branch_id=branch.id,
                        subject_id=subj.id,
                        academic_year=year,
                        semester_number=sem,
                        elective_group=slot_name,
                    )
                    db.session.add(link)
                    added_links += 1
                    print(f"    + Yr{year}-S{sem} elec  | [{slot_name}] {code}  {name}")

    db.session.commit()
    print(f"  ✓ {branch_code}: added {added_subjects} subjects, {added_links} links.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    with app.app_context():
        branches = ["CSE", "AIML", "ECE"]

        print("\n=== PHASE 1: Remove existing Yr3/Yr4 subjects ===")
        for b in branches:
            remove_upper_semesters(b)

        print("\n=== PHASE 2: Seed R22 Yr3/Yr4 subjects ===")
        for b in branches:
            print(f"\n  [{b}]")
            seed_upper_semesters(b)

        print("\n✅ Done.")


if __name__ == "__main__":
    main()