"""
KG2M - routes/analytics.py
Dashboard Analytics cho giảng viên — thống kê tổng hợp khóa học.
"""

import json
from flask import (Blueprint, render_template, redirect,
                   url_for, flash, g)
from database.repository import CourseRepo, UserRepo

analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")


def _require_instructor():
    if not g.get("current_user"):
        return redirect(url_for("auth.login"))
    if g.current_user.role != "instructor":
        flash("Chỉ giảng viên mới có quyền truy cập.", "error")
        return redirect(url_for("index"))
    return None


def _parse_score(score_str):
    """Parse score string like '8/10' to float value on 10 scale."""
    if not score_str:
        return None
    parts = score_str.split("/")
    if len(parts) == 2:
        try:
            return round(float(parts[0]) / float(parts[1]) * 10, 1)
        except (ValueError, ZeroDivisionError):
            pass
    return None


def _build_lop_gap_map(course_id):
    """
    Build a lookup map from LOP content -> gap_title.
    Uses the 'cau_hoi' field as the matching key since it's unique per question.
    Returns: dict mapping cau_hoi_text -> gap_title
    """
    from database.models import LearningOpportunity, KnowledgeGap
    lops = LearningOpportunity.query.join(KnowledgeGap).filter(
        KnowledgeGap.course_id == course_id
    ).all()

    lookup = {}
    for lop in lops:
        gap_title = lop.gap.title if lop.gap else "Khac"
        try:
            parsed = json.loads(lop.content)
            items = []
            if isinstance(parsed, dict) and "lops" in parsed:
                items = parsed["lops"]
            elif isinstance(parsed, list):
                items = parsed
            else:
                items = [parsed]

            for item in items:
                if isinstance(item, dict):
                    inner = item.get("lop", item)
                    if isinstance(inner, dict) and "cau_hoi" in inner:
                        lookup[inner["cau_hoi"]] = gap_title
                    elif "cau_hoi" in item:
                        lookup[item["cau_hoi"]] = gap_title
        except Exception:
            continue

    return lookup


def _resolve_gap(q_dict, lop_gap_map):
    """Resolve gap title from a question dict using the LOP->Gap lookup map."""
    if not lop_gap_map or not isinstance(q_dict, dict):
        return "Khac"
    cau_hoi = q_dict.get("cau_hoi", "")
    if cau_hoi and cau_hoi in lop_gap_map:
        return lop_gap_map[cau_hoi]
    return "Khac"


def _get_question_data(q_item, lop_gap_map=None):
    """
    Extract question data and gap_title from a question item.
    Handles multiple formats:
      1. {"q_data": {...}, "gap_title": "..."} - new format with wrapper
      2. {"lop": {...}} - nested LOP format
      3. {"cau_hoi": ..., "dap_an": ...} - flat dict (legacy format)
    For formats 2 & 3, uses lop_gap_map to look up the actual gap title.
    """
    if isinstance(q_item, dict) and "q_data" in q_item:
        return q_item["q_data"], q_item.get("gap_title", "Khac")

    if isinstance(q_item, dict) and "lop" in q_item:
        inner = q_item["lop"]
        gap_title = _resolve_gap(inner, lop_gap_map)
        return inner, gap_title

    if isinstance(q_item, dict) and "cau_hoi" in q_item:
        gap_title = _resolve_gap(q_item, lop_gap_map)
        return q_item, gap_title

    return q_item, "Khac"


@analytics_bp.route("/<course_id>")
def dashboard(course_id):
    r = _require_instructor()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    from database.models import (Question, KnowledgeGap, LearningOpportunity,
                                  Assignment, AssignmentSubmission, Document)
    from database.repository import AssignmentRepo, AssignmentSubmissionRepo

    # Build LOP->Gap lookup (resolves legacy assignments without gap_title)
    lop_gap_map = _build_lop_gap_map(course_id)

    # 1. Student stats
    enrolled_students = UserRepo.get_enrolled_students(course_id)
    total_students = len(enrolled_students)

    # 2. Document stats
    documents = Document.query.filter_by(course_id=course_id).all()
    total_docs = len(documents)
    total_pages = sum(d.page_count or 0 for d in documents)

    # 3. Question stats
    all_questions = Question.query.filter_by(course_id=course_id).all()
    total_questions = len(all_questions)
    pending_questions = sum(1 for q in all_questions if q.status == "pending")

    # 4. Knowledge Gap stats
    gaps = KnowledgeGap.query.filter_by(course_id=course_id).all()
    total_gaps = len(gaps)

    # 5. Assignments & submissions
    assignments = AssignmentRepo.get_by_course(course_id)
    total_assignments = len(assignments)

    assignment_stats = []
    all_scores = []
    all_wrong_questions = []

    for a in assignments:
        submissions = AssignmentSubmissionRepo.get_by_assignment(a.id)
        completed = [s for s in submissions if s.status == "completed"]

        try:
            content_data = json.loads(a.content)
            questions = content_data.get("questions", [])
        except Exception:
            questions = []

        a_scores = []
        for sub in completed:
            val = _parse_score(sub.score)
            if val is not None:
                a_scores.append(val)
                all_scores.append(val)

        avg_score = round(sum(a_scores) / len(a_scores), 1) if a_scores else 0

        for i, q_item in enumerate(questions):
            q, gap_title = _get_question_data(q_item, lop_gap_map)
            correct_answer = q.get("dap_an_dung") if isinstance(q, dict) else None
            wrong_count = 0

            for sub in completed:
                if sub.answers:
                    try:
                        ans_dict = json.loads(sub.answers)
                        student_ans = ans_dict.get(str(i))
                        if student_ans is not None and student_ans != correct_answer:
                            wrong_count += 1
                    except Exception:
                        pass

            total_attempted = len(completed)
            wrong_pct = round(wrong_count / total_attempted * 100, 1) if total_attempted > 0 else 0

            all_wrong_questions.append({
                "assignment_title": a.title,
                "assignment_id": a.id,
                "question_index": i + 1,
                "question_text": q.get("cau_hoi", f"Cau hoi {i+1}") if isinstance(q, dict) else str(q)[:80],
                "gap_title": gap_title,
                "wrong_count": wrong_count,
                "total_attempted": total_attempted,
                "wrong_pct": wrong_pct,
            })

        completion_pct = round(len(completed) / total_students * 100) if total_students > 0 else 0
        assignment_stats.append({
            "id": a.id,
            "title": a.title,
            "total_questions": len(questions),
            "total_submissions": len(completed),
            "total_students": total_students,
            "avg_score": avg_score,
            "completion_pct": completion_pct,
            "created_at": a.created_at,
        })

    all_wrong_questions.sort(key=lambda x: x["wrong_pct"], reverse=True)
    top_wrong = all_wrong_questions[:10]

    # 6. Overall stats
    overall_avg_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0
    total_completed_subs = sum(a["total_submissions"] for a in assignment_stats)
    total_possible = total_students * total_assignments if total_students and total_assignments else 0
    overall_completion_pct = round(total_completed_subs / total_possible * 100) if total_possible > 0 else 0

    active_ids = set()
    for a in assignments:
        for sub in AssignmentSubmissionRepo.get_by_assignment(a.id):
            if sub.status == "completed":
                active_ids.add(sub.student_id)
    active_students = len(active_ids)

    # 7. Per-student progress
    student_progress = []
    for st in enrolled_students:
        st_done = 0
        st_scores = []
        st_weak = set()

        for a in assignments:
            sub = AssignmentSubmission.query.filter_by(
                student_id=st.id, assignment_id=a.id, status="completed"
            ).first()

            if sub:
                st_done += 1
                val = _parse_score(sub.score)
                if val is not None:
                    st_scores.append(val)

                try:
                    cdata = json.loads(a.content)
                    qs = cdata.get("questions", [])
                    ans_dict = json.loads(sub.answers) if sub.answers else {}
                    for i, q_item in enumerate(qs):
                        q, gap_title = _get_question_data(q_item, lop_gap_map)
                        correct = q.get("dap_an_dung") if isinstance(q, dict) else None
                        s_ans = ans_dict.get(str(i))
                        if s_ans and correct and s_ans != correct and gap_title:
                            st_weak.add(gap_title)
                except Exception:
                    pass

        st_avg = round(sum(st_scores) / len(st_scores), 1) if st_scores else 0
        progress_pct = round(st_done / total_assignments * 100) if total_assignments > 0 else 0

        student_progress.append({
            "id": st.id,
            "name": st.name,
            "email": st.email,
            "assignments_done": st_done,
            "total_assignments": total_assignments,
            "avg_score": st_avg,
            "progress_pct": progress_pct,
            "weak_gaps": list(st_weak)[:3],
        })

    student_progress.sort(key=lambda x: x["avg_score"])

    # 8. Score distribution (histogram bins 0-10)
    score_distribution = [0] * 11
    for s in all_scores:
        score_distribution[min(int(s), 10)] += 1

    # 9. Gap performance data
    gap_data = []
    for gap in gaps:
        lop_count = LearningOpportunity.query.filter_by(gap_id=gap.id).count()
        related_wrong = sum(wq["wrong_count"] for wq in all_wrong_questions if wq["gap_title"] == gap.title)
        related_total = sum(wq["total_attempted"] for wq in all_wrong_questions if wq["gap_title"] == gap.title)
        wrong_rate = round(related_wrong / related_total * 100, 1) if related_total > 0 else 0

        gap_data.append({
            "title": gap.title[:40] + ("..." if len(gap.title) > 40 else ""),
            "full_title": gap.title,
            "lop_count": lop_count,
            "wrong_rate": wrong_rate,
        })

    gap_data.sort(key=lambda x: x["wrong_rate"], reverse=True)

    return render_template(
        "analytics/dashboard.html",
        course=course,
        total_students=total_students,
        active_students=active_students,
        total_docs=total_docs,
        total_pages=total_pages,
        total_questions=total_questions,
        pending_questions=pending_questions,
        total_gaps=total_gaps,
        total_assignments=total_assignments,
        overall_avg_score=overall_avg_score,
        overall_completion_pct=overall_completion_pct,
        assignment_stats=assignment_stats,
        top_wrong=top_wrong,
        student_progress=student_progress,
        score_distribution=json.dumps(score_distribution),
        gap_data=gap_data,
        gap_labels=json.dumps([g["title"] for g in gap_data[:8]]),
        gap_wrong_rates=json.dumps([g["wrong_rate"] for g in gap_data[:8]]),
        total_completed_subs=total_completed_subs,
        total_possible=total_possible,
    )


@analytics_bp.route("/<course_id>/student/<int:student_id>")
def student_detail(course_id, student_id):
    r = _require_instructor()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    from database.models import User, AssignmentSubmission
    from database.repository import AssignmentRepo

    student = User.query.get(student_id)
    if not student:
        flash("Không tìm thấy sinh viên.", "error")
        return redirect(url_for("analytics.dashboard", course_id=course_id))

    # Build LOP->Gap lookup
    lop_gap_map = _build_lop_gap_map(course_id)

    assignments = AssignmentRepo.get_by_course(course_id)
    student_assignments = []
    gap_performance = {}

    for a in assignments:
        sub = AssignmentSubmission.query.filter_by(
            student_id=student_id, assignment_id=a.id
        ).first()

        try:
            content_data = json.loads(a.content)
            questions = content_data.get("questions", [])
        except Exception:
            questions = []

        score_val = None
        status = "Chưa làm"
        wrong_questions = []

        if sub and sub.status == "completed":
            status = "Đã hoàn thành"
            score_val = _parse_score(sub.score)

            try:
                ans_dict = json.loads(sub.answers) if sub.answers else {}
                for i, q_item in enumerate(questions):
                    q, gap_title = _get_question_data(q_item, lop_gap_map)
                    correct = q.get("dap_an_dung") if isinstance(q, dict) else None
                    student_ans = ans_dict.get(str(i))

                    if gap_title not in gap_performance:
                        gap_performance[gap_title] = {"correct": 0, "total": 0}

                    if student_ans is not None:
                        gap_performance[gap_title]["total"] += 1
                        if student_ans == correct:
                            gap_performance[gap_title]["correct"] += 1
                        else:
                            q_text = q.get("cau_hoi", f"Cau {i+1}") if isinstance(q, dict) else str(q)
                            wrong_questions.append({
                                "index": i + 1,
                                "question": q_text,
                                "gap": gap_title,
                                "student_answer": student_ans,
                                "correct_answer": correct,
                            })
            except Exception:
                pass

        student_assignments.append({
            "id": a.id,
            "title": a.title,
            "status": status,
            "score": sub.score if sub else None,
            "score_val": score_val,
            "completed_at": sub.completed_at if sub else None,
            "wrong_questions": wrong_questions,
            "total_questions": len(questions),
        })

    # Gap summary
    gap_summary = []
    for gap_title, data in gap_performance.items():
        accuracy = round(data["correct"] / data["total"] * 100) if data["total"] > 0 else 0
        if accuracy >= 70:
            status_label = "Tốt"
        elif accuracy >= 40:
            status_label = "Cần cải thiện"
        else:
            status_label = "Yếu"
        gap_summary.append({
            "title": gap_title,
            "correct": data["correct"],
            "total": data["total"],
            "accuracy": accuracy,
            "status": status_label,
        })
    gap_summary.sort(key=lambda x: x["accuracy"])

    total_done = sum(1 for a in student_assignments if a["status"] == "Đã hoàn thành")
    scores = [a["score_val"] for a in student_assignments if a["score_val"] is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    return render_template(
        "analytics/student_detail.html",
        course=course,
        student=student,
        student_assignments=student_assignments,
        gap_summary=gap_summary,
        total_done=total_done,
        total_assignments=len(assignments),
        avg_score=avg_score,
        gap_labels=json.dumps([g["title"][:30] for g in gap_summary]),
        gap_accuracies=json.dumps([g["accuracy"] for g in gap_summary]),
    )
