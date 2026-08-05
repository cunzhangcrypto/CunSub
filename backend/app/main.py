from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import projects, workflow, export
from app.database import init_db
from app.config import check_gemini_reachable, GEMINI_PROXY, BRANDING, BRANDING_SECRET

app = FastAPI(title="CunSub")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(workflow.router, prefix="/workflow", tags=["workflow"])
app.include_router(export.router, prefix="/export", tags=["export"])


@app.get("/")
def root():
    return {"name": "CunSub", "version": "1.0", "by": "村长实验室"}


@app.get("/branding")
def branding():
    """下发版权/品牌信息(带签名)。
    前端渲染版权栏时从本接口读取,校验签名通过才显示。
    他人只改前端代码无法抹掉版权——重新启动后版权信息仍由后端下发。
    """
    import hashlib
    import hmac
    import json

    # 签名 payload 用 sort_keys,且返回的 data 也必须是同一排序后的 dict,
    # 否则前端 JSON.stringify(data) 的键顺序与签名时的 payload 不一致,校验失败
    payload = json.dumps(BRANDING, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(
        BRANDING_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return {"data": json.loads(payload), "signature": sig}


@app.get("/health/gemini")
def health_gemini():
    """检测 Gemini API 连通性,供前端上传前预检"""
    ok, msg = check_gemini_reachable()
    return {"ok": ok, "message": msg, "proxy": GEMINI_PROXY}


@app.get("/api/term-library")
def term_library():
    from app.database import get_db
    import json
    db = get_db()
    rows = db.execute("SELECT * FROM term_library ORDER BY confirmed_count DESC").fetchall()
    db.close()
    return [{
        "term": r["term"],
        "aliases": json.loads(r["aliases"] or "[]"),
        "confirmed_count": r["confirmed_count"],
        "domain": r["domain"]
    } for r in rows]


init_db()
