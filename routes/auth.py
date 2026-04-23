"""
KG2M - routes/auth.py
Đăng nhập / đăng xuất bằng session (in-memory, không cần DB).
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database.repository import UserRepo

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = UserRepo.get_by_email(email)
        if user and UserRepo.check_password(user, password):
            session["user_id"] = user.id
            flash("Đăng nhập thành công!", "success")
            return redirect(url_for("index"))
        flash("Email hoặc mật khẩu không đúng.", "error")
    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "student")
        
        if not email or not name or not password:
            flash("Vui lòng nhập đầy đủ thông tin.", "error")
            return render_template("auth/register.html")
            
        existing_user = UserRepo.get_by_email(email)
        if existing_user:
            flash("Email này đã được sử dụng.", "error")
            return render_template("auth/register.html")
            
        UserRepo.create(email=email, name=name, password=password, role=role)
        flash("Đăng ký thành công! Hãy đăng nhập.", "success")
        return redirect(url_for("auth.login"))
        
    return render_template("auth/register.html")


@auth_bp.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Đã đăng xuất.", "success")
    return redirect(url_for("auth.login"))
