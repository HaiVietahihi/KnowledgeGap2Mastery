"""
KG2M - database/db.py
In-memory database mock .
"""


from database.models import db, User, Course

def init_db(app):
    """
    Initialize SQLAlchemy and seed with initial data
    """
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _seed_db()

def _seed_db():
    from database.models import db, User
    
    # Check if admin exists
    admin = User.query.filter_by(email="admin@kg2m.local").first()
    if not admin:
        admin = User.create(email="admin@kg2m.local", name="Giảng viên", password="admin123", role="instructor")
        db.session.add(admin)
        db.session.commit()
    
    # Check if student exists
    student = User.query.filter_by(email="student@kg2m.local").first()
    if not student:
        student = User.create(email="student@kg2m.local", name="Sinh viên", password="student123", role="student")
        db.session.add(student)
        
    db.session.commit()
