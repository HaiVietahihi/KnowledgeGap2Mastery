"""
KG2M - database/models.py
SQLAlchemy Models
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import hashlib

db = SQLAlchemy()

def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

enrollments = db.Table('enrollments',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('course_id', db.String(50), db.ForeignKey('courses.id'), primary_key=True)
)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default="student") # "student" or "instructor"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    enrolled_courses = db.relationship('Course', secondary=enrollments, lazy='subquery',
        backref=db.backref('students', lazy=True))

    def check_password(self, password: str) -> bool:
        return self.password_hash == _hash_pw(password)
        
    @classmethod
    def create(cls, email, name, password, role="student"):
        return cls(email=email, name=name, password_hash=_hash_pw(password), role=role)

class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship('User', backref='owned_courses', foreign_keys=[owner_id])
    questions = db.relationship('Question', backref='course', cascade='all, delete-orphan')
    knowledge_gaps = db.relationship('KnowledgeGap', backref='course', cascade='all, delete-orphan')

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.String(50), db.ForeignKey('courses.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="pending") # "pending", "processed"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    student = db.relationship('User')

class KnowledgeGap(db.Model):
    __tablename__ = 'knowledge_gaps'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.String(50), db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    opportunities = db.relationship('LearningOpportunity', backref='gap', cascade='all, delete-orphan')

class LearningOpportunity(db.Model):
    __tablename__ = 'learning_opportunities'
    id = db.Column(db.Integer, primary_key=True)
    gap_id = db.Column(db.Integer, db.ForeignKey('knowledge_gaps.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False) # "MCQ", "exercise", etc.
    content = db.Column(db.Text, nullable=False) # JSON or generated string
    bloom_level = db.Column(db.String(50), nullable=True)
    difficulty = db.Column(db.String(50), nullable=True)
    is_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ExerciseSubmission(db.Model):
    __tablename__ = 'exercise_submissions'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    lop_id = db.Column(db.Integer, db.ForeignKey('learning_opportunities.id'), nullable=False)
    status = db.Column(db.String(20), default="pending") # "pending", "completed"
    completed_at = db.Column(db.DateTime, nullable=True)
    
    student = db.relationship('User', backref=db.backref('submissions', lazy=True))
    learning_opportunity = db.relationship('LearningOpportunity', backref=db.backref('submissions', lazy=True))

class Assignment(db.Model):
    __tablename__ = 'assignments'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.String(50), db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False) # JSON generated with selected questions
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship('Course', backref=db.backref('assignments', cascade='all, delete-orphan'))

class AssignmentSubmission(db.Model):
    __tablename__ = 'assignment_submissions'
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    answers = db.Column(db.Text, nullable=True) # JSON string
    score = db.Column(db.String(50), nullable=True) # e.g. "8/10"
    status = db.Column(db.String(20), default="pending") # "pending", "completed"
    completed_at = db.Column(db.DateTime, nullable=True)
    
    assignment = db.relationship('Assignment', backref=db.backref('submissions', cascade='all, delete-orphan'))
    student = db.relationship('User', backref=db.backref('assignment_submissions', lazy=True))


class Document(db.Model):
    __tablename__ = 'documents'
    id = db.Column(db.String(50), primary_key=True)
    course_id = db.Column(db.String(50), db.ForeignKey('courses.id'), nullable=False)
    doc_name = db.Column(db.String(200), nullable=False)
    doc_type = db.Column(db.String(50), default="lecture_notes")
    file_name = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), default="processing")  # "processing", "completed", "error"
    page_count = db.Column(db.Integer, nullable=True)
    description = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship('Course', backref=db.backref('documents', cascade='all, delete-orphan'))
    nodes = db.relationship('DocumentNode', backref='document', cascade='all, delete-orphan')

class DocumentNode(db.Model):
    __tablename__ = 'document_nodes'
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.String(50), db.ForeignKey('documents.id'), nullable=False)
    node_id = db.Column(db.String(100), nullable=False)
    parent_node_id = db.Column(db.String(100), nullable=True)
    level = db.Column(db.Integer, default=0)
    chunk_index = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(500), nullable=True)
    content = db.Column(db.Text, nullable=False)
    summary = db.Column(db.Text, nullable=True)
    page_start = db.Column(db.Integer, nullable=True)
    page_end = db.Column(db.Integer, nullable=True)

