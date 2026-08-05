import subprocess
import json
import uuid
import shutil
from pathlib import Path
from app.config import AUDIO_DIR

# Gemini 原生支持的音频格式，无需转码
NATIVE_AUDIO_EXTS = ('.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg', '.opus')


def extract_audio(source_path: str):
    """根据源文件类型处理音频：
    - 原生音频格式(MP3/WAV等)：直接复制，不转码（快）
    - 视频文件：ffmpeg 提取音频为 mp3（压缩小，上传快）
    返回 (audio_path, duration_sec)
    文件名用 uuid 生成纯 ASCII，避免 Gemini SDK header 编码失败"""
    source = Path(source_path)
    ext = source.suffix.lower()

    if ext in NATIVE_AUDIO_EXTS:
        # 原生音频：直接复制，保留原格式
        output_name = f"{uuid.uuid4().hex}{ext}"
        output_path = AUDIO_DIR / output_name
        shutil.copy2(source, output_path)
    else:
        # 视频：提取音频并转码为 mp3（压缩，上传快）
        output_name = f"{uuid.uuid4().hex}.mp3"
        output_path = AUDIO_DIR / output_name
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source),
             "-vn", "-ac", "1", "-ar", "44100", "-b:a", "128k",
             str(output_path)],
            capture_output=True
        )

    # 获取时长
    result = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "json", str(output_path)],
        capture_output=True, text=True
    )
    duration = float(json.loads(result.stdout)["format"]["duration"])
    return str(output_path), duration


def get_audio_clip(audio_path: str, start_sec: float, duration_sec: float = 6.0):
    """切片音频用于确认门试听，返回 clip 路径"""
    source = Path(audio_path)
    clip_name = f"clip_{source.stem}_{int(start_sec)}.wav"
    clip_path = AUDIO_DIR / clip_name

    if not clip_path.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source),
             "-ss", str(start_sec), "-t", str(duration_sec),
             str(clip_path)],
            capture_output=True
        )
    return str(clip_path)
