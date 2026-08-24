import json
from datetime import datetime
from fastapi import APIRouter, HTTPException
from app.database import get_db
from app.services import cover_service as cs

router = APIRouter()


def _get_transcript(project_id: str) -> str:
    """从项目字幕拼接转写文本"""
    db = get_db()
    rows = db.execute(
        "SELECT text FROM subtitles WHERE project_id = ? ORDER BY idx", (project_id,)
    ).fetchall()
    db.close()
    return "\n".join(r["text"] for r in rows)


def _load_cached_fields(project_id: str):
    db = get_db()
    row = db.execute(
        "SELECT content FROM cover_prompts WHERE project_id = ?", (project_id,)
    ).fetchone()
    db.close()
    if not row:
        return None
    data = json.loads(row["content"])
    return data.get("fields") if isinstance(data, dict) else None


def _save_cached_fields(project_id: str, fields: dict):
    db = get_db()
    now = datetime.now().isoformat()
    db.execute(
        "INSERT OR REPLACE INTO cover_prompts (project_id, content, created_at) VALUES (?, ?, ?)",
        (project_id, json.dumps({"fields": fields}, ensure_ascii=False), now),
    )
    db.commit()
    db.close()


@router.post("/analyze")
def cover_analyze(payload: dict = None):
    """AI 分析项目字幕, 提炼封面三要素(标题/界面显示文字/账号领域)。
    结果按 project_id 缓存, 供用户修改后填充模板。"""
    payload = payload or {}
    project_id = (payload.get("project_id") or "").strip()
    transcript = (payload.get("transcript") or "").strip() or _get_transcript(project_id)
    if not transcript:
        raise HTTPException(400, "请先生成字幕, 再提炼封面要素")

    cached = _load_cached_fields(project_id) if project_id else None
    if cached:
        return cached

    fields = cs.analyze_cover_fields(cs.get_client(), transcript)
    fields.setdefault("title", "")
    fields.setdefault("cover_text", "")
    fields.setdefault("category", "")
    if project_id:
        _save_cached_fields(project_id, fields)
    return fields


@router.get("/{project_id}/fields")
def get_cover_fields(project_id: str):
    """读取已分析缓存的封面三要素(未分析过返回 null)"""
    return _load_cached_fields(project_id)


@router.post("/{project_id}/prompt")
def build_cover_prompt(project_id: str, payload: dict = None):
    """把用户确认后的三要素填入"AI 封面复刻助手"模板, 返回完整提示词。"""
    payload = payload or {}
    title = (payload.get("title") or "").strip()
    cover_text = (payload.get("cover_text") or "").strip()
    category = (payload.get("category") or "").strip()
    if not (title or cover_text):
        raise HTTPException(400, "请先填写标题或界面显示文字")
    return {"prompt": cs.fill_cover_prompt(title, cover_text, category)}
