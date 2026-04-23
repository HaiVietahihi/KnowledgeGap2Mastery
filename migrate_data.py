import os
from app import create_app
from database.models import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("Preparing DB (preserving Users)...")
    
    try:
        db.session.execute(text("DROP TABLE IF EXISTS document_chunks;"))
        db.session.commit()
    except Exception as e:
        print("Cannot drop document_chunks:", e)

    tables_to_clear = [
        "exercise_submissions",
        "learning_opportunities",
        "knowledge_gaps",
        "questions",
        "documents",
        "enrollments",
        "courses"
    ]
    
    for table in tables_to_clear:
        try:
            db.session.execute(text(f"DELETE FROM {table};"))
        except Exception as e:
            pass
            
    db.session.commit()
    
    db.create_all()
    print("Done! Database cleared and updated cleanly.")
