# ==========================================
# 文件名: gateway.py
# 架构定位: FastAPI 主入口与路由总线
# ==========================================
import logging
from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from routers import user, translation, tutor, record
from routers.user import init_db, verify_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")

app = FastAPI(title="Voice Gateway API")

# 挂载业务路由
app.include_router(user.router)
app.include_router(translation.router)
app.include_router(tutor.router)
app.include_router(record.router)

# 挂载静态资源
app.mount("/resources", StaticFiles(directory="resources"), name="resources")

@app.on_event("startup")
async def root_startup():
    init_db()
    logging.info("✅ Gateway API 骨架与数据库初始化完毕")
    #🎯
    translation.start_translation_workers()
    tutor.start_tutor_workers()
    record.start_record_workers()

@app.get("/")
async def serve_frontend():
    with open("web/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())
    
@app.get("/tutor")
async def serve_tutor_page():
    with open("web/tutor.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())
    
@app.get("/record")
async def serve_tutor_page():
    with open("web/record.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/admin")
async def serve_admin_page(admin_user: str = Depends(verify_admin)):
    with open("web/admin.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())