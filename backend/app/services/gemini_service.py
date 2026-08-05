import json
import time
from google import genai
from google.genai import types
from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.prompts import PROMPT_UNDERSTANDING, PROMPT_GENERATION

_client = None


def get_client():
    """创建 Gemini 客户端。
    设置 600s 长超时:生成字幕需处理整个音频,耗时可到 2-3 分钟,默认超时会断开。
    """
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=600_000),  # 10 分钟,毫秒
        )
    return _client


def upload_file(file_path: str):
    """上传文件到 Gemini File API，返回 (file_name, file_uri)"""
    c = get_client()
    f = c.files.upload(file=file_path)
    while f.state == "PROCESSING":
        time.sleep(2)
        f = c.files.get(name=f.name)
    if f.state == "FAILED":
        raise Exception("Gemini 文件处理失败")
    return f.name, f.uri


def understand(file_name: str) -> dict:
    """阶段1：理解音频，返回结构化 JSON。带重试机制。"""
    c = get_client()
    f = c.files.get(name=file_name)
    last_err = None
    for attempt in range(1, 4):
        try:
            response = c.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=[PROMPT_UNDERSTANDING, f],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                )
            )
            text = "".join(chunk.text for chunk in response if chunk.text)
            return json.loads(text)
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()
            retryable = any(k in err_msg for k in [
                'disconnected', 'timeout', 'timed out',
                '503', '502', '500', '429', 'rate limit',
                'connection', 'reset', 'unavailable'
            ])
            if not retryable or attempt == 3:
                raise
            time.sleep(3 * attempt)
    raise last_err


def generate(file_name: str, terms_mapping: dict, term_corrections: dict = None, additional_terms: list = None) -> str:
    """阶段2：基于音频+确认术语生成 SRT 字幕。
    带重试机制:Gemini API 偶发 Server disconnected,自动重试最多 3 次。
    """
    c = get_client()
    f = c.files.get(name=file_name)
    prompt = PROMPT_GENERATION.replace(
        "{TERMS_MAPPING}",
        json.dumps(terms_mapping, ensure_ascii=False, indent=2)
    ).replace(
        "{TERM_CORRECTIONS}",
        json.dumps(term_corrections or {}, ensure_ascii=False, indent=2)
    ).replace(
        "{ADDITIONAL_TERMS}",
        json.dumps(additional_terms or [], ensure_ascii=False, indent=2)
    )

    last_err = None
    for attempt in range(1, 4):
        try:
            # 流式输出:长任务连接持续活跃,避免服务端超时断连
            response = c.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=[prompt, f],
                config=types.GenerateContentConfig(
                    temperature=0.2,  # 低温度保证格式稳定
                )
            )
            return "".join(chunk.text for chunk in response if chunk.text)
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()
            # 可重试的错误:连接断开、超时、服务端错误、429
            retryable = any(k in err_msg for k in [
                'disconnected', 'timeout', 'timed out',
                '503', '502', '500', '429', 'rate limit',
                'connection', 'reset', 'unavailable'
            ])
            if not retryable or attempt == 3:
                raise
            time.sleep(3 * attempt)  # 退避:3s, 6s
    raise last_err
