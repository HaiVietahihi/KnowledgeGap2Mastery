"""
KG2M - routes/api.py
JSON API cho polling task status và các thao tác AJAX.
"""

from flask import Blueprint, jsonify
from services import get_task, get_services

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/task/<task_id>")
def task_status(task_id):
    task = get_task(task_id)
    return jsonify(task)


@api_bp.route("/upload-status/<doc_id>")
def upload_status(doc_id):
    """Kiểm tra trạng thái xử lý document trên PageIndex."""
    ingestion, _, _ = get_services()
    result = ingestion.check_document_status(doc_id)
    return jsonify(result)
