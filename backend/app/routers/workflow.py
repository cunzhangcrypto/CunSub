import json
import threading
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.database import get_db
from app.models import ConfirmRequest, SubtitleEdit
from app.services.gemini_service import understand, generate
from app.services.subtitle_service import post_process, apply_offset
from app.services.audio_service import get_audio_clip
from app.services.progress_service import set_progress, simulate_progress

router = APIRouter()


@router.post("/{project_id}/understand")
def start_understanding(project_id: str):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        db.close()
        raise HTTPException(404, "项目不存在")

    now = datetime.now().isoformat()
    db.execute("UPDATE projects SET status = 'understanding', updated_at = ? WHERE id = ?", (now, project_id))
    db.commit()
    db.close()

    # 后台模拟进度
    stop = threading.Event()
    t = threading.Thread(target=simulate_progress, args=(project_id, "understanding", stop, 95))
    t.start()
    try:
        result = understand(project["gemini_file_name"])
    finally:
        stop.set()
        t.join()
    set_progress(project_id, "understanding", 100, "理解完成")

    now = datetime.now().isoformat()
    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO understandings
        (project_id, content_summary, key_points, technical_terms, suspected_errors, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (project_id, result.get("content_summary", ""),
         json.dumps(result.get("key_points", []), ensure_ascii=False),
         json.dumps(result.get("technical_terms", []), ensure_ascii=False),
         json.dumps(result.get("suspected_errors", []), ensure_ascii=False),
         now)
    )
    db.execute("UPDATE projects SET status = 'awaiting_confirmation', updated_at = ? WHERE id = ?", (now, project_id))
    db.commit()
    db.close()

    return result


@router.get("/{project_id}/understanding")
def get_understanding(project_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM understandings WHERE project_id = ?", (project_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(404, "理解结果不存在")
    return {
        "content_summary": row["content_summary"],
        "key_points": json.loads(row["key_points"]),
        "technical_terms": json.loads(row["technical_terms"]),
        "suspected_errors": json.loads(row["suspected_errors"])
    }


@router.post("/{project_id}/confirm")
def confirm(project_id: str, req: ConfirmRequest):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        db.close()
        raise HTTPException(404, "项目不存在")

    now = datetime.now().isoformat()
    db.execute(
        """INSERT OR REPLACE INTO confirmations
        (project_id, status, terms_mapping, additional_terms, term_corrections, confirmed_at)
        VALUES (?, 'confirmed', ?, ?, ?, ?)""",
        (project_id,
         json.dumps(req.terms_mapping, ensure_ascii=False),
         json.dumps(req.additional_terms, ensure_ascii=False),
         json.dumps(req.term_corrections, ensure_ascii=False),
         now)
    )
    db.execute("UPDATE projects SET status = 'confirmed', updated_at = ? WHERE id = ?", (now, project_id))

    # 沉淀疑似错误词修正到术语库
    for original, correct in req.terms_mapping.items():
        existing = db.execute("SELECT * FROM term_library WHERE term = ?", (correct,)).fetchone()
        if existing:
            aliases = json.loads(existing["aliases"] or "[]")
            if original not in aliases:
                aliases.append(original)
            db.execute("UPDATE term_library SET aliases = ?, confirmed_count = ? WHERE term = ?",
                       (json.dumps(aliases, ensure_ascii=False), existing["confirmed_count"] + 1, correct))
        else:
            db.execute(
                "INSERT INTO term_library (term, aliases, source_project_id, confirmed_count) VALUES (?, ?, ?, 1)",
                (correct, json.dumps([original], ensure_ascii=False), project_id)
            )

    # 沉淀已识别术语的修正到术语库
    for original, correct in (req.term_corrections or {}).items():
        if not correct or original == correct:
            continue  # 没改动
        existing = db.execute("SELECT * FROM term_library WHERE term = ?", (correct,)).fetchone()
        if existing:
            aliases = json.loads(existing["aliases"] or "[]")
            if original not in aliases:
                aliases.append(original)
            db.execute("UPDATE term_library SET aliases = ?, confirmed_count = ? WHERE term = ?",
                       (json.dumps(aliases, ensure_ascii=False), existing["confirmed_count"] + 1, correct))
        else:
            db.execute(
                "INSERT INTO term_library (term, aliases, source_project_id, confirmed_count) VALUES (?, ?, ?, 1)",
                (correct, json.dumps([original], ensure_ascii=False), project_id)
            )

    db.commit()
    db.close()
    return {"ok": True, "status": "confirmed"}


@router.get("/{project_id}/confirmation")
def get_confirmation(project_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM confirmations WHERE project_id = ?", (project_id,)).fetchone()
    db.close()
    if not row:
        return {"status": "pending", "terms_mapping": {}, "additional_terms": []}
    return {
        "status": row["status"],
        "terms_mapping": json.loads(row["terms_mapping"] or "{}"),
        "additional_terms": json.loads(row["additional_terms"] or "[]"),
        "term_corrections": json.loads(row["term_corrections"] or "{}")
    }


@router.post("/{project_id}/generate")
def start_generation(project_id: str):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        db.close()
        raise HTTPException(404, "项目不存在")

    confirmation = db.execute("SELECT * FROM confirmations WHERE project_id = ?", (project_id,)).fetchone()
    if not confirmation or confirmation["status"] != "confirmed":
        db.close()
        raise HTTPException(400, "未确认，禁止生成字幕")
    # 允许 generating 状态重试(上次生成失败卡住的情况)

    terms_mapping = json.loads(confirmation["terms_mapping"])
    additional_terms = json.loads(confirmation["additional_terms"] or "[]")
    term_corrections = json.loads(confirmation["term_corrections"] or "{}")
    db.close()

    now = datetime.now().isoformat()
    db = get_db()
    db.execute("UPDATE projects SET status = 'generating', updated_at = ? WHERE id = ?", (now, project_id))
    db.commit()
    db.close()

    # Gemini 阶段2调用
    try:
        srt_text = generate(project["gemini_file_name"], terms_mapping, term_corrections, additional_terms)
    except Exception as e:
        # 生成失败，回滚状态
        now = datetime.now().isoformat()
        db = get_db()
        db.execute("UPDATE projects SET status = 'confirmed', updated_at = ? WHERE id = ?", (now, project_id))
        db.commit()
        db.close()
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Gemini 生成失败: {str(e)}")

    # 后处理
    subtitles = post_process(srt_text, terms_mapping, term_corrections)

    now = datetime.now().isoformat()
    db = get_db()
    db.execute("DELETE FROM subtitles WHERE project_id = ?", (project_id,))
    for sub in subtitles:
        db.execute(
            "INSERT INTO subtitles (project_id, idx, start_time, end_time, text, edited) VALUES (?, ?, ?, ?, ?, 0)",
            (project_id, sub["idx"], sub["start_time"], sub["end_time"], sub["text"])
        )
    db.execute("UPDATE projects SET status = 'generated', updated_at = ? WHERE id = ?", (now, project_id))
    db.commit()
    db.close()

    return {"count": len(subtitles)}


@router.get("/{project_id}/subtitles")
def get_subtitles(project_id: str):
    db = get_db()
    rows = db.execute("SELECT * FROM subtitles WHERE project_id = ? ORDER BY idx", (project_id,)).fetchall()
    project = db.execute("SELECT offset_ms FROM projects WHERE id = ?", (project_id,)).fetchone()
    offset_ms = (project["offset_ms"] if project else 0) or 0
    db.close()
    result = []
    for r in rows:
        d = dict(r)
        d["start_time"] = apply_offset(d["start_time"], offset_ms)
        d["end_time"] = apply_offset(d["end_time"], offset_ms)
        result.append(d)
    return {"offset_ms": offset_ms, "subtitles": result}


@router.post("/{project_id}/offset")
def set_offset(project_id: str, offset_ms: int = 0):
    """调整字幕整体偏移(毫秒)。正=推迟(字幕偏早时用), 负=提前。"""
    db = get_db()
    project = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        db.close()
        raise HTTPException(404, "项目不存在")
    db.execute("UPDATE projects SET offset_ms = ? WHERE id = ?", (offset_ms, project_id))
    db.commit()
    db.close()
    return {"ok": True, "offset_ms": offset_ms}


@router.put("/{project_id}/subtitles/{idx}")
def edit_subtitle(project_id: str, idx: int, req: SubtitleEdit):
    db = get_db()
    db.execute(
        "UPDATE subtitles SET text = ?, edited = 1 WHERE project_id = ? AND idx = ?",
        (req.text, project_id, idx)
    )
    db.commit()
    db.close()
    return {"ok": True}


@router.get("/{project_id}/audio-clip")
def audio_clip(project_id: str, start: float = 0):
    db = get_db()
    project = db.execute("SELECT audio_path FROM projects WHERE id = ?", (project_id,)).fetchone()
    db.close()
    if not project:
        raise HTTPException(404, "项目不存在")
    clip_path = get_audio_clip(project["audio_path"], start)
    return FileResponse(clip_path, media_type="audio/wav")
