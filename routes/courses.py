"""
KG2M - routes/courses.py
Quản lý khóa học: danh sách, chi tiết, upload tài liệu.
"""

import os
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, g, send_from_directory)
from database.repository import CourseRepo, QuestionRepo
from database.models import db, User
from services import get_services

courses_bp = Blueprint("courses", __name__, url_prefix="/courses")


def _require_login():
    if not g.get("current_user"):
        return redirect(url_for("auth.login"))
    return None


@courses_bp.route("/discover")
def discover():
    r = _require_login()
    if r:
        return r
        
    user = g.current_user
    if user.role != "student":
        flash("Chỉ sinh viên mới có thể sử dụng tính năng tìm khóa học.", "info")
        return redirect(url_for("index"))
        
    all_courses = CourseRepo.list_all()
    # Filter out courses the student is already enrolled in
    enrolled_ids = [c.id for c in user.enrolled_courses]
    available_courses = [c for c in all_courses if c.id not in enrolled_ids]
    
    return render_template("courses/discover.html", available_courses=available_courses)

@courses_bp.route("/create", methods=["GET", "POST"])
def create():
    r = _require_login()
    if r:
        return r
        
    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có thể tạo khóa học.", "error")
        return redirect(url_for("index"))
        
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        description = request.form.get("description", "").strip()
        
        if not name or not code:
            flash("Vui lòng nhập tên và mã khóa học.", "error")
            return render_template("courses/create.html")
            
        course = CourseRepo.create(
            course_id=None, # Will auto-generate UUID
            name=name,
            code=code,
            description=description,
            owner_id=user.id
        )
        flash(f"Đã tạo khóa học {course.name} thành công!", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
        
    return render_template("courses/create.html")


@courses_bp.route("/<course_id>")
def detail(course_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))
    
    # Kiem tra quyen truy cap
    user = g.current_user
    is_enrolled = False
    if user.role == "student":
        is_enrolled = course in user.enrolled_courses
    else:
        is_enrolled = True # instructor luôn có quyền
        
    ingestion, _, _ = get_services()
    documents = ingestion.list_documents(course_id)
    questions = QuestionRepo.get_all_for_course(course_id)
    
    from database.repository import AssignmentRepo, AssignmentSubmissionRepo, KnowledgeGapRepo
    assignments = AssignmentRepo.get_by_course(course_id)
    knowledge_gaps = KnowledgeGapRepo.list_by_course(course_id)
    
    submissions = {}
    if user.role == "student":
        for a in assignments:
            sub = AssignmentSubmissionRepo.get_or_create(user.id, a.id)
            submissions[a.id] = sub

    return render_template(
        "courses/detail.html",
        course=course,
        documents=documents,
        is_enrolled=is_enrolled,
        questions=questions,
        assignments=assignments,
        submissions=submissions,
        knowledge_gaps=knowledge_gaps
    )

@courses_bp.route("/<course_id>/enroll", methods=["POST"])
def enroll(course_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))
        
    user = g.current_user
    if user.role == "student":
        if course not in user.enrolled_courses:
            user.enrolled_courses.append(course)
            db.session.commit()
            flash(f"Đã tham gia khóa học {course.name} thành công!", "success")
        else:
            flash("Bạn đã tham gia khóa học này rồi.", "info")
            
    return redirect(url_for("courses.detail", course_id=course_id))

@courses_bp.route("/<course_id>/assignment/<int:assignment_id>", methods=["GET", "POST"])
def assignment(course_id, assignment_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    user = g.current_user
    if user.role != "student":
        flash("Chỉ sinh viên mới có thể làm bài tập.", "info")
        return redirect(url_for("courses.detail", course_id=course_id))

    if course not in user.enrolled_courses:
        flash("Bạn chưa tham gia khóa học này.", "error")
        return redirect(url_for("courses.detail", course_id=course_id))

    from database.repository import AssignmentRepo, AssignmentSubmissionRepo
    import json
    
    assignment_obj = AssignmentRepo.get(assignment_id)
    if not assignment_obj or assignment_obj.course_id != course_id:
        flash("Không tìm thấy bài tập.", "error")
        return redirect(url_for("courses.detail", course_id=course_id))

    submission = AssignmentSubmissionRepo.get_or_create(user.id, assignment_obj.id)
    
    try:
        content_dict = json.loads(assignment_obj.content)
        questions = content_dict.get("questions", [])
    except:
        questions = []

    if request.method == "POST":
        if submission.status != "completed":
            # Grade the submission
            correct_count = 0
            student_answers = {}
            total_questions = len(questions)
            
            for i, q_item in enumerate(questions):
                q = q_item.get("lop", {}) if isinstance(q_item, dict) and "lop" in q_item else q_item
                correct_answer = q.get("dap_an_dung")
                student_choice = request.form.get(f"q_{i}")
                
                if student_choice:
                    student_answers[str(i)] = student_choice
                    if student_choice == correct_answer:
                        correct_count += 1
                        
            score_str = f"{correct_count}/{total_questions}"
            AssignmentSubmissionRepo.save_submission(submission.id, json.dumps(student_answers), score_str)
            
            flash(f"Đã nộp bài và lưu kết quả thành công! Điểm: {score_str}", "success")
        else:
            flash("Bạn đã hoàn thành bài tập này rồi.", "info")
        return redirect(url_for("courses.detail", course_id=course_id))

    try:
        student_answers = json.loads(submission.answers) if submission.answers else {}
    except:
        student_answers = {}

    return render_template("courses/assignment.html", course=course, assignment=assignment_obj, questions=questions, submission=submission, student_answers=student_answers)


@courses_bp.route("/<course_id>/ask", methods=["GET", "POST"])
def ask_question(course_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))
        
    user = g.current_user
    if user.role != "student":
        flash("Chỉ sinh viên mới có thể đặt câu hỏi.", "error")
        return redirect(url_for("courses.detail", course_id=course_id))
        
    from database.repository import DocumentRepo, QuestionRepo
    documents = DocumentRepo.list_by_course(course_id)
    history = QuestionRepo.get_all_for_course_by_student(course_id, user.id)
    
    if request.method == "POST":
        contents = request.form.getlist("content[]")
        doc_ids = request.form.getlist("doc_id[]")
        page_nums = request.form.getlist("page_num[]")
        
        added_count = 0
        for i in range(len(contents)):
            content = contents[i].strip()
            if not content:
                continue
                
            doc_id = doc_ids[i] if i < len(doc_ids) else ""
            page_num = page_nums[i].strip() if i < len(page_nums) else ""
            
            # Xây dựng chuỗi Context
            context_str = ""
            if doc_id:
                # Lấy tên document
                doc = next((d for d in documents if str(d.id) == doc_id), None)
                doc_name = doc.doc_name if doc else "Không rõ tài liệu"
                
                context_str = f"[Tài liệu: {doc_name}"
                if page_num:
                    context_str += f", Trang: {page_num}"
                context_str += "] "
            
            final_content = f"{context_str}{content}"
            QuestionRepo.create(course_id, user.id, final_content)
            added_count += 1
            
        if added_count > 0:
            flash(f"Đã gửi thành công {added_count} câu hỏi!", "success")
        else:
            flash("Vui lòng nhập nội dung câu hỏi.", "error")
            
        return redirect(url_for("courses.ask_question", course_id=course_id))
            
    return render_template("courses/ask.html", course=course, documents=documents, history=history)


@courses_bp.route("/<course_id>/document/<doc_id>/view")
def view_document(course_id, doc_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    user = g.current_user
    # Kiểm tra quyền: instructor hoặc sinh viên đã enroll
    if user.role == "student" and course not in user.enrolled_courses:
        flash("Bạn chưa tham gia khóa học này.", "error")
        return redirect(url_for("courses.detail", course_id=course_id))

    from database.repository import DocumentRepo
    doc = DocumentRepo.get(doc_id)
    if not doc or doc.course_id != course_id:
        flash("Không tìm thấy tài liệu.", "error")
        return redirect(url_for("courses.detail", course_id=course_id))

    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", course_id)
    if not os.path.exists(os.path.join(upload_dir, doc.file_name)):
        flash("File không tồn tại trên hệ thống.", "error")
        return redirect(url_for("courses.detail", course_id=course_id))

    return send_from_directory(upload_dir, doc.file_name)


@courses_bp.route("/<course_id>/document/<doc_id>/delete", methods=["POST"])
def delete_document(course_id, doc_id):
    r = _require_login()
    if r:
        return r
    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("courses.detail", course_id=course_id))
        
    from database.repository import DocumentRepo
    doc = DocumentRepo.get(doc_id)
    if doc and doc.course_id == course_id:
        try:
            # Optionally delete file from disk
            upload_dir = os.path.join("uploads", course_id)
            filepath = os.path.join(upload_dir, doc.file_name)
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            pass # ignore disk delete error
            
        ingestion, _, _ = get_services()
        ingestion.delete_document(doc_id)
        flash("Đã xóa tài liệu thành công.", "success")
    else:
        flash("Không tìm thấy tài liệu.", "error")
        
    return redirect(url_for("courses.detail", course_id=course_id))

@courses_bp.route("/<course_id>/upload", methods=["GET", "POST"])
def upload(course_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        file = request.files.get("file")
        doc_type = request.form.get("doc_type", "lecture_notes")
        doc_name = request.form.get("doc_name", "").strip()

        if not file or file.filename == "":
            flash("Vui lòng chọn file PDF.", "error")
            return render_template("courses/upload.html", course=course)

        upload_dir = os.path.join("uploads", course_id)
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, file.filename)
        file.save(filepath)

        try:
            from flask import current_app
            ingestion, _, _ = get_services()
            entry = ingestion.upload_document(
                filepath, course_id, doc_type, doc_name or None,
                app=current_app._get_current_object()
            )
            flash(f"📤 Đã gửi '{entry['doc_name']}' để xử lý. Đang phân tích PDF...", "success")
            return redirect(url_for("courses.detail", course_id=course_id))
        except Exception as e:
            flash(f"❌ Upload thất bại: {e}", "error")

    return render_template("courses/upload.html", course=course)


@courses_bp.route("/<course_id>/delete", methods=["POST"])
def delete_course(course_id):
    r = _require_login()
    if r:
        return r
    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("index"))

    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    if course.owner_id != user.id:
        flash("Bạn không có quyền xóa khóa học này.", "error")
        return redirect(url_for("index"))

    # Xóa thư mục uploads
    import shutil
    upload_dir = os.path.join("uploads", course_id)
    if os.path.exists(upload_dir):
        shutil.rmtree(upload_dir, ignore_errors=True)

    course_name = course.name
    CourseRepo.delete(course_id)
    flash(f'Đã xóa khóa học "{course_name}" thành công.', "success")
    return redirect(url_for("index"))


@courses_bp.route("/<course_id>/gap/<int:gap_id>/delete", methods=["POST"])
def delete_gap(course_id, gap_id):
    r = _require_login()
    if r:
        return r
    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("generation.dashboard", course_id=course_id))

    from database.repository import KnowledgeGapRepo
    gap = KnowledgeGapRepo.get(gap_id)
    if gap and gap.course_id == course_id:
        KnowledgeGapRepo.delete(gap_id)
        flash(f'Đã xóa lỗ hổng kiến thức "{gap.title}".', "success")
    else:
        flash("Không tìm thấy lỗ hổng kiến thức.", "error")

    return redirect(url_for("generation.dashboard", course_id=course_id))

