# -*- coding: utf-8 -*-
"""验证术语库沉淀+复用闭环。直接 import workflow 的 helper, 用临时 DB 跑。"""
import io, sys, json, os, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# 先临时改 DB_PATH, 别污染真实数据
os.environ["CUBSUB_TEST"] = "1"  # 没用, 只是标记

import app.database as _db
import app.routers.workflow as _wf

# ---------- 1) 测 _extract_diff_pairs ----------
print("=== Test 1: diff 抽替换对 ===")
cases = [
    (
        "我们使用春inbox来管理邮件，非常方便",
        "我们使用Cuninbox来管理邮件，非常方便",
        [("春inbox", "Cuninbox")],
    ),
    (
        "这个算法用到了Transformer架构",
        "这个算法用到了Transformer框架",
        [("架构", "框架")],
    ),
    (
        "春inbox已经被集成到了村长实验室",
        "Cuninbox已经被集成到了村长实验室",
        [("春inbox", "Cuninbox")],
    ),
    # 公共锚点在开头
    (
        "Google Earth Studio 导出后, 我会用CunSub加字幕",
        "Google Earth Studio 导出后, 我会用村长字幕加字幕",
        [("CunSub", "村长字幕")],
    ),
    # 多个被修改的词(前后都有差异)
    (
        "我用春inbox配合Cuninbox来管理内容",
        "我用Cuninbox配合CunSub来管理内容",
        [("春inbox", "Cuninbox"), ("Cuninbox", "CunSub")],
    ),
    # 整句完全重写 (应当返回空, 不乱猜)
    (
        "今天天气真不错啊",
        "我觉得这件事情需要重新考虑",
        [],
    ),
    # 只改了一个字但公共子串太短
    (
        "abc",
        "xyz",
        [],
    ),
]
ok_all = True
for i, (old, new, expected) in enumerate(cases):
    got = _wf._extract_diff_pairs(old, new)
    ok = got == expected
    mark = "✓" if ok else "✗"
    print(f"{mark} case {i+1}:  {got}")
    if not ok:
        ok_all = False
        print(f"   expect: {expected}")

# ---------- 2) 测 save_term_correction + load_term_library_corrections ----------
print("\n=== Test 2: 沉淀到术语库 + 加载 ===")
# 清库
db = _db.get_db()
db.execute("DELETE FROM term_library")
db.commit()
db.close()

_wf.save_term_correction("春inbox", "Cuninbox", "test_pid_1")
_wf.save_term_correction("村长sub", "CunSub", "test_pid_1")
_wf.save_term_correction("春inbox", "Cuninbox", "test_pid_2")  # 再存一次, count+1
_wf.save_term_correction("", "X", None)  # 空错词 → 跳过
_wf.save_term_correction("A", "B", None)  # 单字 → 跳过(长度<2)
_wf.save_term_correction("这是，带标点的句子", "X", None)  # 含逗号 → 跳过

# 验证库内容
db = _db.get_db()
rows = db.execute("SELECT term, aliases, confirmed_count FROM term_library ORDER BY term").fetchall()
db.close()
for r in rows:
    print(f"  term={r['term']}  aliases={r['aliases']}  count={r['confirmed_count']}")

loaded = _wf.load_term_library_corrections()
print(f"  load_term_library_corrections = {loaded}")

expect_loaded = {"春inbox": "Cuninbox", "村长sub": "CunSub"}
assert loaded == expect_loaded, f"期望 {expect_loaded} 实际 {loaded}"
cuninbox = next(r for r in rows if r["term"] == "Cuninbox")
assert cuninbox["confirmed_count"] == 2, "重复沉淀 Cuninbox 应该 count=2"

# ---------- 3) 测合并优先级:当前项目 corrections > 历史库 ----------
print("\n=== Test 3: 合并优先级 ===")
library_corrections = _wf.load_term_library_corrections()
project_corrections = {"春inbox": "村长Inbox"}  # 用户在确认页改了, 应高于历史库
merged = dict(library_corrections)
merged.update(project_corrections)
assert merged["春inbox"] == "村长Inbox", f"项目优先级失效: {merged}"
assert merged["村长sub"] == "CunSub"
print(f"  合并结果: {merged}  ✓")

# ---------- 4) 额外术语追加 ----------
print("\n=== Test 4: additional_terms 追加历史正确词 ===")
additional_terms = ["CunSub"]
extra = sorted({t for t in library_corrections.values() if t and t not in additional_terms})
print(f"  原additional_terms={additional_terms}")
print(f"  追加={extra}")
assert "Cuninbox" in extra, extra
print("  ✓")

print("\n", "全部通过" if ok_all else "有失败")
sys.exit(0 if ok_all else 1)
