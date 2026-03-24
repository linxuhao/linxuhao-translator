# ==========================================
# 文件名: routers/user.py
# 架构定位: 用户状态、鉴权与数据库操作域
# ==========================================
import sqlite3
from fastapi import APIRouter, Header, Depends, HTTPException, Form

router = APIRouter()

DB_PATH = "gateway.db"
ADMIN_EMAIL = "linxuhao84@gmail.com" # 建议在生产环境中通过 os.getenv("ADMIN_EMAIL") 获取

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                username TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                role TEXT DEFAULT 'user'
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
    
    # 仅作为新用户首次插入时的默认初始身份
    initial_role = 'admin' if username == ADMIN_EMAIL else 'user'
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO access_logs (username, request_count, last_active, role)
            VALUES (?, 1, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(username) DO UPDATE SET 
                request_count = request_count + 1,
                last_active = CURRENT_TIMESTAMP
                -- 🎯 致命 Bug 修复：已彻底删除了 role = excluded.role
                -- 活跃度更新将绝对不再触碰、污染或覆盖由 Admin 面板设定的 VIP 身份
        """, (username, initial_role))
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
    # 🎯 契约保持：这里主要为前端 UI (如 adminTab) 提供渲染凭证
    # 增设 is_admin 布尔值，方便前端未来做更清晰的判断
    is_admin = (cf_user == ADMIN_EMAIL)
    return {
        "email": cf_user, 
        "role": 'admin' if is_admin else 'user',
        "is_admin": is_admin
    }

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