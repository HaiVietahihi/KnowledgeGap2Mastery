"""
KG2M - app.py
Demo version 
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, g, session

from database.db import init_db
from database.repository import UserRepo, CourseRepo

load_dotenv()


# ─── App factory ─────────────────────────────────────────────────────────────

def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET", "kg2m-dev-secret")
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(base_dir, "kg2m.db")}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    base_dir = os.path.dirname(os.path.abspath(__file__))
    Path(os.path.join(base_dir, "data")).mkdir(exist_ok=True)
    Path(os.path.join(base_dir, "uploads")).mkdir(exist_ok=True)

    # Seed demo data (in-memory)
    init_db(app)

    # ── Register blueprints ──
    from routes.auth import auth_bp
    from routes.courses import courses_bp
    from routes.discovery import discovery_bp
    from routes.refinement import refinement_bp
    from routes.generation import generation_bp
    from routes.api import api_bp
    from routes.analytics import analytics_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(discovery_bp)
    app.register_blueprint(refinement_bp)
    app.register_blueprint(generation_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(analytics_bp)

    # ── Middleware ──
    @app.before_request
    def load_current_user():
        g.current_user = None
        user_id = session.get("user_id")
        if user_id:
            g.current_user = UserRepo.get_by_id(user_id)

    @app.context_processor
    def inject_user():
        return {"current_user": g.get("current_user")}

    # ── Index route ──
    @app.route("/")
    def index():
        if not g.get("current_user"):
            return redirect(url_for("auth.login"))
        user = g.current_user
        courses = CourseRepo.list_all() if user.role == "instructor" else CourseRepo.list_for_user(user.id)
        
        course_stats = {}
        for c in courses:
            stats = CourseRepo.get_stats(c.id)
            course_stats[c.id] = stats
            
        return render_template("index.html", courses=courses, course_stats=course_stats)

    return app


if __name__ == "__main__":
    app = create_app()
    print("=" * 50)
    print("  KG2M Demo dang chay tai http://localhost:5000")
    print("  Tai khoan: admin@kg2m.local / admin123")
    print("=" * 50)
    app.run(debug=True, port=5000)
