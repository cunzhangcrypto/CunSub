from pydantic import BaseModel
from typing import Optional


class ProjectCreate(BaseModel):
    name: Optional[str] = None


class ConfirmRequest(BaseModel):
    terms_mapping: dict
    additional_terms: list[str] = []
    term_corrections: dict = {}  # 已识别术语的修正：{原错误写法: 正确写法}


class SubtitleEdit(BaseModel):
    text: str


class ExportRequest(BaseModel):
    format: str  # srt / vtt / ass
