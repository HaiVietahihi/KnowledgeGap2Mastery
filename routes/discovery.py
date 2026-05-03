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
        pending_questions = QuestionRepo.get_pending_for_course(course_id)
        
        if not pending_questions:
            flash("Không có câu hỏi mới nào của sinh viên để phân tích.", "info")
            return redirect(url_for("courses.detail", course_id=course_id))
            
        posts = [q.content for q in pending_questions]
        question_ids = [q.id for q in pending_questions]

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
        return redirect(url_for("discovery.results", course_id=course_id, task_id=task_id))

    from database.repository import QuestionRepo
    pending_questions = QuestionRepo.get_pending_for_course(course_id)
    return render_template("discovery/run.html", course=course, pending_questions=pending_questions)


@discovery_bp.route("/<course_id>/results/<task_id>")
def results(course_id, task_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    task = get_task(task_id)

    # Nếu task đã hoàn tất, chỉ mark questions as processed
    # KHÔNG tự động lưu lỗ hổng vào DB — giảng viên sẽ chọn lỗ hổng cần lưu
    if task.get("status") == "done" and task.get("result"):
        save_discovery_results(course_id, task["result"])
        
        # Mark questions as processed
        from database.repository import QuestionRepo
        pending_questions = QuestionRepo.get_pending_for_course(course_id)
        if pending_questions:
            QuestionRepo.mark_processed([q.id for q in pending_questions])

    return render_template(
        "discovery/results.html",
        course=course,
        task_id=task_id,
        task=task,
    )


@discovery_bp.route("/<course_id>/save-gaps", methods=["POST"])
def save_gaps(course_id):
    """Lưu các lỗ hổng kiến thức đã được giảng viên chọn vào DB."""
    r = _require_login()
    if r:
        return r
    
    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("courses.detail", course_id=course_id))

    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    # Lấy danh sách indices đã chọn
    selected_indices = request.form.getlist("selected_gaps")
    
    if not selected_indices:
        flash("Bạn chưa chọn lỗ hổng nào để lưu.", "warning")
        return redirect(request.referrer or url_for("courses.detail", course_id=course_id))

    from database.repository import KnowledgeGapRepo
    from database.models import KnowledgeGap
    
    saved_count = 0
    for idx_str in selected_indices:
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        
        # Lấy tên đã sửa (nếu có)
        edited_title = request.form.get(f"gap_title_{idx}", "").strip()
        if not edited_title:
            continue
        
        # Kiểm tra lỗ hổng đã tồn tại chưa
        existing = KnowledgeGap.query.filter_by(course_id=course_id, title=edited_title).first()
        if not existing:
            KnowledgeGapRepo.create(course_id, edited_title, "Phát hiện từ câu hỏi sinh viên")
            saved_count += 1

    if saved_count > 0:
        flash(f"Đã lưu {saved_count} lỗ hổng kiến thức vào hệ thống.", "success")
    else:
        flash("Không có lỗ hổng mới nào được lưu (có thể đã tồn tại).", "info")

    return redirect(url_for("refinement.review", course_id=course_id))
