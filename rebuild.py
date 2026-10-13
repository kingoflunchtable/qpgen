from app import app
from models import db
from sqlalchemy import text

def rebuild_database():
    with app.app_context():
        print("Opening direct database connection...")
        with db.engine.connect() as connection:
            # Begin an explicit transaction block on this connection
            transaction = connection.begin()
            try:
                print("Disabling foreign key checks...")
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
                
                print("Dropping all tables...")
                # Force SQLAlchemy to drop tables using THIS exact connection context
                db.metadata.drop_all(bind=connection)
                
                print("Re-enabling foreign key checks...")
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
                
                transaction.commit()
                print("All old tables dropped successfully.")
            except Exception as e:
                transaction.rollback()
                print(f"Failed to drop tables safely: {e}")
                raise e
        
        print("Creating new tables based on updated schema...")
        db.create_all()
        print("Database wiped and rebuilt successfully!")

if __name__ == '__main__':
    rebuild_database()