"""Run once: adds is_pending column to mid_objective_questions table."""
from app import app,db


with app.app_context():
    try:
        db.engine.execute("ALTER TABLE mid_objective_questions ADD COLUMN is_pending BOOLEAN DEFAULT 0")
        print("Column added.")
    except Exception as e:
        print(f"Already exists or error: {e}")
