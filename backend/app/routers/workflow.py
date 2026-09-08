import json
import threading
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.database import get_db
from app.models import ConfirmRequest, SubtitleEdit
from app.services.gemini_service import understand, generate
from app.services.subtitle_service import (
    post_process, apply_offset, finalize_subtitles, last_covered_seconds,
    _time_to_seconds, _seconds_to_time, transcribe_audio, reanchor_to_audio,
)
from app.services.audio_service import get_audio_clip
from app.services.progress_service import set_progress, simulate_progress

router = APIRouter()

# 截断检测与断点续传: Gemini 对长音频偶发输出到一半就停(尾部字幕缺失),
# 生成后对比"字幕覆盖到哪"与"音频总长", 差太多则自动从断点继续生成。
TRUNCATION_THRESHOLD_SEC = 20.0   # 音频尾部超过 20s 无字幕视为被截断
MIN_RESUME_GAP_SEC = 5.0          # 剩余不足 5s 不值得续传
MAX_CONTINUE_ROUNDS = 5           # 最多续传轮数, 防止异常时死循环
CONTINUE_OVERLAP_SEC = 2.0        # 续传起点回退 2s, 保证衔接处不断字


def load_term_library_corrections() -> dict:
    """从 term_library 表加载所有历史别名修正: {错词: 正确词}.
    每次生成时一起传给 Gemini + post_process 兜底替换, 实现术语库越用越准。
    """
    db = get_db()
    rows = db.execute("SELECT term, aliases FROM term_library").fetchall()
    db.close()
    out = {}
    for r in rows:
        try:
            aliases = json.loads(r["aliases"] or "[]")
        except Exception:
            continue
        correct = r["term"]
        for wrong in aliases:
            if wrong and wrong != correct:
                # 当前项目的 term_corrections 优先级高于历史库, 不覆盖
                out.setdefault(wrong, correct)
    return out


def save_term_correction(wrong: str, correct: str, source_project_id: str | None = None):
    """沉淀单条词修正(错词→正确词)到 term_library。已存在则 count+1、补充别名。"""
    if not wrong or not correct or wrong == correct:
        return
    # 只沉淀长度看起来像"词"的: 2~30 个字, 不包含句子里的标点符号
    if len(wrong) < 2 or len(correct) < 2 or len(wrong) > 30 or len(correct) > 30:
        return
    # 跳过整句级别的修改(含逗号、句号、问号等)——避免把整句误当词
    for ch in wrong + correct:
        if ch in "，。！？、；：,.!?;: \t\n":
            return
    db = get_db()
    try:
        existing = db.execute("SELECT * FROM term_library WHERE term = ?", (correct,)).fetchone()
        if existing:
            aliases = json.loads(existing["aliases"] or "[]")
            if wrong not in aliases:
                aliases.append(wrong)
            db.execute(
                "UPDATE term_library SET aliases = ?, confirmed_count = ? WHERE term = ?",
                (json.dumps(aliases, ensure_ascii=False), (existing["confirmed_count"] or 0) + 1, correct),
            )
        else:
            db.execute(
                "INSERT INTO term_library (term, aliases, source_project_id, confirmed_count) VALUES (?, ?, ?, 1)",
                (correct, json.dumps([wrong], ensure_ascii=False), source_project_id),
            )
        db.commit()
    finally:
        db.close()


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

    # 合并术语库中的历史修正(实现越用越准)。
    # 当前项目 term_corrections 优先级高于历史库(setdefault 不覆盖),
    # 所以用户在确认页做的临时修正可以覆盖老结论。
    library_corrections = load_term_library_corrections()
    merged_corrections = dict(library_corrections)
    merged_corrections.update(term_corrections)

    # 额外术语去重:把术语库里的正确词也追加到 additional_terms 里传给 Gemini
    extra_library_terms = sorted({
        t for t in library_corrections.values() if t and t not in additional_terms
    })
    merged_additional = list(additional_terms) + extra_library_terms

    now = datetime.now().isoformat()
    db = get_db()
    db.execute("UPDATE projects SET status = 'generating', updated_at = ? WHERE id = ?", (now, project_id))
    db.commit()
    db.close()

    # Gemini 阶段2调用(首轮)
    try:
        srt_text = generate(project["gemini_file_name"], terms_mapping, merged_corrections, merged_additional)
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

    # 后处理 + 截断检测与断点续传
    audio_duration = float(project["source_duration"] or 0)
    all_subs = list(post_process(srt_text, terms_mapping, merged_corrections))
    rounds = 1
    while (audio_duration > 0
           and audio_duration - last_covered_seconds(all_subs) > TRUNCATION_THRESHOLD_SEC
           and rounds < MAX_CONTINUE_ROUNDS):
        resume_sec = last_covered_seconds(all_subs) - CONTINUE_OVERLAP_SEC
        if resume_sec < 0 or audio_duration - resume_sec < MIN_RESUME_GAP_SEC:
            break
        resume_time = _seconds_to_time(max(0.0, resume_sec))
        try:
            srt_tail = generate(project["gemini_file_name"], terms_mapping, merged_corrections,
                                merged_additional, continue_from=resume_time)
        except Exception:
            # 续传失败时保留已生成的字幕, 不中断整个流程
            import traceback
            traceback.print_exc()
            break
        tail_subs = post_process(srt_tail, terms_mapping, merged_corrections)
        # 只保留从断点之后开始的新字幕(过滤 Gemini 可能的重复输出)
        new_subs = [s for s in tail_subs if _time_to_seconds(s["start_time"]) >= resume_sec]
        if not new_subs:
            break  # 剩余无可转录内容(如纯音乐结尾), 停止续传
        all_subs.extend(new_subs)
        rounds += 1

    subtitles = finalize_subtitles(all_subs)

    # 用本地 whisper 对语音做真实对齐, 覆盖 Gemini 的不可靠时间戳:
    # 文字仍是 Gemini 的, 时间轴对齐到真实语音。失败则保留 Gemini 时间。
    audio_path = dict(project).get("audio_path")
    if audio_path:
        segs = transcribe_audio(audio_path)
        if segs:
            subtitles = reanchor_to_audio(subtitles, segs)

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

    return {"count": len(subtitles), "rounds": rounds, "continued": rounds > 1}


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


def _extract_diff_pairs(old: str, new: str) -> list[tuple[str, str]]:
    """比较 old/new 两条字幕文本, 找出一对一的替换词对。
    分层过滤:
      1) 先按标点分句, 只有分句数量一致才继续, 保证结构相同(避免整句重写的误沉淀)
      2) 对对应分句跑 difflib, 把 replace 区附近做一个有限窗口的扩张(不跨全句吞)
      3) trim 掉共同前后缀 → 剩下的差异如果是 2-30 字的无标点片段 → 作为词对
      4) trim 后太短 → 回退到扩张窗口的相似度兜底(高度相似则整窗口一对)
      5) 任何环节涉及标点 / 差异占分句比例过高(>60%) → 跳过
    """
    if not old or not new or old == new:
        return []

    import difflib, re as _re

    PUNCT_STR = r"[，。！？、；：,.!?;:]"
    PUNCT_SET = set("，。！？、；：,.!?;: \t\n")

    def _split_clauses(s: str) -> list[str]:
        # 按标点分句, 保留标点作为分隔边界; 去掉空块
        parts = _re.split(PUNCT_STR, s)
        return [p.strip() for p in parts if p.strip()]

    def _lcsub(s1, s2) -> int:
        nn, mm = len(s1), len(s2)
        best = 0
        dp = [[0] * (mm + 1) for _ in range(nn + 1)]
        for x in range(1, nn + 1):
            for y in range(1, mm + 1):
                if s1[x - 1] == s2[y - 1]:
                    v = dp[x - 1][y - 1] + 1
                    dp[x][y] = v
                    if v > best:
                        best = v
                else:
                    dp[x][y] = 0
        return best

    def _lcsub_pair_info(s1, s2):
        """返回 (最长公共连续子串长度, 相似度=长度/max(len))"""
        nn, mm = len(s1), len(s2)
        if nn == 0 or mm == 0:
            return 0, 0.0
        best = _lcsub(s1, s2)
        return best, best / max(nn, mm)

    def _trim_common(a: str, b: str) -> tuple[str, str]:
        """枚举所有可能的前缀/后缀 trim 步数, 选出最优词对:
           优先级: 1) 最长公共连续子串长度(绝对值越大越好)  2) 相似度比例(越接近1越好)
           约束: 两边长度 ≥ 2, 不含标点
        """
        na, nb = len(a), len(b)
        max_pre = 0
        for i in range(min(na, nb) + 1):
            if i < min(na, nb) and a[i] == b[i]:
                if na - (i + 1) >= 2 and nb - (i + 1) >= 2:
                    max_pre = i + 1
                else:
                    break
            else:
                break
        best_pair = (a, b)
        best_lcsub, best_ratio = _lcsub_pair_info(a, b)
        for pre in range(max_pre + 1):
            a2, b2 = a[pre:], b[pre:]
            na2, nb2 = len(a2), len(b2)
            max_suf = 0
            for j in range(min(na2, nb2) + 1):
                if j < min(na2, nb2) and a2[na2 - 1 - j] == b2[nb2 - 1 - j]:
                    if na2 - (j + 1) >= 2 and nb2 - (j + 1) >= 2:
                        max_suf = j + 1
                    else:
                        break
                else:
                    break
            for suf in range(max_suf + 1):
                a3 = a2 if suf == 0 else a2[: na2 - suf]
                b3 = b2 if suf == 0 else b2[: nb2 - suf]
                if len(a3) < 2 or len(b3) < 2:
                    continue
                if any(ch in a3 + b3 for ch in PUNCT_SET):
                    continue
                lc, ratio = _lcsub_pair_info(a3, b3)
                if (lc > best_lcsub) or (lc == best_lcsub and ratio > best_ratio):
                    best_lcsub = lc
                    best_ratio = ratio
                    best_pair = (a3, b3)
        return best_pair

    def _ok_term(s: str) -> bool:
        if not s or not (2 <= len(s) <= 30):
            return False
        return not any(ch in s for ch in PUNCT_SET)

    def _expand_to_token(s: str, lo: int, hi: int) -> tuple[int, int]:
        """基于「字符类」做 token 扩张:
        字符类: C = CJK, A = ASCII alnum, O = 其他(标点/空白 → 硬边界)
        只扩张与 [lo,hi) 内相同字符类的字符, 碰到 C↔A 转换或 O(边界) 就停。
        这样不会把「配合Cuninbox」中的 "配合"(CJK) 和 "Cuninbox"(ASCII) 吞成一个 token;
        同时也不会把 "春inbox"(CJK+ASCII 两边都在 change 内) 拆太散 — 这种情况留给 MARGIN 兜底。
        """
        n = len(s)
        if lo >= hi:
            return lo, hi
        def ccl(c):
            if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf' or (
                    '\uf900' <= c <= '\ufaff'):
                return 'C'  # CJK 统一汉字
            if c.isascii() and c.isalnum():
                return 'A'  # ASCII 字母/数字
            return 'O'  # 其他 → 视为边界
        classes = [ccl(c) for c in s]
        # 先吞掉所有 O(标点/空白) 在 change 两端(防御性)
        while lo < hi and classes[lo] == 'O':
            lo += 1
        while lo < hi and classes[hi-1] == 'O':
            hi -= 1
        if lo >= hi:
            return lo, hi
        orig_classes = set(classes[lo:hi])
        if 'O' in orig_classes:
            orig_classes.discard('O')
        # 扩张: 只允许和 orig_classes 相同类的字符, 碰到 C↔A 转换或 O 就停
        while lo > 0 and classes[lo-1] != 'O' and classes[lo-1] in orig_classes:
            lo -= 1
        while hi < n and classes[hi] != 'O' and classes[hi] in orig_classes:
            hi += 1
        return lo, hi

    old_clauses = _split_clauses(old)
    new_clauses = _split_clauses(new)
    if len(old_clauses) != len(new_clauses):
        return []  # 分句数量不同 → 不是简单词替换, 放弃

    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []
    for c_old, c_new in zip(old_clauses, new_clauses):
        if c_old == c_new:
            continue
        sm = difflib.SequenceMatcher(None, c_old, c_new, autojunk=False)
        # --- 把 change 段(opcode != equal)合并成「一个 change 组」---
        # 注意: 单字相等(内部 equal, len==1)不打断, 比如 difflib 把 架构→框架 拆成
        # insert "框" + equal "架" + delete "构", 我们要把它当成一组替换,
        # 否则会生成两个 change 组 → 产生重复/错误的词对。
        groups: list[tuple[int, int, int, int]] = []  # (i1, i2, j1, j2)
        cur_lo = cur_hi = cur_jo = cur_jh = -1
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                eq_len_old, eq_len_new = i2 - i1, j2 - j1
                # 两边相等长度都 <=1 → 视为内部断点, 不结束当前 change 组, 把 equal 区段吞进 change range
                if cur_lo >= 0 and eq_len_old <= 1 and eq_len_new <= 1:
                    cur_hi, cur_jh = max(cur_hi, i2), max(cur_jh, j2)
                    continue
                if cur_lo >= 0:
                    groups.append((cur_lo, cur_hi, cur_jo, cur_jh))
                    cur_lo = -1
                continue
            if cur_lo < 0:
                cur_lo, cur_hi, cur_jo, cur_jh = i1, i2, j1, j2
            else:
                cur_hi, cur_jh = max(cur_hi, i2), max(cur_jh, j2)
        if cur_lo >= 0:
            groups.append((cur_lo, cur_hi, cur_jo, cur_jh))

        for i1, i2, j1, j2 in groups:
            # 差异占分句比例过高 → 多半是整句改写, 跳过
            ratio = max(i2 - i1, j2 - j1) / max(len(c_old), len(c_new), 1)
            if ratio > 0.6:
                continue

            # 1) 优先: 不扩张的 raw change 组本身就是合规的词对?
            #    这是最强信号, 直接捕获 Case 2「架构→框架」和 Case 4「CunSub→村长字幕」
            #    但要排除「difflib 把大词的共同前后缀 trim 掉后留下的残缺 stem」场景:
            #    典型 Case 5 第二组: difflib 把 "Cuninbox→CunSub" 拆成 equal("Cun") + change("inbox→Sub")
            #    此时 raw = ("inbox", "Sub") 虽满足 ok_term, 但两边 change 起点都贴 ASCII alnum
            #    → 其实是更大 token 的片段, 不接受 raw, 留到 token expansion 阶段补全。
            core_old = c_old[i1:i2]
            core_new = c_new[j1:j2]
            if core_old != core_new and _ok_term(core_old) and _ok_term(core_new):
                _pure_ascii_alnum = lambda s: s.isascii() and s.isalnum()
                left_touches_word = (
                    _pure_ascii_alnum(core_old) and _pure_ascii_alnum(core_new)
                    and i1 > 0 and j1 > 0
                    and c_old[i1-1].isascii() and c_old[i1-1].isalnum()
                    and c_new[j1-1].isascii() and c_new[j1-1].isalnum()
                )
                right_touches_word = (
                    _pure_ascii_alnum(core_old) and _pure_ascii_alnum(core_new)
                    and i2 < len(c_old) and j2 < len(c_new)
                    and c_old[i2].isascii() and c_old[i2].isalnum()
                    and c_new[j2].isascii() and c_new[j2].isalnum()
                )
                if not (left_touches_word or right_touches_word):
                    cand_a, cand_b = _trim_common(core_old, core_new)
                    if not (_ok_term(cand_a) and _ok_term(cand_b)):
                        cand_a, cand_b = core_old, core_new
                    if (cand_a, cand_b) not in seen:
                        seen.add((cand_a, cand_b))
                        pairs.append((cand_a, cand_b))
                    continue

            # 2) 次优: 扩张 change 组到 token 边界
            #    捕获 difflib 把共同前后缀 trim 掉后导致的「半残缺 token」:
            #    如 Case 5 第二组 (inbox → Sub) 实际对应 (Cuninbox → CunSub), 通过扩张补全前缀
            #    扩张后 >12 字多半是中文无分词边界造成的误吞, 放弃走 fallback
            #    额外: 扩张后的词对必须至少有 ≥1 字符的公共连续子串,
            #    否则像 Case 1 (旧 token "我们使用春" CJK vs 新 token "Cuninbox" ASCII)
            #    完全没共同点 → 是无效词对, 拒绝 token 结果, 回退到 MARGIN 窗口。
            ti1, ti2 = _expand_to_token(c_old, i1, i2)
            tj1, tj2 = _expand_to_token(c_new, j1, j2)
            core_old = c_old[ti1:ti2]
            core_new = c_new[tj1:tj2]
            if (core_old != core_new
                    and _ok_term(core_old) and _ok_term(core_new)
                    and max(len(core_old), len(core_new)) <= 12):
                cand_a, cand_b = _trim_common(core_old, core_new)
                if not (_ok_term(cand_a) and _ok_term(cand_b)):
                    cand_a, cand_b = core_old, core_new
                # 词对必须有一定相似性(至少 1 个公共连续子串字符)
                if _lcsub(cand_a, cand_b) >= 1:
                    if (cand_a, cand_b) not in seen:
                        seen.add((cand_a, cand_b))
                        pairs.append((cand_a, cand_b))
                    continue

            # fallback: change 组 + MARGIN 窗口的兜底抽取(主要用于长句中非 token 化的大段上下文修正)
            MARGIN = 5
            w_lo = max(0, i1 - MARGIN)
            w_hi = min(len(c_old), i2 + MARGIN)
            x_lo = max(0, j1 - MARGIN)
            x_hi = min(len(c_new), j2 + MARGIN)
            win_old = c_old[w_lo:w_hi]
            win_new = c_new[x_lo:x_hi]
            if win_old == win_new:
                continue

            a, b = _trim_common(win_old, win_new)
            if _ok_term(a) and _ok_term(b):
                if (a, b) not in seen:
                    seen.add((a, b))
                    pairs.append((a, b))
                continue

            denom = max(len(win_old), len(win_new), 1)
            if max(len(win_old), len(win_new)) <= 14:
                sim = _lcsub(win_old, win_new) / denom
                if sim >= 0.4 and _ok_term(win_old) and _ok_term(win_new):
                    cand = (win_old, win_new)
                    if cand not in seen:
                        seen.add(cand)
                        pairs.append(cand)
    return pairs


@router.put("/{project_id}/subtitles/{idx}")
def edit_subtitle(project_id: str, idx: int, req: SubtitleEdit):
    db = get_db()
    # 先拿原字幕的原文(用户还没改之前的), 用于后续 diff 出修正对
    row = db.execute(
        "SELECT text FROM subtitles WHERE project_id = ? AND idx = ?",
        (project_id, idx),
    ).fetchone()
    old_text = row["text"] if row else ""

    db.execute(
        "UPDATE subtitles SET text = ?, edited = 1 WHERE project_id = ? AND idx = ?",
        (req.text, project_id, idx),
    )
    db.commit()
    db.close()

    # diff 原句/新句, 抽出词级修正对 → 沉淀到术语库
    if old_text and old_text != req.text:
        for wrong, correct in _extract_diff_pairs(old_text, req.text):
            save_term_correction(wrong, correct, source_project_id=project_id)

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
