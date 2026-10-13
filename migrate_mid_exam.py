"""
Run once: creates the three new mid-exam tables.
    python migrate_mid_exam.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

from app import app
from models import db

with app.app_context():
    db.create_all()
    print("✓ mid_objective_questions table created/verified")
    print("✓ mid_exam_papers table created/verified")
    print("✓ mid_subjective_slots table created/verified")
    print("Done. All mid-exam tables are ready.")
