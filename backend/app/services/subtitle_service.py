import re

MAX_CHARS = 18

# SRT 时间戳正则: 兼容 HH:MM:SS,mmm 和 MM:SS,mmm 两种格式
# Gemini 长输出时可能省略小时,例如 01:03,187 --> 01:05,077
_TIME_RE = re.compile(
    r'(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})'
    r'\s*-->\s*'
    r'(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})'
)


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
    """
    srt_text = srt_text.strip()
    # 去除可能的 markdown 包裹
    if srt_text.startswith("```"):
        srt_text = re.sub(r'^```[a-z]*\n', '', srt_text)
        srt_text = re.sub(r'\n```$', '', srt_text)

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
        # 去掉首尾空行、序号行、空行
        lines = [ln.strip() for ln in raw_text.split('\n') if ln.strip()]
        # 过滤掉纯数字行(下一块的序号)和空行
        text_lines = [ln for ln in lines if not ln.isdigit()]
        text = ' '.join(text_lines).strip()
        if text:
            subtitles.append({
                "start_time": start_time,
                "end_time": end_time,
                "text": text
            })
    return subtitles


def clean_punctuation(text: str) -> str:
    """删除非?!标点"""
    # 中文标点
    text = re.sub(r'[，。、；：""''（）【】《》…—·]+', '', text)
    # 英文标点(保留?!)
    text = re.sub(r'[,.:;\'"()\[\]<>\\/-]+', '', text)
    return text


def count_chars(text: str) -> int:
    """统计字符数(不含空格)"""
    return len(text.replace(" ", ""))


def apply_terms(text: str, terms_mapping: dict, term_corrections: dict = None) -> str:
    """术语词典替换校验"""
    for original, correct in terms_mapping.items():
        if original and correct:
            text = text.replace(original, correct)
    for original, correct in (term_corrections or {}).items():
        if original and correct and original != correct:
            text = text.replace(original, correct)
    return text


def split_by_pauses(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """把一条字幕的文本按停顿拆成多段(对齐 test.srt 标准)。
    1. 双空格(旧版停顿标记)处必断行;
    2. 单空格是英文词间距,保留;
    3. 每段超过 max_chars 再智能断句。
    """
    parts = re.split(r'  +', text)  # 双空格及以上的停顿处拆开
    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if count_chars(part) <= max_chars:
            result.append(part)
        else:
            result.extend(_smart_split(part, max_chars))
    return result


def _smart_split(text: str, max_chars: int) -> list[str]:
    """智能断句:把无停顿的超长段切成多段。
    优先级:英文单词边界 > 语气词后 > 平均分配(避免拆出孤字)。
    """
    result = []
    while count_chars(text) > max_chars:
        cut = _find_cut(text, max_chars)
        result.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        result.append(text)
    return result


def _find_cut(text: str, max_chars: int) -> int:
    """在超长段内找最佳切点"""
    # 1. 英文空格边界
    window = text[:max_chars + 3]
    last_space = window.rfind(" ")
    if 0 < last_space <= max_chars:
        return last_space
    # 2. 语气词/助词后切(呢啊吧吗呀哦的了着)
    particles = "呢啊吧吗呀哦的着了"
    for i in range(min(max_chars, len(text)) - 1, 0, -1):
        if text[i] in particles:
            return i + 1
    # 3. 平均分配兜底:避免切出孤字(如 18+1)
    tail = count_chars(text) - max_chars
    if tail < max_chars // 3:
        # 尾部太短,往前挪,让尾部至少 max_chars//2 字
        return max(max_chars // 2, count_chars(text) - max_chars // 2)
    return max_chars


def _time_to_seconds(t: str) -> float:
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _seconds_to_time(sec: float) -> str:
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        sec += 1
        ms = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def post_process(srt_text: str, terms_mapping: dict = None, term_corrections: dict = None) -> list[dict]:
    """后处理：标点清理 + 术语替换 + 按双空格断行。
    每条字幕按双空格(停顿标记)拆分成独立字幕行,超过 18 字的段智能断句,
    时间戳按字符比例分配给各段。
    """
    if terms_mapping is None:
        terms_mapping = {}

    raw_subs = parse_srt(srt_text)
    processed = []
    idx = 1

    for sub in raw_subs:
        text = sub["text"]
        text = clean_punctuation(text)
        text = apply_terms(text, terms_mapping, term_corrections)
        text = text.strip()

        if not text:
            continue

        segments = split_by_pauses(text)
        if len(segments) == 1:
            processed.append({
                "idx": idx,
                "start_time": sub["start_time"],
                "end_time": sub["end_time"],
                "text": segments[0]
            })
            idx += 1
        else:
            # 按字符比例把 [start, end] 分配给各段
            total_chars = sum(count_chars(s) for s in segments)
            start_sec = _time_to_seconds(sub["start_time"])
            end_sec = _time_to_seconds(sub["end_time"])
            duration = end_sec - start_sec
            cursor = start_sec
            for seg in segments:
                seg_chars = count_chars(seg)
                seg_dur = duration * seg_chars / total_chars if total_chars else duration / len(segments)
                seg_end = cursor + seg_dur
                processed.append({
                    "idx": idx,
                    "start_time": _seconds_to_time(cursor),
                    "end_time": _seconds_to_time(seg_end),
                    "text": seg
                })
                idx += 1
                cursor = seg_end

    return processed
