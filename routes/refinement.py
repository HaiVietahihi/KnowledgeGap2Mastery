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

    return render_template(
        "refinement/review.html",
        course=course,
        knowledge_gaps=discovery_data.get("knowledge_gaps", []),
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

    # Lưu lại
    discovery_data["knowledge_gaps"] = gaps
    save_discovery_results(course_id, discovery_data)

    return redirect(url_for("refinement.review", course_id=course_id))


@refinement_bp.route("/<course_id>/confirm", methods=["POST"])
def confirm(course_id):
    """Xác nhận duyệt xong → chuyển sang sinh LOP."""
    r = _require_login()
    if r:
        return r

    discovery_data = get_discovery_results(course_id)
    if not discovery_data or not discovery_data.get("knowledge_gaps"):
        flash("Không có lỗ hổng nào để sinh LOP.", "error")
        return redirect(url_for("refinement.review", course_id=course_id))

    # Lấy gap đầu tiên hoặc gap được chọn
    selected_idx = int(request.form.get("selected_gap", 0))
    gaps = discovery_data["knowledge_gaps"]
    if selected_idx >= len(gaps):
        selected_idx = 0

    gap = gaps[selected_idx]
    # Chuyển qua trang sinh LOP với gap và posts đã duyệt
    sample_posts = "\n\n".join(gap.get("posts", [])[:5])
    return redirect(
        url_for("generation.generate", course_id=course_id,
                gap=gap["knowledge_gap"],
                sample_posts=sample_posts)
    )
