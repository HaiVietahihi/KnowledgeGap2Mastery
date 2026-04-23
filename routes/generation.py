"""
KG2M - routes/generation.py
Sinh cơ hội học tập (Learning Opportunity) dựa trên lỗ hổng đã phát hiện.
"""

import uuid
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, g, session)
from database.repository import CourseRepo
from services import get_services, run_task, get_task

generation_bp = Blueprint("generation", __name__, url_prefix="/generation")


def _require_login():
    if not g.get("current_user"):
        return redirect(url_for("auth.login"))
    return None


@generation_bp.route("/<course_id>", methods=["GET", "POST"])
def generate(course_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    from database.models import KnowledgeGap
    gaps = KnowledgeGap.query.filter_by(course_id=course_id).all()

    if request.method == "POST":
        knowledge_gap = request.form.get("knowledge_gap", "").strip()
        sample_posts_raw = request.form.get("sample_posts", "").strip()
        lop_type = request.form.get("lop_type", "MCQ")
        bloom_level = request.form.get("bloom_level", "ap_dung")
        difficulty = request.form.get("difficulty", "trung_binh")
        try:
            num_questions = int(request.form.get("num_questions", "1"))
        except ValueError:
            num_questions = 1

        if not knowledge_gap:
            flash("Vui lòng nhập lỗ hổng kiến thức.", "error")
            return render_template("generation/generate.html", course=course)

        sample_posts = [p.strip() for p in sample_posts_raw.split("\n\n") if p.strip()] or ["(không có bài mẫu)"]

        task_id = f"gen-{uuid.uuid4().hex[:8]}"
        _, _, generator = get_services()

        def do_generate():
            return generator.generate(
                knowledge_gap, sample_posts, course_id,
                lop_type, bloom_level, difficulty,
                course_name=course.name,
                num_questions=num_questions
            )

        run_task(task_id, do_generate)
        return redirect(url_for("generation.view", course_id=course_id, task_id=task_id))

    return render_template("generation/generate.html", course=course, gaps=gaps)


@generation_bp.route("/<course_id>/view/<task_id>")
def view(course_id, task_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    task = get_task(task_id)
    # Nếu task đã hoàn tất, lưu kết quả
    if task.get("status") == "done" and task.get("result"):
        result_data = task["result"]
        import json
        
        # Save Learning Opportunity to DB
        from database.models import KnowledgeGap, db
        from database.repository import LearningOpportunityRepo
        
        knowledge_gap_text = result_data.get("metadata", {}).get("knowledge_gap", "")
        # Find the gap ID
        gap = KnowledgeGap.query.filter_by(course_id=course_id, title=knowledge_gap_text).first()
        
        if gap and "lops" in result_data:
            # check to see if we already created lops for this task so we don't duplicate on page reload
            from database.models import LearningOpportunity
            existing = LearningOpportunity.query.filter_by(gap_id=gap.id).count()
            if existing == 0:
                for lop_item in result_data["lops"]:
                    lop_content = lop_item.get("lop", {})
                    meta = lop_item.get("metadata", {})
                    
                    LearningOpportunityRepo.create(
                        gap_id=gap.id,
                        gap_type=meta.get("lop_type", "MCQ"),
                        content=json.dumps(lop_content, ensure_ascii=False),
                        bloom_level=meta.get("bloom_level", ""),
                        difficulty=meta.get("difficulty", "")
                    )

    return render_template(
        "generation/view.html",
        course=course,
        task_id=task_id,
        task=task,
    )


@generation_bp.route("/dashboard/<course_id>")
def dashboard(course_id):
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    
    from database.models import KnowledgeGap
    from database.repository import LearningOpportunityRepo, AssignmentRepo
    gaps = KnowledgeGap.query.filter_by(course_id=course_id).all()
    opportunities = LearningOpportunityRepo.get_by_course(course_id)
    assignments = AssignmentRepo.get_by_course(course_id)
    
    return render_template("generation/dashboard.html", course=course, gaps=gaps, opportunities=opportunities, assignments=assignments)

@generation_bp.route("/create_assignment/<course_id>", methods=["GET", "POST"])
def create_assignment(course_id):
    r = _require_login()
    if r:
        return r
        
    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("index"))
        
    from database.repository import LearningOpportunityRepo, AssignmentRepo, CourseRepo
    import json
    
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    # Chỉ lấy LOP loại MCQ
    all_opportunities = LearningOpportunityRepo.get_by_course(course_id)
    mcq_opportunities = [lop for lop in all_opportunities if lop.type == "MCQ"]
    if not mcq_opportunities:
        flash("Khóa học này chưa có câu hỏi trắc nghiệm (MCQ) nào.", "error")
        return redirect(url_for('generation.dashboard', course_id=course_id))

    all_questions = []
    # Build a flat list of MCQ questions with their parent GAP info
    for lop in mcq_opportunities:
        try:
            parsed = json.loads(lop.content)
            questions_list = []

            if isinstance(parsed, dict) and "lops" in parsed:
                questions_list = parsed["lops"]
            elif isinstance(parsed, list):
                questions_list = parsed
            else:
                questions_list = [parsed]

            for q_data in questions_list:
                inner_q = q_data.get("lop", q_data) if isinstance(q_data, dict) else q_data
                # Chỉ thêm nếu là MCQ hợp lệ (có câu hỏi và đáp án)
                if not isinstance(inner_q, dict):
                    continue
                if not inner_q.get("cau_hoi") or not inner_q.get("dap_an") or not inner_q.get("dap_an_dung"):
                    continue
                all_questions.append({
                    "lop_id": lop.id,
                    "gap_title": lop.gap.title,
                    "gap_id": lop.gap.id,
                    "global_index": len(all_questions),
                    "q_data": inner_q
                })
        except:
            continue

    if request.method == "POST":
        title = request.form.get("title", f"Bài tập tổng hợp").strip()
        selected_indices = request.form.getlist("question_indices")
        if not selected_indices:
            flash("Vui lòng chọn ít nhất 1 câu hỏi.", "error")
            return render_template("generation/create_assignment.html", course=course, all_questions=all_questions)
            
        selected_questions = []
        for idx_str in selected_indices:
            idx = int(idx_str)
            if 0 <= idx < len(all_questions):
                selected_questions.append({
                    "gap_title": all_questions[idx]["gap_title"],
                    "q_data": all_questions[idx]["q_data"]
                })
                
        assignment_content = json.dumps({"questions": selected_questions}, ensure_ascii=False)
        AssignmentRepo.create(course_id, title, assignment_content)
        flash("Đã tạo Bài Tập thành công.", "success")
        return redirect(url_for('generation.dashboard', course_id=course_id))
        
    return render_template("generation/create_assignment.html", course=course, all_questions=all_questions)

@generation_bp.route("/assignment_dashboard/<int:assignment_id>")
def assignment_dashboard(assignment_id):
    r = _require_login()
    if r:
        return r
        
    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("index"))
        
    from database.repository import AssignmentRepo, AssignmentSubmissionRepo, UserRepo
    import json
    
    assignment = AssignmentRepo.get(assignment_id)
    if not assignment:
        flash("Không tìm thấy Bài tập.", "error")
        return redirect(url_for('index'))
        
    submissions = AssignmentSubmissionRepo.get_by_assignment(assignment_id)
    enrolled_students = UserRepo.get_enrolled_students(assignment.course_id)
    
    total_students = len(enrolled_students)
    total_completed = sum(1 for s in submissions if s.status == "completed")
    total_not_completed = total_students - total_completed
    
    # Calculate stats
    try:
        content_data = json.loads(assignment.content)
        questions = content_data.get("questions", [])
    except:
        questions = []
    
    gap_stats = {}
    for i, q_item in enumerate(questions):
        if isinstance(q_item, dict) and "q_data" in q_item:
            q = q_item["q_data"]
            gap_title = q_item.get("gap_title", "Khác")
        else:
            q = q_item.get("lop", {}) if isinstance(q_item, dict) and "lop" in q_item else q_item
            gap_title = "Tổng hợp"
            
        correct_answer = q.get("dap_an_dung")
        wrong_count = 0
        
        for sub in submissions:
            if sub.status == "completed" and sub.answers:
                try:
                    ans_dict = json.loads(sub.answers)
                    student_ans = ans_dict.get(str(i))
                    if student_ans is not None:
                        if student_ans != correct_answer:
                            wrong_count += 1
                except:
                    pass
                    
        q_stat = {
            "index": i + 1,
            "question": q.get("cau_hoi", f"Câu hỏi {i+1}"),
            "wrong_count": wrong_count,
            "total_count": total_completed,
            "wrong_percentage": round((wrong_count / total_completed * 100), 1) if total_completed > 0 else 0
        }
        
        if gap_title not in gap_stats:
            gap_stats[gap_title] = []
        gap_stats[gap_title].append(q_stat)
        
    return render_template("generation/assignment_dashboard.html", 
                           assignment=assignment, 
                           course=assignment.course, 
                           submissions=submissions, 
                           enrolled_students=enrolled_students,
                           gap_stats=gap_stats,
                           total_completed=total_completed,
                           total_not_completed=total_not_completed)


@generation_bp.route("/edit/<int:lop_id>", methods=["GET", "POST"])
def edit(lop_id):
    r = _require_login()
    if r:
        return r
        
    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("index"))
        
    from database.repository import LearningOpportunityRepo
    from database.models import db
    import json
    
    lop = LearningOpportunityRepo.get(lop_id)
    if not lop:
        flash("Không tìm thấy bài tập.", "error")
        return redirect(url_for("index"))
        
    if request.method == "POST":
        # Parse updated JSON
        content_str = request.form.get("content", "")
        try:
            # Validate JSON
            parsed = json.loads(content_str)
            lop.content = json.dumps(parsed, ensure_ascii=False)
            db.session.commit()
            flash("Đã cập nhật bài tập thành công.", "success")
            return redirect(url_for("generation.dashboard", course_id=lop.gap.course_id))
        except json.JSONDecodeError:
            flash("Nội dung JSON không hợp lệ. Vui lòng kiểm tra lại cú pháp.", "error")
            
    content_json = json.dumps(json.loads(lop.content), ensure_ascii=False, indent=4) if lop.content else "{}"
    return render_template("generation/edit.html", lop=lop, content_json=content_json, course=lop.gap.course)
