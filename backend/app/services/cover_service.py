"""
cover_service.py - 封面复刻提示词服务

字幕生成后, 基于字幕内容提炼封面三要素(标题/界面显示文字/账号领域),
再把用户确认后的三要素填入"AI 封面复刻助手"模板, 生成可直接复制使用的完整提示词。
"""

import json
import re

from google.genai import types

from app.services.gemini_service import get_client

# 文本/视觉模型(按优先级, 失败自动降级)
TEXT_MODELS = ["gemini-3-flash-preview", "gemini-3.1-flash-lite"]


def _parse_json_text(text: str) -> dict:
    """从模型输出中提取 JSON 对象(容错)"""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("模型输出中未找到 JSON 对象")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError("JSON 未闭合")


def _gen_json(client, prompt: str) -> dict:
    """调文本模型, 强制 JSON 输出(模型失败自动降级)"""
    last_err = None
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(
                model=model, contents=[prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json"))
            return _parse_json_text(resp.text)
        except Exception as e:
            last_err = e
            print(f"[封面] 文本模型 {model} 失败: {e}")
    raise RuntimeError(f"所有文本模型都失败了: {last_err}")


def analyze_cover_fields(client, transcript: str) -> dict:
    """基于转写文本提炼封面三要素: 标题 / 界面显示文字(封面大字) / 账号领域"""
    prompt = f"""你是B站视频封面策划专家。根据视频转写内容, 提炼封面所需的三个要素。

视频转写内容(节选):
{transcript[:6000]}

请先思考三个问题(思考过程不要输出, 只输出最终 JSON):
1. 这个视频讲什么？
2. 用户痛点是什么？
3. 封面应该突出什么？

然后只输出下面的 JSON, 不要输出任何其他内容:
{{
  "title": "视频标题(简洁有力, 30字以内)",
  "cover_text": "界面显示文字(封面大字, 整个封面唯一允许出现的文字! 必须8字以内, 字越少越好(2-5字最佳), 从视频中提炼最准确、最尖锐、最能让人想点进来的一个短句, 如 '不用Bitly' '字幕不再翻车' '告别会员' '免费白嫖')",
  "category": "账号领域(2-6字, 如: 网站相关/科技科普/工具教程)"
}}"""
    return _gen_json(client, prompt)


# AI 封面复刻助手模板(用户确认的固定模板, 三要素填入其中)
COVER_PROMPT_TEMPLATE = """你是一个 AI 封面复刻助手。

你的任务不是直接照搬参考图，而是先拆解参考封面的视觉结构，再根据用户的新标题和素材，生成一版新的封面方案。

工作流程：

第一步：确认用户输入的信息是否完整。
需要用户提供：
1. 参考封面图
2. 新封面标题
3. 账号领域
4. 画面比例
5. 是否有人像或素材
6. 参考程度：轻度参考/深度参考

第二步：拆解参考封面。
请分析：
1. 画面比例
2. 标题位置
3. 标题层级
4. 人物/主体位置
5. 背景氛围
6. 颜色搭配
7. 字体气质
8. 视觉重点

第三步：迁移到用户的新内容。
请判断：
1. 新标题适合如何分行
2. 哪些关键词需要突出
3. 人物/素材应该放在哪里
4. 背景和颜色如何调整
5. 哪些地方只参考，不照搬

第四步：输出封面生成提示词。
提示词需要包含：
1. 构图
2. 标题排版
3. 人物/主体
4. 背景
5. 色彩
6. 字体风格
7. 画面氛围
8. 禁止事项

第五步：给出优化建议。
如果生成效果不好，请按顺序检查：
1. 标题是否清楚
2. 构图是否接近参考逻辑
3. 人物是否突出
4. 颜色是否统一
5. 元素是否太多

——————————————————————————————————————————————————————


按要求生成Youtube高点击率的视频封面图。封面禁止出现标题文字。
标题：{TITLE}
界面显示文字：{COVER_TEXT}
账号领域：{CATEGORY}
画面比例：16：9 
是否有人像：否
参考程度：高度参考"""


def fill_cover_prompt(title: str, cover_text: str, category: str) -> str:
    """把确认后的三要素填入模板, 返回完整复刻提示词"""
    return COVER_PROMPT_TEMPLATE.replace("{TITLE}", title or "").replace(
        "{COVER_TEXT}", cover_text or "").replace("{CATEGORY}", category or "")
