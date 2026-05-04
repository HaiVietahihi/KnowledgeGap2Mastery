"""
KG2M - routes/refinement.py
Bước 2 (theo bài báo): Expert Refinement — giảng viên duyệt, gộp, đổi tên, xóa
các lỗ hổng kiến thức trước khi sinh LOP.
"""

import json
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, g, session)
from database.repository import CourseRepo
from services import get_discovery_results, save_discovery_results

refinement_bp = Blueprint("refinement", __name__, url_prefix="/refinement")


def _require_login():
    if not g.get("current_user"):
        return redirect(url_for("auth.login"))
    return None


@refinement_bp.route("/<course_id>")
def review(course_id):
    """Hiển thị trang duyệt lỗ hổng cho giảng viên."""
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    # Lấy kết quả discovery đã lưu
    discovery_data = get_discovery_results(course_id)
    if not discovery_data:
        flash("Chưa có kết quả phân tích. Vui lòng chạy phát hiện lỗ hổng trước.", "warning")
        return redirect(url_for("discovery.run", course_id=course_id))

    # Lọc ra các câu hỏi bị loại (has_gap = False)
    classified_posts = discovery_data.get("classified_posts", [])
    excluded_posts = [p for p in classified_posts if not p.get("has_gap", False)]

    return render_template(
        "refinement/review.html",
        course=course,
        knowledge_gaps=discovery_data.get("knowledge_gaps", []),
        excluded_posts=excluded_posts,
    )


@refinement_bp.route("/<course_id>/update", methods=["POST"])
def update(course_id):
    """Xử lý các thao tác duyệt: đổi tên, xóa, gộp."""
    r = _require_login()
    if r:
        return r
    course = CourseRepo.get(course_id)
    if not course:
        flash("Không tìm thấy khóa học.", "error")
        return redirect(url_for("index"))

    action = request.form.get("action", "")
    discovery_data = get_discovery_results(course_id)
    if not discovery_data:
        flash("Không tìm thấy dữ liệu phân tích.", "error")
        return redirect(url_for("discovery.run", course_id=course_id))

    gaps = discovery_data.get("knowledge_gaps", [])

    if action == "rename":
        idx = int(request.form.get("gap_index", -1))
        new_name = request.form.get("new_name", "").strip()
        if 0 <= idx < len(gaps) and new_name:
            old_name = gaps[idx]["knowledge_gap"]
            gaps[idx]["knowledge_gap"] = new_name
            flash(f'Đã đổi tên: "{old_name}" → "{new_name}"', "success")

    elif action == "delete":
        idx = int(request.form.get("gap_index", -1))
        if 0 <= idx < len(gaps):
            removed = gaps.pop(idx)
            flash(f'Đã xóa: "{removed["knowledge_gap"]}"', "success")

    elif action == "merge":
        indices_raw = request.form.get("merge_indices", "")
        merge_name = request.form.get("merge_name", "").strip()
        try:
            indices = sorted([int(i) for i in indices_raw.split(",") if i.strip()], reverse=True)
        except ValueError:
            indices = []

        if len(indices) >= 2 and merge_name:
            # Gộp coverage và posts
            merged_posts = []
            total_coverage = 0
            for idx in indices:
                if 0 <= idx < len(gaps):
                    total_coverage += gaps[idx].get("coverage", 0)
                    merged_posts.extend(gaps[idx].get("posts", []))

            # Xóa các gap cũ (từ index lớn → nhỏ)
            for idx in indices:
                if 0 <= idx < len(gaps):
                    gaps.pop(idx)

            # Thêm gap mới đã gộp
            gaps.insert(0, {
                "knowledge_gap": merge_name,
                "coverage": total_coverage,
                "cohesion": "Trung bình",
                "posts": merged_posts,
            })
            flash(f'Đã gộp {len(indices)} lỗ hổng thành: "{merge_name}"', "success")
        else:
            flash("Vui lòng chọn ít nhất 2 lỗ hổng và nhập tên mới để gộp.", "error")

    elif action == "save_to_db":
        indices_raw = request.form.get("save_indices", "")
        try:
            indices = sorted([int(i) for i in indices_raw.split(",") if i.strip()], reverse=True)
        except ValueError:
            indices = []

        if indices:
            from database.repository import KnowledgeGapRepo
            from database.models import KnowledgeGap
            saved_count = 0
            
            for idx in indices:
                if 0 <= idx < len(gaps):
                    gap_data = gaps[idx]
                    title = gap_data["knowledge_gap"]
                    existing = KnowledgeGap.query.filter_by(course_id=course_id, title=title).first()
                    if not existing:
                        KnowledgeGapRepo.create(course_id, title, "Phát hiện từ câu hỏi sinh viên")
                        saved_count += 1
                    # Remove from temp list so it doesn't show up again
                    gaps.pop(idx)
                    
            if saved_count > 0:
                flash(f"Đã lưu {saved_count} lỗ hổng vào hệ thống.", "success")
                return redirect(url_for("courses.detail", course_id=course_id))
            else:
                flash("Các lỗ hổng đã chọn có thể đã tồn tại trong hệ thống.", "info")
        else:
            flash("Vui lòng chọn ít nhất 1 lỗ hổng để lưu.", "error")

    # Lưu lại trạng thái của danh sách tạm (nếu chỉ đổi tên, xóa, gộp)
    discovery_data["knowledge_gaps"] = gaps
    save_discovery_results(course_id, discovery_data)

    return redirect(url_for("refinement.review", course_id=course_id))
