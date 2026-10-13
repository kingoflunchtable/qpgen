"""
seed.py — One-time data loader for Programming for Problem Solving (A2501)

Run this ONCE after your tables are created:
    python seed.py

It is safe to re-run: it checks if the subject already exists and skips
re-inserting if so (prevents duplicate data on accidental double-run).
"""

from app import app
from models import db, Branch, Subject, BranchSubject, Unit, PartAQuestion, QuestionGroup, QuestionPart

def seed():
    with app.app_context():

        # ----------------------------------------------------------------
        # 0. BRANCHES (create if missing — safe to re-run)
        # ----------------------------------------------------------------
        branch_data = [
            ("CSE", "Computer Science Engineering"),
            ("AIML", "Computer Science Engineering (AI & ML)"),
            ("ECE", "Electronics and Communication Engineering"),
        ]
        branches = {}
        for code, name in branch_data:
            b = Branch.query.filter_by(branch_code=code).first()
            if not b:
                b = Branch(branch_code=code, branch_name=name)
                db.session.add(b)
                db.session.flush()
            branches[code] = b
        db.session.commit()

        # ----------------------------------------------------------------
        # Guard: don't re-seed if this subject already exists
        # ----------------------------------------------------------------
        existing = Subject.query.filter_by(subject_code='A2501').first()
        if existing:
            print("⚠️  Subject A2501 already exists in the database. Skipping seed.")
            print("    If you want to re-seed from scratch, wipe the database and rebuild.")
            return

        # ----------------------------------------------------------------
        # 1. SUBJECT (Updated for Many-to-Many and Year/Sem)
        # ----------------------------------------------------------------
        subject = Subject(
            subject_name="Programming for Problem Solving",
            subject_code="A2501",
            total_marks=60,
            duration_minutes=180,
            part_a_marks=10,
            part_a_count=10,
            part_b_marks=50,
            part_b_count=5
        )
        db.session.add(subject)
        db.session.flush()  # get subject.id

        # Link this shared subject to BOTH CSE and AIML branches.
        # Year/semester live on the LINK now, not on Subject itself —
        # this is the one row where both branches happen to share the
        # same term (Y1-S1), but the schema supports them differing
        # (e.g. A2006 is Y1-S1 for CSE/ECE but Y1-S2 for AIML).
        db.session.add(BranchSubject(
            branch_id=branches["CSE"].id, subject_id=subject.id,
            academic_year=1, semester_number=1
        ))
        db.session.add(BranchSubject(
            branch_id=branches["AIML"].id, subject_id=subject.id,
            academic_year=1, semester_number=1
        ))
        db.session.flush()

        # ----------------------------------------------------------------
        # 2. UNITS
        # ----------------------------------------------------------------
        unit_names = [
            (1, "Introduction to C Programming"),
            (2, "Control Structures and Arrays"),
            (3, "Strings and Functions"),
            (4, "Structures, Pointers and Dynamic Memory"),
            (5, "File Handling and Preprocessor Directives"),
        ]

        units = {}
        for number, name in unit_names:
            u = Unit(subject_id=subject.id, unit_number=number, unit_name=name)
            db.session.add(u)
            db.session.flush()
            units[number] = u

        # ----------------------------------------------------------------
        # 3. PART A QUESTIONS (2 per unit, 1 mark each)
        # ----------------------------------------------------------------
        part_a_data = {
            1: [
                ("Define an algorithm.", "Remember"),
                ("What is the difference between a constant and a variable in C?", "Understand"),
            ],
            2: [
                ("List the jump statements available in C.", "Remember"),
                ("What is the difference between break and continue?", "Understand"),
            ],
            3: [
                ("Define recursion.", "Remember"),
                ("What is the use of the strcmp() function?", "Understand"),
            ],
            4: [
                ("What is a self-referential structure?", "Remember"),
                ("Differentiate between malloc() and calloc().", "Understand"),
            ],
            5: [
                ("What is the purpose of the #define preprocessor directive?", "Remember"),
                ("What is the difference between text mode and binary mode file handling?", "Understand"),
            ],
        }

        for unit_number, questions in part_a_data.items():
            for text, bloom in questions:
                pa = PartAQuestion(
                    subject_id=subject.id,
                    unit_id=units[unit_number].id,
                    question_text=text,
                    bloom_level=bloom
                )
                db.session.add(pa)

        # ----------------------------------------------------------------
        # 4. PART B — QUESTION GROUPS (2 per unit: A = Compound, B = Single)
        # ----------------------------------------------------------------
        part_b_data = {
            1: {
                "compound": (
                    "Draw a flowchart and write an algorithm to check whether a given number is prime.", 5, "Apply",
                    "Explain the different types of operators in C with one example each.", 5, "Understand"
                ),
                "single": (
                    "Write a C program to read two integers and an operator from the user, perform the operation "
                    "using a switch statement, and display the result. Explain the structure of a C program in this context.",
                    10, "Apply"
                )
            },
            2: {
                "compound": (
                    "Write a C program to find the sum and average of elements in a 1D array.", 5, "Apply",
                    "Explain the difference between while and do-while loops with examples.", 5, "Understand"
                ),
                "single": (
                    "Write a C program to perform addition and multiplication of two matrices of order m x n and p x q. "
                    "Discuss the conditions required for valid matrix multiplication.",
                    10, "Analyze"
                )
            },
            3: {
                "compound": (
                    "Write a C program to check whether a given string is a palindrome or not.", 5, "Apply",
                    "Explain the nature of recursion with a trace of a recursive function computing factorial of a number.", 5, "Understand"
                ),
                "single": (
                    "Write a C program using recursive and non-recursive functions to find the GCD of two integers. "
                    "Compare both approaches in terms of efficiency.",
                    10, "Apply"
                )
            },
            4: {
                "compound": (
                    "Write a C program to create a student record using structures with fields roll number, name, "
                    "and marks, for an array of 5 students.", 5, "Apply",
                    "Explain pointer arithmetic with suitable examples.", 5, "Understand"
                ),
                "single": (
                    "Write a C program to dynamically allocate memory for an array of n integers using malloc(), "
                    "read the values, compute their sum and average, and free the allocated memory.",
                    10, "Apply"
                )
            },
            5: {
                "compound": (
                    "Write a C program to read data from standard input, store it in a text file, and display the "
                    "contents of the file.", 5, "Apply",
                    "Explain the use of #ifdef and #ifndef preprocessor directives with an example.", 5, "Understand"
                ),
                "single": (
                    "Write a C program to demonstrate the use of command line arguments by accepting a number as "
                    "an argument and printing its reverse.",
                    10, "Apply"
                )
            },
        }

        for unit_number, group_data in part_b_data.items():
            unit = units[unit_number]

            # --- Compound group (a + b) ---
            a_text, a_marks, a_bloom, b_text, b_marks, b_bloom = group_data["compound"]
            compound_group = QuestionGroup(
                subject_id=subject.id,
                unit_id=unit.id,
                total_marks=a_marks + b_marks,
                difficulty="Medium",
                question_type="Compound"
            )
            db.session.add(compound_group)
            db.session.flush()

            db.session.add(QuestionPart(
                group_id=compound_group.id, part_label='a', part_order=1,
                question_text=a_text, marks=a_marks, bloom_level=a_bloom
            ))
            db.session.add(QuestionPart(
                group_id=compound_group.id, part_label='b', part_order=2,
                question_text=b_text, marks=b_marks, bloom_level=b_bloom
            ))

            # --- Single group ---
            single_text, single_marks, single_bloom = group_data["single"]
            single_group = QuestionGroup(
                subject_id=subject.id,
                unit_id=unit.id,
                total_marks=single_marks,
                difficulty="Medium",
                question_type="Single"
            )
            db.session.add(single_group)
            db.session.flush()

            db.session.add(QuestionPart(
                group_id=single_group.id, part_label=None, part_order=1,
                question_text=single_text, marks=single_marks, bloom_level=single_bloom
            ))

        # ----------------------------------------------------------------
        # COMMIT EVERYTHING
        # ----------------------------------------------------------------
        db.session.commit()
        print("✅ Seed complete!")
        print(f"   Subject: {subject.subject_name} ({subject.subject_code})")
        print(f"   Units: {len(units)}")
        print(f"   Part A questions: {sum(len(v) for v in part_a_data.values())}")
        print(f"   Part B question groups: {len(part_b_data) * 2} (1 Compound + 1 Single per unit)")
        print("\n👉 You can now test paper generation by POSTing to /generate with:")
        print('   { "subject_code": "A2501" }')


if __name__ == '__main__':
    seed()