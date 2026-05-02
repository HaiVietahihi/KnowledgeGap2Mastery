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
        gap_id = request.form.get("gap_id", "").strip()
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

        # Lưu gap_id vào session để dùng khi task hoàn tất
        session[f"task_gap_id_{task_id}"] = gap_id if gap_id else ""

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
    
    # Kiểm tra đã lưu chưa (để hiển thị trạng thái trên UI)
    saved_flag_key = f"task_saved_{task_id}"
    already_saved = session.get(saved_flag_key, False)

    return render_template(
        "generation/view.html",
        course=course,
        task_id=task_id,
        task=task,
        already_saved=already_saved,
    )


@generation_bp.route("/<course_id>/save_lops/<task_id>", methods=["POST"])
def save_selected_lops(course_id, task_id):
    """Lưu các câu hỏi đã chọn (và có thể đã chỉnh sửa) vào DB."""
    r = _require_login()
    if r:
        return r

    import json
    from database.models import KnowledgeGap
    from database.repository import LearningOpportunityRepo, KnowledgeGapRepo
    
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))
    
    task = get_task(task_id)
    if task.get("status") != "done" or not task.get("result"):
        flash("Task chưa hoàn tất hoặc không có kết quả.", "error")
        return redirect(url_for("generation.view", course_id=course_id, task_id=task_id))

    result_data = task["result"]
    selected_indices = request.form.getlist("selected_lops")
    
    if not selected_indices:
        flash("Vui lòng chọn ít nhất 1 câu hỏi để lưu.", "error")
        return redirect(url_for("generation.view", course_id=course_id, task_id=task_id))

    # Tìm hoặc tạo gap
    knowledge_gap_text = result_data.get("metadata", {}).get("knowledge_gap", "")
    gap = None
    gap_id_str = session.pop(f"task_gap_id_{task_id}", "")
    
    if gap_id_str:
        try:
            gap = KnowledgeGap.query.get(int(gap_id_str))
        except (ValueError, TypeError):
            pass
    
    if not gap and knowledge_gap_text:
        gap = KnowledgeGap.query.filter_by(
            course_id=course_id, title=knowledge_gap_text
        ).first()
    
    if not gap and knowledge_gap_text:
        gap = KnowledgeGapRepo.create(
            course_id=course_id,
            title=knowledge_gap_text,
            description="Được tạo tự động khi sinh LOP"
        )

    if not gap:
        flash("Không thể xác định lỗ hổng kiến thức.", "error")
        return redirect(url_for("generation.view", course_id=course_id, task_id=task_id))

    saved_count = 0
    lops_list = result_data.get("lops", [])
    
    for idx_str in selected_indices:
        try:
            idx = int(idx_str)
            if 0 <= idx < len(lops_list):
                # Lấy nội dung đã chỉnh sửa từ form (nếu có)
                edited_json = request.form.get(f"lop_content_{idx}", "")
                meta = lops_list[idx].get("metadata", {})
                
                if edited_json:
                    try:
                        lop_content = json.loads(edited_json)
                    except json.JSONDecodeError:
                        lop_content = lops_list[idx].get("lop", {})
                else:
                    lop_content = lops_list[idx].get("lop", {})
                
                LearningOpportunityRepo.create(
                    gap_id=gap.id,
                    gap_type=meta.get("lop_type", "MCQ"),
                    content=json.dumps(lop_content, ensure_ascii=False),
                    bloom_level=meta.get("bloom_level", ""),
                    difficulty=meta.get("difficulty", "")
                )
                saved_count += 1
        except (ValueError, IndexError):
            continue

    # Đánh dấu đã lưu
    session[f"task_saved_{task_id}"] = True
    
    flash(f"Đã lưu {saved_count} câu hỏi vào ngân hàng câu hỏi.", "success")
    return redirect(url_for("generation.dashboard", course_id=course_id))


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


@generation_bp.route("/question_bank/<course_id>")
def question_bank(course_id):
    """Trang ngân hàng câu hỏi — xem, lọc, sửa, xóa câu hỏi."""
    r = _require_login()
    if r:
        return r

    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("index"))

    import json
    from database.models import KnowledgeGap
    from database.repository import LearningOpportunityRepo

    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    # Filter by gap
    selected_gap_id = request.args.get("gap_id", type=int)

    gaps = KnowledgeGap.query.filter_by(course_id=course_id).all()
    all_lops = LearningOpportunityRepo.get_by_course(course_id)
    mcq_lops = [lop for lop in all_lops if lop.type == "MCQ"]

    if selected_gap_id:
        mcq_lops = [lop for lop in mcq_lops if lop.gap_id == selected_gap_id]

    # Build structured question data grouped by gap
    gap_questions_map = {}
    total_questions = 0

    for lop in mcq_lops:
        try:
            parsed = json.loads(lop.content)
            q_data = parsed
            if isinstance(parsed, dict) and "lops" in parsed:
                q_data = parsed["lops"][0] if parsed["lops"] else parsed
            elif isinstance(parsed, list):
                q_data = parsed[0] if parsed else {}

            if isinstance(q_data, dict) and "lop" in q_data:
                q_data = q_data["lop"]

            if not isinstance(q_data, dict) or not q_data.get("cau_hoi"):
                continue

            gap_title = lop.gap.title
            gap_id = lop.gap.id

            question_info = {
                "lop_id": lop.id,
                "cau_hoi": q_data.get("cau_hoi", ""),
                "dap_an": q_data.get("dap_an", {}),
                "dap_an_dung": q_data.get("dap_an_dung", ""),
                "giai_thich": q_data.get("giai_thich", ""),
                "bloom_level": lop.bloom_level,
                "difficulty": lop.difficulty,
            }

            if gap_id not in gap_questions_map:
                gap_questions_map[gap_id] = {
                    "gap_id": gap_id,
                    "gap_title": gap_title,
                    "questions": []
                }
            gap_questions_map[gap_id]["questions"].append(question_info)
            total_questions += 1
        except Exception:
            continue

    questions_by_gap = list(gap_questions_map.values())

    # Build gap_list with question counts for the filter dropdown
    gap_count_map = {}
    for lop in [l for l in LearningOpportunityRepo.get_by_course(course_id) if l.type == "MCQ"]:
        gap_count_map[lop.gap_id] = gap_count_map.get(lop.gap_id, 0) + 1

    class GapInfo:
        def __init__(self, gap, q_count):
            self.id = gap.id
            self.title = gap.title
            self.q_count = q_count

    gap_list = [GapInfo(g, gap_count_map.get(g.id, 0)) for g in gaps if gap_count_map.get(g.id, 0) > 0]

    return render_template(
        "generation/question_bank.html",
        course=course,
        questions_by_gap=questions_by_gap,
        total_questions=total_questions,
        gap_list=gap_list,
        selected_gap_id=selected_gap_id,
    )


@generation_bp.route("/question_bank/<course_id>/edit/<int:lop_id>", methods=["POST"])
def question_bank_edit(course_id, lop_id):
    """Cập nhật nội dung câu hỏi từ form inline."""
    r = _require_login()
    if r:
        return r

    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("index"))

    import json
    from database.repository import LearningOpportunityRepo

    lop = LearningOpportunityRepo.get(lop_id)
    if not lop:
        flash("Không tìm thấy câu hỏi.", "error")
        return redirect(url_for("generation.question_bank", course_id=course_id))

    # Rebuild JSON from form fields
    cau_hoi = request.form.get("cau_hoi", "").strip()
    dap_an_dung = request.form.get("dap_an_dung", "A")
    giai_thich = request.form.get("giai_thich", "").strip()

    dap_an = {}
    for key in ["A", "B", "C", "D"]:
        val = request.form.get(f"dap_an_{key}", "").strip()
        if val:
            dap_an[key] = val

    new_content = {
        "cau_hoi": cau_hoi,
        "dap_an": dap_an,
        "dap_an_dung": dap_an_dung,
        "giai_thich": giai_thich,
    }

    LearningOpportunityRepo.update_content(
        lop_id,
        json.dumps(new_content, ensure_ascii=False)
    )

    flash("Đã cập nhật câu hỏi thành công.", "success")
    return redirect(url_for("generation.question_bank", course_id=course_id))


@generation_bp.route("/question_bank/<course_id>/delete/<int:lop_id>", methods=["POST"])
def question_bank_delete(course_id, lop_id):
    """Xóa câu hỏi khỏi ngân hàng."""
    r = _require_login()
    if r:
        return r

    user = g.current_user
    if user.role != "instructor":
        flash("Chỉ giảng viên mới có chức năng này.", "error")
        return redirect(url_for("index"))

    from database.repository import LearningOpportunityRepo

    if LearningOpportunityRepo.delete(lop_id):
        flash("Đã xóa câu hỏi.", "success")
    else:
        flash("Không tìm thấy câu hỏi.", "error")

    return redirect(url_for("generation.question_bank", course_id=course_id))
