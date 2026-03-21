# ==========================================
# 文件名: routers/user.py
# 架构定位: 用户状态、鉴权与数据库操作域
# ==========================================
import sqlite3
from fastapi import APIRouter, Header, Depends, HTTPException, Form

router = APIRouter()

DB_PATH = "gateway.db"
ADMIN_EMAIL = "linxuhao84@gmail.com"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                username TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE access_logs ADD COLUMN role TEXT DEFAULT 'user'")
        except sqlite3.OperationalError:
            pass
        conn.commit()

def record_usage(username: str):
    if not username:
        username = "anonymous" 
    role = 'admin' if username == ADMIN_EMAIL else 'user'
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO access_logs (username, request_count, last_active, role)
            VALUES (?, 1, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(username) DO UPDATE SET 
                request_count = request_count + 1,
                last_active = CURRENT_TIMESTAMP,
                role = excluded.role
        """, (username, role))
        conn.commit()

def get_user_priority(cf_user: str) -> int:
    role = 'user'
    if cf_user == ADMIN_EMAIL:
        role = 'admin'
    else:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT role FROM access_logs WHERE username = ?", (cf_user or "anonymous",)).fetchone()
            if row: role = row[0]
    return 1 if role in ['admin', 'vip'] else 2

def verify_admin(cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")):
    if cf_user != ADMIN_EMAIL: raise HTTPException(status_code=403, detail="Forbidden")
    return cf_user

@router.get("/api/me")
async def get_my_profile(cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")):
    return {"email": cf_user, "role": 'admin' if cf_user == ADMIN_EMAIL else 'user'}

@router.get("/api/admin/users")
async def get_users_list(admin_user: str = Depends(verify_admin)):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM access_logs ORDER BY role ASC, last_active DESC").fetchall()
        return [dict(r) for r in rows]

@router.post("/api/admin/set_vip")
async def set_user_vip(username: str = Form(...), is_vip: str = Form(...), admin_user: str = Depends(verify_admin)):
    target_role = 'vip' if is_vip.lower() == 'true' else 'user'
    if username == ADMIN_EMAIL: target_role = 'admin'
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE access_logs SET role = ? WHERE username = ?", (target_role, username))
        conn.commit()
    return {"status": "ok"}