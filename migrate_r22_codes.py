"""
migrate_r22_codes.py — R22 code integration pass.

Does two things:
1. REPLACE PEND codes → real R22 codes on existing Subject rows.
2. INSERT new Subject rows for R22 subjects not in the original 144.

Run once from project root:
    python migrate_r22_codes.py

Safe to re-run — uses upsert logic (skip if already exists).
"""

from app import app
from models import db, Subject

# ---------------------------------------------------------------------------
# 1. PEND → real code replacements
#    old_pend_code : new_r22_code
# ---------------------------------------------------------------------------
REPLACEMENTS = {
    "PEND-CSE-41-6AAB1A": "A1529",   # Cloud Computing
    "PEND-CSE-41-C56F89": "A1564",   # Scripting Languages
    "PEND-CSE-42-7A7248": "A1566",   # Mobile Application Development
    "PEND-CSE-31-07B677": "A1606",   # Automata Theory and Compiler Design
    "PEND-CSE-31-6BFD82": "A1560",   # Full Stack Development
    "PEND-CSE-31-A12C4E": "A1516",   # Database Management Systems
    "PEND-CSE-31-C71F90": "A1568",   # Software Testing Methodologies
    "PEND-CSE-32-2221DE": "A1554",   # Image Processing
    "PEND-CSE-41-81861C": "A1559",   # Natural Language Processing
    "PEND-CSE-41-CA81B5": "A1558",   # Information Retrieval Systems
    "PEND-CSE-42-52179B": "A1562",   # Internet of Things
    "PEND-CSE-31-2DD069": "A1551",   # Artificial Intelligence
    "PEND-CSE-41-ACA26E": "A1556",   # Cyber Security
    "PEND-CSE-31-3CF61A": "A1523",   # Algorithm Design and Analysis
    "PEND-CSE-31-A21C21": "A1534",   # DevOps
    "PEND-CSE-31-DEA0A4": "A1754",   # Data Mining
    "PEND-CSE-41-7DD56D": "A1571",   # Quantum Computing
    "PEND-CSE-41-1776EB": "A1572",   # Algorithms Design and Analysis (PE-V)
    "PEND-CSE-41-303E92": "A1573",   # Agile Methodology
    "PEND-CSE-41-8E7272": "A1574",   # Robotic Process Automation
    "PEND-CSE-32-62D351": "A1575",   # Blockchain Technology
    "PEND-CSE-32-D768E9": "A1577",   # Distributed Systems
    "PEND-CSE-41-6CE644": "A1578",   # Big Data Analytics
    "PEND-CSE-42-D44779": "A1579",   # Human Computer Interaction
    "PEND-CSE-41-41EE16": "A1580",   # Cyber Forensics
    "PEND-CSE-42-CADAFA": "A1651",   # Graph Theory
    "PEND-CSE-42-660989": "A1570",   # Distributed Databases
    "PEND-AIML-31-19D65D": "A1691",  # Fundamentals of AI
    "PEND-AIML-31-3F3EEE": "A1692",  # Machine Learning Basics
    "PEND-AIML-41-4AE35C": "A1663",  # Reinforcement Learning
    "PEND-ECE-32-4DD838":  "A1461",  # Digital Image Processing
    "PEND-ECE-41-2ECED0":  "A1463",  # Real Time Operating Systems
    "PEND-ECE-41-5807FE":  "A1437",  # Microwave and Optical Communications
    "PEND-ECE-41-644A7B":  "A1462",  # Mobile Communications and Networks
    "PEND-ECE-41-6B9B9A":  "A1464",  # CMOS Analog IC Design
    "PEND-ECE-41-7F63BE":  "A1455",  # Embedded System Design
    "PEND-ECE-41-96FE77":  "A1465",  # Satellite Communications
    "PEND-ECE-42-2ACEE5":  "A1470",  # System on Chip Architecture
    "PEND-ECE-42-2FE4BF":  "A1472",  # Network Security and Cryptography
    "PEND-ECE-42-530B01":  "A1471",  # Wireless Sensor Networks
    "PEND-ECE-42-79DC8C":  "A1469",  # 5G and beyond Communication
    "PEND-ECE-32-EAFDFE":  "A1459",  # IoT Architectures and Protocols
    "PEND-ECE-42-48A847":  "A1468",  # Multimedia Database Management Systems
    "PEND-ECE-32-40A4B2":  "A1467",  # Low Power VLSI Design
}

# ---------------------------------------------------------------------------
# 2. New subjects to INSERT (not in original 144)
#    (code, name)
# ---------------------------------------------------------------------------
NEW_SUBJECTS = [
    # ECE electives
    ("A1453", "Telecommunication Switching Systems and Networks"),
    ("A1454", "Error Correcting Codes"),
    ("A1456", "Object Oriented Programming through Java (ECE)"),
    ("A1457", "Radar Systems"),
    ("A1460", "Introduction to Artificial Intelligence (ECE)"),
    ("A1466", "Artificial Neural Networks and Deep Learning"),
    # CSE electives
    ("A1552", "Advanced Computer Architecture"),
    ("A1553", "Data Analytics"),
    ("A1555", "Principles of Programming Languages"),
    ("A1576", "Software Process and Project Management"),
    # AIML electives
    ("A1652", "Introduction to Data Science (AIML)"),
    ("A1653", "Web Programming"),
    ("A1656", "Pattern Recognition"),
    ("A1657", "Generative AI (AIML)"),
    ("A1751", "Data Warehousing and Business Intelligence"),
    ("A1756", "Cloud Computing (AIML/ECE)"),
]


def run():
    with app.app_context():
        replaced = 0
        skipped_replace = 0
        inserted = 0
        skipped_insert = 0
        conflicts = 0

        # --- PASS 1: replace PEND codes ---
        for old_code, new_code in REPLACEMENTS.items():
            subj = Subject.query.filter_by(subject_code=old_code).first()
            if subj is None:
                print(f"  SKIP (not found): {old_code}")
                skipped_replace += 1
                continue

            # check new code not already taken by different row
            existing = Subject.query.filter_by(subject_code=new_code).first()
            if existing and existing.id != subj.id:
                print(f"  CONFLICT: {new_code} already used by '{existing.subject_name}' — skipping {old_code}")
                conflicts += 1
                continue

            subj.subject_code = new_code
            subj.code_pending = False
            db.session.add(subj)
            print(f"  REPLACED: {old_code} -> {new_code}  ({subj.subject_name})")
            replaced += 1

        db.session.commit()

        # --- PASS 2: insert new subjects ---
        for code, name in NEW_SUBJECTS:
            existing = Subject.query.filter_by(subject_code=code).first()
            if existing:
                print(f"  EXISTS: {code} '{existing.subject_name}' — skip insert")
                skipped_insert += 1
                continue

            subj = Subject(
                subject_name=name,
                subject_code=code,
                code_pending=False,
            )
            db.session.add(subj)
            print(f"  INSERTED: {code}  {name}")
            inserted += 1

        db.session.commit()

        print(f"\nDone. replaced={replaced} skipped={skipped_replace} "
              f"conflicts={conflicts} inserted={inserted} skipped_insert={skipped_insert}")


if __name__ == "__main__":
    run()