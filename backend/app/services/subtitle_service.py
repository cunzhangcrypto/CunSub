import re

# 单条字幕舒适目标长度(不含空格)。超过 TARGET_LEN 就尽量按语义边界拆短,
# 因为一行 18 字一口气读不完, 中文每行 11~12 字左右才适合阅读。
TARGET_LEN = 12

# 单条字幕绝对硬上限(不含空格)。超过它必切(兜底拆分), 但优先找语义边界。
MAX_CHARS = 18

# 标点停顿: 在这些标点后优先断行(顿号/逗号/句号/分号/冒号/问号/叹号)
_PUNCT_BREAKS = "，,。；;：:、！!？?"

# 关联词/话题词: 在这些词之前断行, 避免长句被硬切成无语义碎块。
# 除关联词外, 还包含「这次/这个/下面/我们/他们」这类常开新话题与小句的词,
# 例如 "它会让我们选择这次可乐宣传片要什么画幅" 应在 "这次" 前拆成自然两句。
_BREAK_BEFORE = ("然后", "接着", "所以", "因为", "但是", "而且", "顺便", "同时",
                 "比如", "例如", "包括", "另外", "还有", "以及", "总之", "其实",
                 "甚至", "虽然", "不过", "也就是",
                 "这次", "下次", "这个", "那个", "下面", "接下来",
                 "我们", "他们", "她们", "你们",
                 "关于", "对于", "通过", "针对", "借助", "围绕")

# 语气词/助词: 在这些字之后断行
_PARTICLE_AFTER = "的呢了啊吧吗呀哦着"

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


def split_by_pauses(text: str) -> list[str]:
    """把一条字幕的文本拆成多段, 每段不超过 MAX_CHARS 且语义顺畅。
    断行优先级: 标点停顿 > 双空格停顿 > 语义安全拆分(不拆英文单词)。
    """
    # 1. 标点停顿: 在主要标点后断行(标点留在前一段末尾, 稍后清理)
    parts = re.split(r'(?<=[%s])' % _PUNCT_BREAKS, text)
    result = []
    for part in parts:
        # 2. 双空格(语义停顿标记)处必断行
        sub_parts = re.split(r'  +', part)
        for sp in sub_parts:
            sp = sp.strip()
            if not sp:
                continue
            # 3. 超过 MAX_CHARS 的段做语义安全拆分
            if count_chars(sp) <= MAX_CHARS:
                result.append(sp)
            else:
                result.extend(_smart_split(sp))
    return result


def _is_semantic(text: str, i: int) -> bool:
    """切点 i 是否落在『语义边界』上(逗号早已剥掉, 此处针对长句中剩余的可断点)。
    语义边界 = 空格 / 语气助词后 / 关联话题词前。"""
    if i < 1 or i >= len(text):
        return False
    if text[i] == " ":
        return True
    if text[i - 1] in _PARTICLE_AFTER:
        return True
    for w in _BREAK_BEFORE:
        if text.startswith(w, i):
            return True
    return False


def _smart_split(text: str) -> list[str]:
    """把一段字幕文本拆成多行。

    两阶段:
      阶段A(必切): 超过硬上限 MAX_CHARS 时必须切平——_find_cut 会优先语义边界、
                    绝不劈英文单词、避开悬空残尾。
      阶段B(按需): 超过舒适目标 TARGET_LEN(12) 但仍在上限内 → 尽量切到 ~12。
                    切点仍由 _find_cut 给出(优先语义边界), 但只有两段都 ≥6 字
                    才真的拆开, 避免出现 "么画幅" 这类过短的悬空残句。
    """
    text = text.strip()
    result = []
    # 阶段A: 超硬上限必切
    while count_chars(text) > MAX_CHARS:
        cut = _find_cut(text)
        seg = text[:cut].strip()
        if not seg:  # 防御: 切点无效时按上限硬切, 避免死循环
            seg = text[:MAX_CHARS]
            text = text[MAX_CHARS:].strip()
        else:
            text = text[cut:].strip()
        result.append(seg)
    # 阶段B: (舒适, 上限] 之间 → 尽量切短, 但两段须都 ≥6 字才拆
    while count_chars(text) > TARGET_LEN:
        cut = _find_cut(text)
        head = text[:cut].strip()
        tail = text[cut:].strip()
        if count_chars(head) >= 6 and count_chars(tail) >= 6:
            result.append(head)
            text = tail
            continue
        break
    if text:
        result.append(text)
    return result


def _find_cut(text: str) -> int:
    """在句子中找最佳切点(首行尽量 ≤ TARGET_LEN, 绝不劈开英文/拉丁单词)。

    两级选择:
      一级(语义边界): 在『首行 ≤ TARGET_LEN+3』的窗口内找语义边界
                       (代词/关联词前、语气助词后、空格), 取最接近 TARGET_LEN 的。
                       首行因语义边界被拖得太长就放弃, 避免 18 字长行。
      二级(均衡切):   没有合格语义边界时, 取最接近 TARGET_LEN 的均衡位置,
                       同时避开悬空残尾。绝不落在英文单词中间。
    """
    n = len(text)
    if n <= 1:
        return n
    limit = min(MAX_CHARS, n - 1)  # 始终给尾巴留 ≥1 字, 保证是真拆分
    target = min(TARGET_LEN, limit)

    def is_latin(c: str) -> bool:
        return bool(c) and c.isascii() and c.isalnum()

    def latin_split(i: int) -> bool:
        return i < n and is_latin(text[i - 1]) and is_latin(text[i])

    # 一级: 语义边界
    sem_best = None
    sem_d = 1e9
    for i in range(3, min(limit, target + 3) + 1):
        if latin_split(i):
            continue
        if n - i < 4:  # 残尾不放做语义切点
            continue
        if _is_semantic(text, i):
            d = abs(i - target)
            if d < sem_d:
                sem_d = d
                sem_best = i
    if sem_best is not None:
        return sem_best

    # 二级: 均衡切 — 优先『紧贴英文/拉丁单词边界』的切点(不撕裂中英文交界),
    #       否则取最接近 target 的均衡位置; 残尾越小越差。
    def latin_edge(i: int) -> bool:
        return i < n and is_latin(text[i - 1]) != is_latin(text[i])

    # 二级a: 目标附近的拉丁单词边界(离 target ≤ 4)
    edge_best = None
    edge_key = (1e9, 1e9)
    for i in range(3, limit + 1):
        if latin_split(i):
            continue
        if abs(i - target) > 4:
            continue
        if not latin_edge(i):
            continue
        tail = n - i
        pen = 0 if tail >= 4 else (4 - tail)
        key = (abs(i - target), pen)
        if key < edge_key:
            edge_key = key
            edge_best = i
    if edge_best is not None:
        return edge_best

    # 二级b: 普通均衡切
    bal_best = None
    bal_key = (1e9, 1e9)
    for i in range(3, limit + 1):
        if latin_split(i):
            continue
        tail = n - i
        pen = 0 if tail >= 4 else (4 - tail)
        key = (abs(i - target), pen)
        if key < bal_key:
            bal_key = key
            bal_best = i
    if bal_best is not None:
        return bal_best
    # 极端兜底: 前 limit 字是同一段超长拉丁连续词, 无安全切点
    return min(limit, max(3, n - 1))


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
    """后处理: 标点清理 + 术语替换 + 按双空格停顿断行。
    不做字数硬拆——保持 Gemini 语义断句与单词完整,
    时间戳按字符比例分配给按停顿拆出的各段。
    """
    if terms_mapping is None:
        terms_mapping = {}

    raw_subs = parse_srt(srt_text)
    processed = []
    idx = 1

    for sub in raw_subs:
        text = sub["text"]
        # 先转简体, 再做术语替换, 然后按标点/停顿拆分, 最后清理标点
        text = to_simplified(text)
        text = apply_terms(text, terms_mapping, term_corrections)
        text = text.strip()

        if not text:
            continue

        segments = split_by_pauses(text)
        segments = [clean_punctuation(s).strip() for s in segments]
        segments = [s for s in segments if s]
        if not segments:
            continue
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
            for i, seg in enumerate(segments):
                if i == len(segments) - 1:
                    seg_end = end_sec  # 最后一段精确对齐原结束时间
                else:
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

    return make_monotonic(processed)
