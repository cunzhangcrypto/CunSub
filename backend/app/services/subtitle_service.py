import re

# SRT 时间戳正则: 兼容 HH:MM:SS,mmm 和 MM:SS,mmm 两种格式
# Gemini 长输出时可能省略小时,例如 01:03,187 --> 01:05,077
_TIME_RE = re.compile(
    r'(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})'
    r'\s*-->\s*'
    r'(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})'
)

# Gemini 偶发把时间戳输出成空格分隔格式: 00 00 02 029 --> 00 00 04 399
# (时 分 秒 毫秒 各为一组, 用空格分隔, 原 _TIME_RE 匹配不到会被当成字幕文本)
_SPACE_TIME_RE = re.compile(
    r'(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,3})\s*-->\s*'
    r'(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,3})'
)

# 时间戳垃圾行: 由 数字/空格/冒号/点/逗号/箭头/连字符/括号 组成的行(如 "00 00 02 029 --> 00 00 04 399")
_TIMESTAMP_JUNK_RE = re.compile(r'^[\d\s:.,，;；\-—>→()（）\[\]]+$')


def _normalize_timestamps(srt_text: str) -> str:
    """把 Gemini 输出的空格分隔时间戳(00 00 02 029 --> 00 00 04 399)
    规范化为标准格式(00:00:02,029 --> 00:00:04,399),
    使其能被 _TIME_RE 识别为真正的时间边界, 避免被当成字幕文本。
    """

    def _fmt(m):
        h, mi, s = (int(m.group(i)) for i in range(1, 4))
        h2, mi2, s2 = (int(m.group(i)) for i in range(5, 8))
        return (f"{h:02d}:{mi:02d}:{s:02d},{m.group(4).zfill(3)}"
                f" --> "
                f"{h2:02d}:{mi2:02d}:{s2:02d},{m.group(8).zfill(3)}")

    return _SPACE_TIME_RE.sub(_fmt, srt_text)


def _normalize_time(t: str) -> str:
    """标准化时间戳为 HH:MM:SS,mmm 格式。
    MM:SS,mmm 格式省略了小时,补 00。
    """
    t = t.strip().replace('.', ',')
    if ',' in t:
        main, ms = t.split(',', 1)
        ms = ms[:3].ljust(3, '0')
    else:
        main, ms = t, '000'
    parts = main.split(':')
    if len(parts) == 2:  # MM:SS -> HH:MM:SS
        parts = ['00'] + parts
    h, m, s = [int(p) for p in parts]
    return f"{h:02d}:{m:02d}:{s:02d},{ms}"


def parse_srt(srt_text: str) -> list[dict]:
    """健壮解析 SRT 文本为字幕列表。
    用正则匹配时间戳行,不依赖固定的空行分隔,避免 Gemini 输出格式波动丢数据。
    兼容 Gemini 偶发的空格分隔时间戳,并过滤时间戳垃圾行。
    """
    srt_text = srt_text.strip()
    # 去除可能的 markdown 包裹
    if srt_text.startswith("```"):
        srt_text = re.sub(r'^```[a-z]*\n', '', srt_text)
        srt_text = re.sub(r'\n```$', '', srt_text)

    # 空格分隔时间戳(00 00 02 029 --> 00 00 04 399)规范化为标准格式
    srt_text = _normalize_timestamps(srt_text)

    # 找出所有时间戳行的位置
    matches = list(_TIME_RE.finditer(srt_text))
    subtitles = []
    for i, m in enumerate(matches):
        start_time = _normalize_time(m.group(1))
        end_time = _normalize_time(m.group(2))
        # 文本在当前时间戳行之后,到下一个时间戳或块分隔之前
        text_start = m.end()
        text_end = matches[i + 1].start() if i + 1 < len(matches) else len(srt_text)
        raw_text = srt_text[text_start:text_end]
        # 去掉首尾空行、序号行、空行、时间戳垃圾行
        lines = [ln.strip() for ln in raw_text.split('\n') if ln.strip()]
        text_lines = [
            ln for ln in lines
            if not ln.isdigit() and not _TIMESTAMP_JUNK_RE.match(ln)
        ]
        text = ' '.join(text_lines).strip()
        if text:
            subtitles.append({
                "start_time": start_time,
                "end_time": end_time,
                "text": text
            })
    return subtitles


def clean_punctuation(text: str) -> str:
    """删除非?!标点, 但保留数字中的小数点(如 2.5pro、3.14、v1.2)"""
    # 中文标点
    text = re.sub(r'[，。、；：""''（）【】《》…—·]+', '', text)
    # 英文标点(保留?!): 逗号/冒号/分号/引号/括号/尖括号/斜杠/连字符
    text = re.sub(r'[,:;"()\[\]<>\\/-]+', '', text)
    # 英文句点: 只删除非小数点的句点(数字之间的点保留)
    text = re.sub(r'(?<!\d)\.(?!\d)', '', text)
    return text


def apply_offset(time_str: str, offset_ms: int) -> str:
    """给时间戳加偏移(毫秒)。offset_ms 为正=字幕整体推迟, 负=提前。
    结果不小于 0。"""
    if not offset_ms:
        return time_str
    ms_total = int(round(_time_to_seconds(time_str) * 1000)) + offset_ms
    ms_total = max(0, ms_total)
    h, ms_total = divmod(ms_total, 3600000)
    m, ms_total = divmod(ms_total, 60000)
    s, ms = divmod(ms_total, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


_converter = None


def to_simplified(text: str) -> str:
    """繁体转简体(基于 opencc t2s)。失败时原样返回, 不影响主流程。"""
    global _converter
    try:
        if _converter is None:
            from opencc import OpenCC
            _converter = OpenCC("t2s")
        return _converter.convert(text)
    except Exception:
        return text


def apply_terms(text: str, terms_mapping: dict, term_corrections: dict = None) -> str:
    """术语词典替换校验"""
    for original, correct in terms_mapping.items():
        if original and correct:
            text = text.replace(original, correct)
    for original, correct in (term_corrections or {}).items():
        if original and correct and original != correct:
            text = text.replace(original, correct)
    return text


def _time_to_seconds(t: str) -> float:
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _seconds_to_time(sec: float) -> str:
    """秒转时间戳, 用整数毫秒运算避免浮点进位误差(如 7.9999s+1 进位成 9s)。"""
    ms_total = int(round(sec * 1000))
    h, ms_total = divmod(ms_total, 3600000)
    m, ms_total = divmod(ms_total, 60000)
    s, ms = divmod(ms_total, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def last_covered_seconds(subtitles: list[dict]) -> float:
    """所有字幕覆盖到的最晚时间(秒)。用于判断生成是否被截断(尾部缺失)。"""
    return max((_time_to_seconds(s["end_time"]) for s in subtitles), default=0.0)


def finalize_subtitles(subtitles: list[dict]) -> list[dict]:
    """多轮(首轮+续传轮)字幕合并后的统一处理:
    按起始时间排序 -> 重排 idx -> 时间单调化(消除续传衔接处的时间重叠)。
    """
    ordered = sorted(subtitles, key=lambda s: _time_to_seconds(s["start_time"]))
    for i, s in enumerate(ordered, 1):
        s["idx"] = i
    return make_monotonic(ordered)


def make_monotonic(subtitles: list[dict]) -> list[dict]:
    """修正字幕时间重叠: 保证下一条的起始时间不早于上一条的结束时间。
    原因: Gemini 偶发输出相邻时间戳重叠(甚至乱序), 剪映会把重叠字幕叠加显示成多排。
    保持字幕顺序与文本不变, 只顺延时间; 时长不足 0.5s 的字幕补足到 0.5s。"""
    last_end = 0.0
    for sub in subtitles:
        start = _time_to_seconds(sub["start_time"])
        end = _time_to_seconds(sub["end_time"])
        if start < last_end:
            start = last_end
        if end <= start:
            end = start + 0.5
        sub["start_time"] = _seconds_to_time(start)
        sub["end_time"] = _seconds_to_time(end)
        last_end = end
    return subtitles


def post_process(srt_text: str, terms_mapping: dict = None, term_corrections: dict = None) -> list[dict]:
    """后处理: 简体转换 + 术语替换 + 标点清理。

    信任 Gemini 每行自带的时间戳——不再对单个字幕做按字符比例的伪拆分,
    因为语音不是均匀分布的, 伪时间戳会让文字出现的时刻与实际说话时刻脱节。
    因此只做文本清洗, 时间轴原样保留(每条字幕 = Gemini 的一行)。
    """
    if terms_mapping is None:
        terms_mapping = {}

    raw_subs = parse_srt(srt_text)
    processed = []
    for sub in raw_subs:
        text = to_simplified(sub["text"])
        text = apply_terms(text, terms_mapping, term_corrections)
        text = clean_punctuation(text).strip()
        if not text:
            continue
        processed.append({
            "idx": len(processed) + 1,
            "start_time": sub["start_time"],
            "end_time": sub["end_time"],
            "text": text
        })
    return make_monotonic(processed)
