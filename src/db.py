import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from flask import current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin', 'user')),
    active INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT,
    qps_limit INTEGER NOT NULL DEFAULT 2,
    credits INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    qps_limit INTEGER,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS platform_settings (
    platform TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    qps_limit INTEGER
);
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    api_key_id INTEGER,
    platform TEXT,
    path TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    error_code TEXT,
    duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limit_buckets (
    subject TEXT NOT NULL,
    bucket_second INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY(subject, bucket_second)
);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON request_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_user_id ON request_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rate_limit_bucket_time ON rate_limit_buckets(bucket_second);
"""


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        database = current_app.config["DATABASE"]
        g.db = sqlite3.connect(database, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 10000")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    db.executescript(SCHEMA)
    columns = [row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()]
    if "credits" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN credits INTEGER NOT NULL DEFAULT 100")
    defaults = {
        "global_api_enabled": "1",
        "demo_enabled": "1",
        "registration_enabled": "1",
        "default_user_qps": "2",
        "default_trial_days": "7",
        "default_initial_credits": "100",
        "api_tip_enabled": "1",
        "api_tip_author": "ucmao",
        "api_tip_website": "https://github.com/ucmao/media-parser",
        "api_tip_notice": "本接口由开源项目 media-parser 提供服务",
    }
    db.executemany(
        "INSERT OR IGNORE INTO system_settings(key, value) VALUES (?, ?)",
        defaults.items(),
    )
    db.commit()


def reserve_user_credit(user_id):
    """原子预扣一次积分；True 表示已扣，False 表示无需扣，None 表示余额不足。"""
    if not user_id:
        return False
    with transaction(immediate=True) as db:
        user = db.execute(
            "SELECT role, credits FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not user:
            return None
        if user["role"] == "admin" or user["credits"] == -1:
            return False
        cursor = db.execute(
            "UPDATE users SET credits=credits-1 WHERE id=? AND credits>0",
            (user_id,),
        )
        return True if cursor.rowcount == 1 else None


def refund_user_credit(user_id):
    """退回一次已预扣的普通用户积分。"""
    if not user_id:
        return
    with transaction(immediate=True) as db:
        db.execute(
            "UPDATE users SET credits=credits+1 "
            "WHERE id=? AND role!='admin' AND credits!=-1",
            (user_id,),
        )



def setting(name, default=None):
    row = get_db().execute(
        "SELECT value FROM system_settings WHERE key = ?", (name,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(name, value):
    get_db().execute(
        "INSERT INTO system_settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (name, str(value)),
    )


@contextmanager
def transaction(immediate=False):
    db = get_db()
    db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()


def get_daily_trend(user_id=None, days=7):
    db = get_db()
    today = datetime.now().date()
    
    # 确定实际天数 (days=0 表示全周期)
    if days == 0:
        sql_min = "SELECT MIN(date(created_at, 'localtime')) as min_date FROM request_logs "
        params_min = []
        if user_id is not None:
            sql_min += "WHERE user_id = ? "
            params_min.append(user_id)
        row_min = db.execute(sql_min, params_min).fetchone()
        if row_min and row_min["min_date"]:
            try:
                min_date = datetime.strptime(row_min["min_date"], "%Y-%m-%d").date()
                total_days = max(7, (today - min_date).days + 1)
            except ValueError:
                total_days = 7
        else:
            total_days = 7
    else:
        total_days = max(1, days)

    sql = (
        "SELECT date(created_at, 'localtime') as day, "
        "COUNT(*) as calls, "
        "SUM(CASE WHEN status_code < 400 THEN 1 ELSE 0 END) as successes "
        "FROM request_logs "
    )
    params = []
    where_clauses = []
    if days > 0:
        where_clauses.append("datetime(created_at) >= datetime('now', ? || ' days', 'localtime')")
        params.append(f"-{total_days}")
    if user_id is not None:
        where_clauses.append("user_id = ?")
        params.append(user_id)

    if where_clauses:
        sql += "WHERE " + " AND ".join(where_clauses) + " "
    sql += "GROUP BY day ORDER BY day ASC"

    rows = db.execute(sql, params).fetchall()
    row_map = {row["day"]: row for row in rows if row["day"]}

    daily_stats = []
    max_val = 0
    for i in range(total_days - 1, -1, -1):
        day_date = today - timedelta(days=i)
        day_str = day_date.strftime("%Y-%m-%d")
        short_date = day_date.strftime("%m-%d")
        item = row_map.get(day_str)
        calls = item["calls"] if item and item["calls"] else 0
        successes = item["successes"] if item and item["successes"] else 0
        if calls > max_val:
            max_val = calls
        daily_stats.append({
            "date": day_str,
            "short_date": short_date,
            "calls": calls,
            "successes": successes,
            "failures": max(0, calls - successes),
        })

    num_points = len(daily_stats)
    # 计算 X 轴文字抽样频率
    if num_points <= 10:
        step = 1
    elif num_points <= 31:
        step = 5
    elif num_points <= 90:
        step = 15
    elif num_points <= 180:
        step = 30
    else:
        step = 60

    for idx, item in enumerate(daily_stats):
        item["show_label"] = (idx % step == 0) or (idx == num_points - 1)

    y_max = max_val if max_val > 0 else 10
    if y_max < 5:
        y_max = 5

    width = 620
    height = 160
    left_margin = 50
    top_margin = 20
    bottom_y = top_margin + height

    points_calls = []
    points_successes = []

    for i, item in enumerate(daily_stats):
        x = round(left_margin + i * (width / max(1, num_points - 1)), 1)
        y_c = round(top_margin + height * (1 - item["calls"] / y_max), 1)
        y_s = round(top_margin + height * (1 - item["successes"] / y_max), 1)
        item["x"] = x
        item["y_calls"] = y_c
        item["y_successes"] = y_s
        points_calls.append(f"{x},{y_c}")
        points_successes.append(f"{x},{y_s}")

    calls_line = " ".join(points_calls)
    successes_line = " ".join(points_successes)

    first_x = daily_stats[0]["x"]
    last_x = daily_stats[-1]["x"]
    calls_area = f"{first_x},{bottom_y} {calls_line} {last_x},{bottom_y}"
    successes_area = f"{first_x},{bottom_y} {successes_line} {last_x},{bottom_y}"

    return {
        "trend": daily_stats,
        "max_val": max_val,
        "y_max": y_max,
        "calls_line": calls_line,
        "successes_line": successes_line,
        "calls_area": calls_area,
        "successes_area": successes_area,
        "y_ticks": [
            {"val": y_max, "y": top_margin},
            {"val": round(y_max / 2), "y": top_margin + height / 2},
            {"val": 0, "y": bottom_y},
        ],
    }


def get_platform_distribution(user_id=None, days=7):
    db = get_db()
    sql = (
        "SELECT COALESCE(NULLIF(platform, ''), '未知平台') as platform_name, "
        "COUNT(*) as calls, "
        "SUM(CASE WHEN status_code < 400 THEN 1 ELSE 0 END) as successes "
        "FROM request_logs "
    )
    params = []
    where_clauses = []
    if days > 0:
        where_clauses.append("datetime(created_at) >= datetime('now', ? || ' days', 'localtime')")
        params.append(f"-{days}")
    if user_id is not None:
        where_clauses.append("user_id = ?")
        params.append(user_id)

    if where_clauses:
        sql += "WHERE " + " AND ".join(where_clauses) + " "
    sql += "GROUP BY platform_name ORDER BY calls DESC"

    rows = db.execute(sql, params).fetchall()
    total_calls = sum(r["calls"] for r in rows) if rows else 0

    PALETTE = [
        "#4f46e5", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6",
        "#06b6d4", "#ef4444", "#3b82f6", "#14b8a6", "#f97316",
        "#64748b", "#84cc16", "#d946ef", "#6366f1"
    ]

    items = []
    if total_calls > 0:
        cx, cy = 100, 100
        r_out, r_in = 80, 50
        current_angle = 0.0  # radians

        for idx, row in enumerate(rows):
            name = row["platform_name"]
            calls = row["calls"]
            successes = row["successes"] or 0
            percentage = round((calls / total_calls) * 100, 1)
            color = PALETTE[idx % len(PALETTE)]

            slice_angle = (calls / total_calls) * 2 * math.pi
            # 防止刚好 360 度圆环闭合异常
            if slice_angle >= 2 * math.pi - 1e-4:
                slice_angle = 2 * math.pi - 1e-4

            start_angle = current_angle
            end_angle = current_angle + slice_angle
            current_angle = end_angle

            x1_out = cx + r_out * math.sin(start_angle)
            y1_out = cy - r_out * math.cos(start_angle)
            x2_out = cx + r_out * math.sin(end_angle)
            y2_out = cy - r_out * math.cos(end_angle)

            x2_in = cx + r_in * math.sin(end_angle)
            y2_in = cy - r_in * math.cos(end_angle)
            x1_in = cx + r_in * math.sin(start_angle)
            y1_in = cy - r_in * math.cos(start_angle)

            large_arc = 1 if slice_angle > math.pi else 0

            path_d = (
                f"M {x1_out:.2f} {y1_out:.2f} "
                f"A {r_out} {r_out} 0 {large_arc} 1 {x2_out:.2f} {y2_out:.2f} "
                f"L {x2_in:.2f} {y2_in:.2f} "
                f"A {r_in} {r_in} 0 {large_arc} 0 {x1_in:.2f} {y1_in:.2f} Z"
            )

            items.append({
                "platform": name,
                "calls": calls,
                "successes": successes,
                "percentage": percentage,
                "color": color,
                "path_d": path_d,
            })

    return {
        "total_calls": total_calls,
        "items": items,
    }


def get_top_users(days=7, limit=10):
    db = get_db()
    sql = (
        "SELECT u.username, COUNT(l.id) as calls "
        "FROM request_logs l "
        "JOIN users u ON u.id = l.user_id "
    )
    params = []
    if days > 0:
        sql += "WHERE datetime(l.created_at) >= datetime('now', ? || ' days', 'localtime') "
        params.append(f"-{days}")
    sql += "GROUP BY u.id ORDER BY calls DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(sql, params).fetchall()
    max_calls = max((r["calls"] for r in rows), default=1)
    return [
        {
            "username": r["username"],
            "calls": r["calls"],
            "pct": round((r["calls"] / max_calls) * 100, 1),
        }
        for r in rows
    ]


def get_top_keys(user_id, days=7, limit=10):
    db = get_db()
    sql = (
        "SELECT k.name, k.key_prefix, COUNT(l.id) as calls "
        "FROM request_logs l "
        "JOIN api_keys k ON k.id = l.api_key_id "
        "WHERE l.user_id = ? "
    )
    params = [user_id]
    if days > 0:
        sql += "AND datetime(l.created_at) >= datetime('now', ? || ' days', 'localtime') "
        params.append(f"-{days}")
    sql += "GROUP BY k.id ORDER BY calls DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(sql, params).fetchall()
    max_calls = max((r["calls"] for r in rows), default=1)
    return [
        {
            "name": r["name"],
            "key_prefix": r["key_prefix"],
            "calls": r["calls"],
            "pct": round((r["calls"] / max_calls) * 100, 1),
        }
        for r in rows
    ]
