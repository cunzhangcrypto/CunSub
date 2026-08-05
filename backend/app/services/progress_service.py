import json
import time
import threading
from datetime import datetime
from app.database import get_db


def set_progress(project_id: str, step: str, percent: int, message: str = ""):
    """设置/更新某项目的进度"""
    now = datetime.now().isoformat()
    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO progress (project_id, step, percent, message, updated_at)
        VALUES (?, ?, ?, ?, ?)""",
        (project_id, step, percent, message, now)
    )
    db.commit()
    db.close()


def get_progress(project_id: str):
    """读取某项目当前进度"""
    db = get_db()
    row = db.execute("SELECT * FROM progress WHERE project_id = ?", (project_id,)).fetchone()
    db.close()
    if not row:
        return {"step": "", "percent": 0, "message": ""}
    return {"step": row["step"], "percent": row["percent"], "message": row["message"]}


def simulate_progress(project_id: str, step: str, stop_event: threading.Event, max_percent: int = 90):
    """在后台线程模拟进度推进(因为 Gemini SDK 不暴露真实进度)
    推进到 max_percent 就停,等真实操作完成后由调用方跳到 100%"""
    messages = {
        "extracting": "提取音频中",
        "uploading_gemini": "上传到 Gemini",
        "understanding": "AI 理解音频内容",
        "generating": "AI 生成字幕",
    }
    msg = messages.get(step, step)
    percent = 5
    while not stop_event.is_set() and percent < max_percent:
        set_progress(project_id, step, percent, msg)
        time.sleep(0.5)
        # 越接近 max_percent 增长越慢(模拟真实感)
        remaining = max_percent - percent
        increment = max(1, int(remaining * 0.08))
        percent = min(max_percent, percent + increment)
