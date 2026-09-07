from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from werkzeug.security import generate_password_hash

from configs.general_constants import DOMAIN_TO_NAME
from src.auth import admin_required, csrf_protected, generate_api_key, hash_api_key
from src.db import get_daily_trend, get_db, get_platform_distribution, get_top_users, set_setting, utcnow


bp = Blueprint("admin", __name__, url_prefix="/admin")


def _positive_int(value, default=1, maximum=1000):
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


@bp.get("")
@admin_required
def dashboard():
    try:
        days = int(request.args.get("days", 7))
        if days not in (7, 30, 90, 180, 0):
            days = 7
    except (TypeError, ValueError):
        days = 7

    db = get_db()
    users = db.execute(
        "SELECT u.*, COUNT(k.id) key_count FROM users u LEFT JOIN api_keys k ON k.user_id=u.id "
        "GROUP BY u.id ORDER BY u.id DESC"
    ).fetchall()
    configured = {row["platform"]: row for row in db.execute("SELECT * FROM platform_settings")}
    platforms = []
    for name in sorted(set(DOMAIN_TO_NAME.values())):
        row = configured.get(name)
        platforms.append({"name": name, "enabled": True if row is None else bool(row["enabled"]), "qps_limit": None if row is None else row["qps_limit"]})
    stats = db.execute(
        "SELECT COUNT(*) calls, SUM(status_code < 400) successes, COUNT(DISTINCT user_id) users "
        "FROM request_logs WHERE datetime(created_at) >= datetime('now','-1 day')"
    ).fetchone()
    api_keys = db.execute(
        "SELECT k.*, u.username, u.role user_role, u.qps_limit user_qps FROM api_keys k "
        "JOIN users u ON u.id=k.user_id ORDER BY k.id DESC"
    ).fetchall()
    logs = db.execute(
        "SELECT l.*, u.username, k.key_prefix FROM request_logs l "
        "LEFT JOIN users u ON u.id=l.user_id LEFT JOIN api_keys k ON k.id=l.api_key_id "
        "ORDER BY l.id DESC LIMIT 50"
    ).fetchall()
    settings = {row["key"]: row["value"] for row in db.execute("SELECT * FROM system_settings")}
    chart_data = get_daily_trend(user_id=None, days=days)
    pie_data = get_platform_distribution(user_id=None, days=days)
    top_users = get_top_users(days=days, limit=10)
    return render_template(
        "admin/dashboard.html",
        users=users,
        api_keys=api_keys,
        platforms=platforms,
        stats=stats,
        logs=logs,
        settings=settings,
        chart_data=chart_data,
        pie_data=pie_data,
        top_users=top_users,
        current_days=days,
        new_api_key=session.pop("new_api_key", None),
    )




@bp.post("/settings")
@admin_required
@csrf_protected
def update_settings():
    db = get_db()
    if request.form.get("action") == "reset":
        set_setting("global_api_enabled", "1")
        set_setting("demo_enabled", "1")
        set_setting("registration_enabled", "1")
        set_setting("default_user_qps", "2")
        set_setting("default_trial_days", "7")
        set_setting("default_initial_credits", "100")
        set_setting("api_tip_enabled", "1")
        set_setting("api_tip_author", "ucmao")
        set_setting("api_tip_website", "https://github.com/ucmao/media-parser")
        set_setting("api_tip_notice", "本接口由开源项目 media-parser 提供服务")
        db.commit()
        flash("已重置系统配置为默认值", "success")
        return redirect(url_for("admin.dashboard") + "#settings")

    for name in ("global_api_enabled", "demo_enabled", "registration_enabled", "api_tip_enabled"):
        set_setting(name, "1" if request.form.get(name) else "0")
    set_setting("default_user_qps", _positive_int(request.form.get("default_user_qps"), 2))
    set_setting("default_trial_days", _positive_int(request.form.get("default_trial_days"), 7, 365))
    try:
        init_cred = int(request.form.get("default_initial_credits", 100))
    except (TypeError, ValueError):
        init_cred = 100
    set_setting("default_initial_credits", init_cred)
    set_setting("api_tip_author", (request.form.get("api_tip_author") or "").strip() or "ucmao")
    set_setting("api_tip_website", (request.form.get("api_tip_website") or "").strip() or "https://github.com/ucmao/media-parser")
    set_setting("api_tip_notice", (request.form.get("api_tip_notice") or "").strip() or "本接口由开源项目 media-parser 提供服务")
    db.commit()
    flash("系统设置已保存", "success")
    return redirect(url_for("admin.dashboard") + "#settings")



@bp.post("/users/<int:user_id>")
@admin_required
@csrf_protected
def update_user(user_id):
    expires = request.form.get("expires_at", "").strip()
    expires_at = None
    if expires:
        try:
            local_end = datetime.combine(datetime.strptime(expires, "%Y-%m-%d").date(), time.max)
            expires_at = local_end.replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc).isoformat(timespec="seconds")
        except ValueError:
            flash("到期日期格式无效", "error")
            return redirect(url_for("admin.dashboard") + "#users")
    db = get_db()
    credits_raw = request.form.get("credits", "").strip()
    if credits_raw:
        try:
            user_credits = int(credits_raw)
            db.execute(
                "UPDATE users SET active=?, expires_at=?, qps_limit=?, credits=? WHERE id=? AND role!='admin'",
                (1 if request.form.get("active") else 0, expires_at, _positive_int(request.form.get("qps_limit"), 2), user_credits, user_id),
            )
        except ValueError:
            db.execute(
                "UPDATE users SET active=?, expires_at=?, qps_limit=? WHERE id=? AND role!='admin'",
                (1 if request.form.get("active") else 0, expires_at, _positive_int(request.form.get("qps_limit"), 2), user_id),
            )
    else:
        db.execute(
            "UPDATE users SET active=?, expires_at=?, qps_limit=? WHERE id=? AND role!='admin'",
            (1 if request.form.get("active") else 0, expires_at, _positive_int(request.form.get("qps_limit"), 2), user_id),
        )
    db.commit()
    flash("用户设置已保存", "success")
    return redirect(url_for("admin.dashboard") + "#users")


@bp.post("/keys/<int:key_id>/update")
@admin_required
@csrf_protected
def update_key(key_id):
    db = get_db()
    if "name" in request.form:
        name = request.form.get("name", "").strip()[:40]
        if name:
            db.execute("UPDATE api_keys SET name=? WHERE id=?", (name, key_id))

    if "active" in request.form or "qps_limit" in request.form:
        qps_raw = request.form.get("qps_limit", "").strip()
        qps = _positive_int(qps_raw) if qps_raw else None
        active = 1 if request.form.get("active") else 0
        db.execute("UPDATE api_keys SET active=?, qps_limit=? WHERE id=?", (active, qps, key_id))

    db.commit()
    flash("API Key 已成功更新", "success")
    return redirect(url_for("admin.dashboard") + "#keys")


@bp.post("/keys")
@admin_required
@csrf_protected
def create_key():
    name = request.form.get("name", "").strip()[:40] or "管理员专属密钥"
    target_user_id = request.form.get("user_id", "").strip()
    db = get_db()
    if target_user_id:
        user = db.execute("SELECT * FROM users WHERE id=?", (target_user_id,)).fetchone()
        if not user:
            flash("指定的归属账号不存在", "error")
            return redirect(url_for("admin.dashboard") + "#keys")
        user_id = user["id"]
        target_name = user["username"]
    else:
        user_id = g.user["id"]
        target_name = g.user["username"]

    qps_raw = request.form.get("qps_limit", "").strip()
    qps = _positive_int(qps_raw) if qps_raw else None

    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    key_prefix = raw_key[:7]

    db.execute(
        "INSERT INTO api_keys(user_id, name, key_hash, key_prefix, qps_limit, created_at) VALUES(?,?,?,?,?,?)",
        (user_id, name, key_hash, key_prefix, qps, utcnow()),
    )
    db.commit()
    session["new_api_key"] = raw_key
    flash(f"已为「{target_name}」成功创建 API 密钥「{name}」", "success")
    return redirect(url_for("admin.dashboard") + "#keys")


@bp.post("/keys/<int:key_id>/delete")
@admin_required
@csrf_protected
def delete_key(key_id):
    db = get_db()
    db.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
    db.commit()
    flash("API 密钥已彻底删除", "success")
    return redirect(url_for("admin.dashboard") + "#keys")



@bp.post("/platforms/<path:platform>")
@admin_required
@csrf_protected
def update_platform(platform):
    if platform not in set(DOMAIN_TO_NAME.values()):
        flash("未知平台", "error")
        return redirect(url_for("admin.dashboard") + "#platforms")
    qps_raw = request.form.get("qps_limit", "").strip()
    qps = _positive_int(qps_raw) if qps_raw else None
    db = get_db()
    db.execute(
        "INSERT INTO platform_settings(platform,enabled,qps_limit) VALUES(?,?,?) "
        "ON CONFLICT(platform) DO UPDATE SET enabled=excluded.enabled,qps_limit=excluded.qps_limit",
        (platform, 1 if request.form.get("enabled") else 0, qps),
    )
    db.commit()
    flash(f"{platform} 设置已保存", "success")
    return redirect(url_for("admin.dashboard") + "#platforms")


@bp.post("/users/<int:user_id>/reset-password")
@admin_required
@csrf_protected
def reset_password(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or user["role"] == "admin":
        flash("无法操作该用户账号", "error")
        return redirect(url_for("admin.dashboard") + "#users")

    new_password = request.form.get("new_password", "")
    if len(new_password) < 8:
        flash("重置密码至少需要 8 位", "error")
        return redirect(url_for("admin.dashboard") + "#users")

    db.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (generate_password_hash(new_password), user_id),
    )
    db.commit()
    flash(f"已成功重置客户「{user['username']}」的密码", "success")
    return redirect(url_for("admin.dashboard") + "#users")


