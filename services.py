"""
KG2M - services.py
Singleton services & background task manager.
Tách riêng khỏi app.py để tránh circular import với routes.
"""

import os
import threading
from dotenv import load_dotenv

load_dotenv()

# ── Services (lazy singleton) ────────────────────────────────────────────────

_services = None


def get_services():
    global _services
    if _services is None:
        from core.ingestion import CourseIngestion
        from core.discovery import KnowledgeGapDiscovery
        from core.generation import LOPGenerator

        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "data")
        
        ingestion = CourseIngestion(data_dir)
        discovery = KnowledgeGapDiscovery("", ingestion)
        generator = LOPGenerator("", ingestion)
        _services = (ingestion, discovery, generator)
    return _services


# ── Background task manager ──────────────────────────────────────────────────

_tasks: dict = {}


def run_task(task_id: str, fn, *args, **kwargs):
    _tasks[task_id] = {"status": "running", "result": None, "error": None}

    # Capture Flask app object (if we are inside a request/app context)
    app = None
    try:
        from flask import current_app
        app = current_app._get_current_object()
    except Exception:
        app = None

    def worker():
        try:
            if app is not None:
                with app.app_context():
                    result = fn(*args, **kwargs)
            else:
                result = fn(*args, **kwargs)
            _tasks[task_id].update({"result": result, "status": "done"})
        except Exception as e:
            _tasks[task_id].update({"error": str(e), "status": "error"})

    threading.Thread(target=worker, daemon=True).start()


def get_task(task_id: str) -> dict:
    return _tasks.get(task_id, {"status": "not_found"})


# ── Discovery results store (for Expert Refinement step) ─────────────────────

_discovery_results: dict = {}


def save_discovery_results(course_id: str, data: dict):
    """Lưu kết quả discovery để bước Refinement truy cập."""
    _discovery_results[course_id] = data


def get_discovery_results(course_id: str) -> dict | None:
    """Lấy kết quả discovery đã lưu."""
    return _discovery_results.get(course_id)
