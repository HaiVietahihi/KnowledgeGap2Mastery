"""
KG2M - database/repository.py
In-memory repositories — không cần database thật.
"""

import hashlib
from datetime import datetime


# ── Helper ────────────────────────────────────────────────────────────────────

def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ── User ──────────────────────────────────────────────────────────────────────

class UserRepo:
    @classmethod
    def create(cls, email, name, password, role="student"):
        from database.models import db, User
        user = User.create(email=email, name=name, password=password, role=role)
        db.session.add(user)
        db.session.commit()
        return user

    @classmethod
    def get_by_id(cls, uid):
        from database.models import User
        return User.query.get(uid)

    @classmethod
    def get_by_email(cls, email):
        from database.models import User
        return User.query.filter_by(email=email).first()

    @classmethod
    def check_password(cls, user, password: str) -> bool:
        return user.check_password(password)

    @classmethod
    def get_enrolled_students(cls, course_id):
        from database.models import Course
        course = Course.query.get(course_id)
        return course.students if course else []


# ── Course ────────────────────────────────────────────────────────────────────

class CourseRepo:
    @classmethod
    def get(cls, course_id: str):
        from database.models import Course
        return Course.query.get(course_id)

    @classmethod
    def list_all(cls):
        from database.models import Course
        return Course.query.all()

    @classmethod
    def list_for_user(cls, user_id: int):
        from database.models import Course, User
        user = User.query.get(user_id)
        if not user:
            return []
        if user.role == "instructor":
            return Course.query.filter_by(owner_id=user_id).all()
        else:
            return user.enrolled_courses

    @classmethod
    def get_stats(cls, course_id: str) -> dict:
        from database.models import Question, KnowledgeGap, LearningOpportunity, Document
        return {
            "doc_count": Document.query.filter_by(course_id=course_id).count(),
            "gap_count": KnowledgeGap.query.filter_by(course_id=course_id).count(),
            "lop_count": LearningOpportunity.query.join(KnowledgeGap).filter(KnowledgeGap.course_id == course_id).count(),
        }

    @classmethod
    def create(cls, course_id, name, code, description="", owner_id=1):
        from database.models import db, Course
        import uuid
        if not course_id:
            course_id = f"course-{uuid.uuid4().hex[:8]}"
            
        course = Course(id=course_id, name=name, code=code, description=description, owner_id=owner_id)
        db.session.add(course)
        db.session.commit()
        return course

    @classmethod
    def delete(cls, course_id):
        from database.models import db, Course, enrollments
        course = Course.query.get(course_id)
        if not course:
            return False
        # Clear enrollments (many-to-many)
        db.session.execute(enrollments.delete().where(enrollments.c.course_id == course_id))
        # Cascade delete handled by SQLAlchemy relationships
        db.session.delete(course)
        db.session.commit()
        return True

class QuestionRepo:
    @classmethod
    def create(cls, course_id, student_id, content):
        from database.models import db, Question
        q = Question(course_id=course_id, student_id=student_id, content=content)
        db.session.add(q)
        db.session.commit()
        return q

    @classmethod
    def get_pending_for_course(cls, course_id):
        from database.models import Question
        return Question.query.filter_by(course_id=course_id, status="pending").all()
        
    @classmethod
    def get_all_for_course(cls, course_id):
        from database.models import Question
        return Question.query.filter_by(course_id=course_id).all()

    @classmethod
    def mark_processed(cls, question_ids):
        from database.models import db, Question
        Question.query.filter(Question.id.in_(question_ids)).update({"status": "processed"})
        db.session.commit()

    @classmethod
    def get_all_for_course_by_student(cls, course_id, student_id):
        from database.models import Question
        return Question.query.filter_by(course_id=course_id, student_id=student_id).order_by(Question.created_at.desc()).all()

class KnowledgeGapRepo:
    @classmethod
    def create(cls, course_id, title, description=""):
        from database.models import db, KnowledgeGap
        gap = KnowledgeGap(course_id=course_id, title=title, description=description)
        db.session.add(gap)
        db.session.commit()
        return gap

    @classmethod
    def get(cls, gap_id):
        from database.models import KnowledgeGap
        return KnowledgeGap.query.get(gap_id)

    @classmethod
    def list_by_course(cls, course_id):
        from database.models import KnowledgeGap
        return KnowledgeGap.query.filter_by(course_id=course_id).order_by(KnowledgeGap.created_at.desc()).all()

    @classmethod
    def delete(cls, gap_id):
        from database.models import db, KnowledgeGap
        gap = KnowledgeGap.query.get(gap_id)
        if gap:
            db.session.delete(gap)
            db.session.commit()
            return True
        return False

class LearningOpportunityRepo:
    @classmethod
    def create(cls, gap_id, gap_type, content, bloom_level="", difficulty=""):
        from database.models import db, LearningOpportunity
        lop = LearningOpportunity(gap_id=gap_id, type=gap_type, content=content, bloom_level=bloom_level, difficulty=difficulty)
        db.session.add(lop)
        db.session.commit()
        return lop

    @classmethod
    def get(cls, lop_id):
        from database.models import LearningOpportunity
        return LearningOpportunity.query.get(lop_id)

    @classmethod
    def get_by_course(cls, course_id):
        from database.models import LearningOpportunity, KnowledgeGap
        return LearningOpportunity.query.join(KnowledgeGap).filter(KnowledgeGap.course_id == course_id).all()

    @classmethod
    def toggle_publish(cls, lop_id):
        from database.models import db, LearningOpportunity
        lop = LearningOpportunity.query.get(lop_id)
        if lop:
            lop.is_published = not lop.is_published
            db.session.commit()
        return lop

    @classmethod
    def update_content(cls, lop_id, content):
        from database.models import db, LearningOpportunity
        lop = LearningOpportunity.query.get(lop_id)
        if lop:
            lop.content = content
            db.session.commit()
        return lop

    @classmethod
    def delete(cls, lop_id):
        from database.models import db, LearningOpportunity
        lop = LearningOpportunity.query.get(lop_id)
        if lop:
            db.session.delete(lop)
            db.session.commit()
            return True
        return False


class ExerciseSubmissionRepo:
    @classmethod
    def get_or_create(cls, student_id, lop_id):
        from database.models import db, ExerciseSubmission
        submission = ExerciseSubmission.query.filter_by(student_id=student_id, lop_id=lop_id).first()
        if not submission:
            submission = ExerciseSubmission(student_id=student_id, lop_id=lop_id)
            db.session.add(submission)
            db.session.commit()
        return submission

    @classmethod
    def mark_completed(cls, submission_id):
        from database.models import db, ExerciseSubmission
        from datetime import datetime
        submission = ExerciseSubmission.query.get(submission_id)
        if submission:
            submission.status = "completed"
            submission.completed_at = datetime.utcnow()
            db.session.commit()
        return submission

class AssignmentRepo:
    @classmethod
    def create(cls, course_id, title, content):
        from database.models import db, Assignment
        assignment = Assignment(course_id=course_id, title=title, content=content)
        db.session.add(assignment)
        db.session.commit()
        return assignment
        
    @classmethod
    def get(cls, assignment_id):
        from database.models import Assignment
        return Assignment.query.get(assignment_id)

    @classmethod
    def get_by_course(cls, course_id):
        from database.models import Assignment
        return Assignment.query.filter_by(course_id=course_id).order_by(Assignment.created_at.desc()).all()


class AssignmentSubmissionRepo:
    @classmethod
    def get_or_create(cls, student_id, assignment_id):
        from database.models import db, AssignmentSubmission
        submission = AssignmentSubmission.query.filter_by(student_id=student_id, assignment_id=assignment_id).first()
        if not submission:
            submission = AssignmentSubmission(student_id=student_id, assignment_id=assignment_id)
            db.session.add(submission)
            db.session.commit()
        return submission

    @classmethod
    def save_submission(cls, submission_id, answers_json, score):
        from database.models import db, AssignmentSubmission
        from datetime import datetime
        submission = AssignmentSubmission.query.get(submission_id)
        if submission:
            submission.answers = answers_json
            submission.score = score
            submission.status = "completed"
            submission.completed_at = datetime.utcnow()
            db.session.commit()
        return submission

    @classmethod
    def get_by_assignment(cls, assignment_id):
        from database.models import AssignmentSubmission
        return AssignmentSubmission.query.filter_by(assignment_id=assignment_id).all()



class DocumentRepo:
    @classmethod
    def create(cls, doc_id, course_id, doc_name, doc_type, file_name):
        from database.models import db, Document
        doc = Document(id=doc_id, course_id=course_id, doc_name=doc_name,
                       doc_type=doc_type, file_name=file_name, status="processing")
        db.session.add(doc)
        db.session.commit()
        return doc

    @classmethod
    def get(cls, doc_id):
        from database.models import Document
        return Document.query.get(doc_id)

    @classmethod
    def list_by_course(cls, course_id):
        from database.models import Document
        return Document.query.filter_by(course_id=course_id).order_by(Document.created_at.desc()).all()

    @classmethod
    def update_status(cls, doc_id, status, page_count=None, description=None, error_message=None):
        from database.models import db, Document
        doc = Document.query.get(doc_id)
        if doc:
            doc.status = status
            if page_count is not None:
                doc.page_count = page_count
            if description is not None:
                doc.description = description
            if error_message is not None:
                doc.error_message = error_message
            db.session.commit()
        return doc

    @classmethod
    def delete(cls, doc_id):
        from database.models import db, Document
        doc = Document.query.get(doc_id)
        if doc:
            db.session.delete(doc)
            db.session.commit()
            return True
        return False


class DocumentNodeRepo:
    @classmethod
    def create_bulk(cls, document_id, nodes_data):
        from database.models import db, DocumentNode
        for node in nodes_data:
            c = DocumentNode(
                document_id=document_id,
                node_id=node.get("node_id"),
                parent_node_id=node.get("parent_node_id"),
                level=node.get("level", 0),
                chunk_index=node.get("chunk_index", 0),
                title=node.get("title", ""),
                content=node.get("content", ""),
                summary=node.get("summary", ""),
                page_start=node.get("page_start"),
                page_end=node.get("page_end"),
            )
            db.session.add(c)
        db.session.commit()

    @classmethod
    def get_all_by_course(cls, course_id):
        from database.models import DocumentNode, Document
        return DocumentNode.query.join(Document).filter(
            Document.course_id == course_id, Document.status == "completed"
        ).order_by(DocumentNode.chunk_index).all()

    @classmethod
    def get_nodes_by_ids(cls, course_id, node_ids):
        from database.models import DocumentNode, Document
        if not node_ids:
            return []
        return DocumentNode.query.join(Document).filter(
            Document.course_id == course_id, 
            Document.status == "completed",
            DocumentNode.node_id.in_(node_ids)
        ).all()

