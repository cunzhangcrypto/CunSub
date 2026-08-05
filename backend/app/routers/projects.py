import uuid
import threading
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from app.database import get_db
from app.config import AUDIO_DIR
from app.services.audio_service import extract_audio, NATIVE_AUDIO_EXTS
from app.services.gemini_service import upload_file
from app.services.progress_service import set_progress, get_progress, simulate_progress

router = APIRouter()

VIDEO_EXTS = ('.mp4', '.mov', '.mkv', '.avi', '.flv', '.webm')


@router.get("")
def list_projects():
    db = get_db()
    rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]


@router.post("/upload")
async def upload_only(file: UploadFile = File(...), name: str = Form(None)):
    """Step 1: 仅接收文件并落盘"""
    project_id = str(uuid.uuid4())
    original_name = file.filename
    project_name = name or Path(original_name).stem

    source_path = AUDIO_DIR / f"{project_id}_{original_name}"
    content = await file.read()
    with open(source_path, "wb") as f:
        f.write(content)

    file_type = "video" if original_name.lower().endswith(VIDEO_EXTS) else "audio"
    now = datetime.now().isoformat()

    db = get_db()
    db.execute(
        """INSERT INTO projects
        (id, name, status, source_file_path, source_file_type, source_size, created_at, updated_at)
        VALUES (?, ?, 'uploaded', ?, ?, ?, ?, ?)""",
        (project_id, project_name, str(source_path), file_type, len(content), now, now)
    )
    db.commit()
    db.close()

    set_progress(project_id, "uploading", 100, "文件已接收")
    return {"id": project_id, "name": project_name, "size": len(content)}


@router.post("/{project_id}/extract")
def extract(project_id: str):
    """Step 2: 提取音频(MP3 等原生格式直接复制,视频才 ffmpeg 转码)"""
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        db.close()
        raise HTTPException(404, "项目不存在")

    source_ext = Path(project["source_file_path"]).suffix.lower()
    is_native = source_ext in NATIVE_AUDIO_EXTS

    now = datetime.now().isoformat()
    db.execute("UPDATE projects SET status = 'extracting', updated_at = ? WHERE id = ?", (now, project_id))
    db.commit()
    db.close()

    if is_native:
        set_progress(project_id, "extracting", 100, "原生音频格式,跳过转码")
    else:
        stop = threading.Event()
        t = threading.Thread(target=simulate_progress, args=(project_id, "extracting", stop, 95))
        t.start()
        try:
            audio_path, duration = extract_audio(project["source_file_path"])
        finally:
            stop.set()
            t.join()
        set_progress(project_id, "extracting", 100, "音频提取完成")

    if is_native:
        audio_path, duration = extract_audio(project["source_file_path"])

    now = datetime.now().isoformat()
    db = get_db()
    db.execute("UPDATE projects SET audio_path = ?, source_duration = ?, status = 'extracted', updated_at = ? WHERE id = ?",
               (audio_path, duration, now, project_id))
    db.commit()
    db.close()

    return {"duration": duration}


@router.post("/{project_id}/upload-gemini")
def upload_to_gemini(project_id: str):
    """Step 3: 上传音频到 Gemini File API"""
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        db.close()
        raise HTTPException(404, "项目不存在")

    now = datetime.now().isoformat()
    db.execute("UPDATE projects SET status = 'uploading_gemini', updated_at = ? WHERE id = ?", (now, project_id))
    db.commit()
    db.close()

    # 后台模拟进度(Gemini SDK 不暴露真实上传进度)
    stop = threading.Event()
    t = threading.Thread(target=simulate_progress, args=(project_id, "uploading_gemini", stop, 95))
    t.start()
    try:
        file_name, file_uri = upload_file(project["audio_path"])
    except Exception as e:
        stop.set()
        t.join()
        from app.config import check_gemini_reachable
        ok, msg = check_gemini_reachable()
        if not ok:
            raise HTTPException(502, msg)
        raise HTTPException(502, f"上传 Gemini 失败: {type(e).__name__}: {e}")
    finally:
        stop.set()
        t.join()
    set_progress(project_id, "uploading_gemini", 100, "上传完成")

    now = datetime.now().isoformat()
    db = get_db()
    db.execute("UPDATE projects SET gemini_file_uri = ?, gemini_file_name = ?, status = 'uploaded', updated_at = ? WHERE id = ?",
               (file_uri, file_name, now, project_id))
    db.commit()
    db.close()

    return {"file_name": file_name}


@router.get("/{project_id}/progress")
def progress_stream(project_id: str):
    """SSE 端点:实时推送进度"""
    import time
    def event_stream():
        last_percent = -1
        while True:
            p = get_progress(project_id)
            if p["percent"] != last_percent:
                last_percent = p["percent"]
                yield f"data: {__import__('json').dumps(p, ensure_ascii=False)}\n\n"
            if p["percent"] >= 100 and p["step"] in ("uploading", "extracting", "uploading_gemini", "understanding"):
                # 完成后多推一次让前端收尾,然后退出
                yield f"data: {__import__('json').dumps(p, ensure_ascii=False)}\n\n"
                break
            time.sleep(0.3)
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{project_id}")
def get_project(project_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(404, "项目不存在")
    return dict(row)


@router.delete("/{project_id}")
def delete_project(project_id: str):
    db = get_db()
    for table in ["subtitles", "confirmations", "understandings", "exports", "projects"]:
        db.execute(f"DELETE FROM {table} WHERE project_id = ? OR id = ?", (project_id, project_id))
    db.commit()
    db.close()
    return {"ok": True}
