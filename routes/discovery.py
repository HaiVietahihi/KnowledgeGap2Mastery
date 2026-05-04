"""
KG2M - routes/discovery.py
Phát hiện lỗ hổng kiến thức từ bài đăng sinh viên.
"""

import uuid
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, g, session)
from database.repository import CourseRepo
from services import get_services, run_task, get_task, save_discovery_results

discovery_bp = Blueprint("discovery", __name__, url_prefix="/discovery")


def _require_login():
    if not g.get("current_user"):
        return redirect(url_for("auth.login"))
    return None


@discovery_bp.route("/<course_id>", methods=["GET", "POST"])
def run(course_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        from database.repository import QuestionRepo
        question_ids_str = request.form.getlist("question_ids")
        
        if not question_ids_str:
            flash("Bạn chưa chọn câu hỏi nào để phân tích.", "warning")
            return redirect(url_for("discovery.run", course_id=course_id))

        selected_ids = [int(qid) for qid in question_ids_str if qid.isdigit()]
        all_questions = QuestionRepo.get_all_for_course(course_id)
        selected_questions = [q for q in all_questions if q.id in selected_ids]
        
        if not selected_questions:
            flash("Không có câu hỏi hợp lệ nào được chọn.", "info")
            return redirect(url_for("courses.detail", course_id=course_id))
            
        posts = [q.content for q in selected_questions]
        question_ids = [q.id for q in selected_questions]

        task_id = f"discovery-{uuid.uuid4().hex[:8]}"
        _, discovery, _ = get_services()

        def do_discovery():
            result = discovery.discover(posts, course_id, course_name=course.name)
            # Lưu kết quả để bước Expert Refinement truy cập
            save_discovery_results(course_id, result)
            return result

        run_task(task_id, do_discovery)
        session["last_discovery_task"] = task_id
        session["last_discovery_course"] = course_id
        
        # Save question IDs to session so we can mark them as processed later
        session[f"discovery_{task_id}_questions"] = question_ids
        
        return redirect(url_for("discovery.results", course_id=course_id, task_id=task_id))

    from database.repository import QuestionRepo
    all_questions = QuestionRepo.get_all_for_course(course_id)
    return render_template("discovery/run.html", course=course, all_questions=all_questions)


@discovery_bp.route("/<course_id>/results/<task_id>")
def results(course_id, task_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    task = get_task(task_id)

    # Nếu task đã hoàn tất, tự động lưu lỗ hổng vào DB và chuyển sang chuyên gia duyệt
    if task.get("status") == "done" and task.get("result"):
        save_discovery_results(course_id, task["result"])
        
        # Mark selected questions as processed
        from database.repository import QuestionRepo, KnowledgeGapRepo
        from database.models import KnowledgeGap
        question_ids = session.get(f"discovery_{task_id}_questions", [])
        if question_ids:
            QuestionRepo.mark_processed(question_ids)
            
        # Redirect directly to refinement review
        return redirect(url_for("refinement.review", course_id=course_id))

    return render_template(
        "discovery/results.html",
        course=course,
        task_id=task_id,
        task=task,
    )
