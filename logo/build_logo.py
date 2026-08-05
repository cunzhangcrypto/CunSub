# -*- coding: utf-8 -*-
"""CunSub Logo 生成脚本 — 村长实验室
输出: cunsub-logo-icon.png (纯图标) + cunsub-logo.png (图标+文字组合版)
风格: 深色科技风, C 字母环 + 音频波形, 青色→紫色渐变
"""
import math
from PIL import Image, ImageDraw, ImageFont

CYAN = (34, 211, 238)
PURPLE = (168, 85, 247)
WHITE = (255, 255, 255)
GRAY = (148, 163, 184)

FONT_DIR = r"C:\Windows\Fonts"


def lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def gradient_arc(draw, cx, cy, R, W, a_start, a_end, n=280):
    """分段绘制渐变描边的圆弧(青色→紫色)。a 为数学角度(度), y 向下。"""
    step = (a_end - a_start) / n
    for i in range(n):
        a1 = math.radians(a_start + i * step)
        a2 = math.radians(a_start + (i + 1) * step)
        t = i / n
        p1 = (cx + R * math.cos(a1), cy + R * math.sin(a1))
        p2 = (cx + R * math.cos(a2), cy + R * math.sin(a2))
        draw.line([p1, p2], fill=lerp(CYAN, PURPLE, t), width=W, joint="curve")


def load_font(name, size):
    try:
        return ImageFont.truetype(FONT_DIR + "\\" + name, size)
    except OSError:
        return ImageFont.load_default()


def build_icon(size=2048):
    cx = cy = size / 2
    R = size * 0.34          # C 环半径
    W = int(size * 0.072)    # C 环描边宽
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 主 C 环(缺口朝右, 从 315° 顺时针绕左半圈到 45°), 实体无光晕
    gradient_arc(d, cx, cy, R, W, 315, 45)

    # 缺口内音频波形(3 条渐变高度竖条, 青色)
    w = int(size * 0.030)
    r = w // 2
    heights = [0.30, 0.46, 0.20]
    xs = [cx + R * 0.79, cx + R * 0.92, cx + R * 1.05]
    for i, (x, h) in enumerate(zip(xs, heights)):
        half = size * h / 2
        d.rounded_rectangle(
            [x - w / 2, cy - half, x + w / 2, cy + half],
            radius=r, fill=lerp(CYAN, PURPLE, 0.85 if i == 1 else 0.35),
        )
    return img


def build_lockup(size=2400, height=1000):
    """横向组合版: 图标 + CunSub 文字 + 副标题。
    画布加宽 + 基于文字实际像素 bbox 处理, 避免末尾字母被裁。
    """
    canvas = Image.new("RGBA", (size, height), (0, 0, 0, 0))
    icon_size = int(height * 0.80)
    icon = build_icon(icon_size)
    icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
    canvas.alpha_composite(icon, (int(height * 0.08), (height - icon_size) // 2))

    # 文字区起点 x: 图标右缘 + 间距
    icon_right = int(height * 0.08) + icon_size
    text_x0 = icon_right + int(height * 0.10)
    ty = height // 2

    f_main = load_font("segoeuib.ttf", int(height * 0.30))
    main_bbox = f_main.getbbox("CunSub")
    main_w = main_bbox[2] - main_bbox[0]
    main_h = main_bbox[3] - main_bbox[1]

    # 1) 先渲染文字到足够大的图层(anchor="mm" 按中心定位)
    text_layer = Image.new("RGBA", (size, height), (0, 0, 0, 0))
    dt = ImageDraw.Draw(text_layer)
    dt.text((text_x0 + main_w / 2, ty), "CunSub", font=f_main, fill=WHITE, anchor="mm")

    # 2) 按文字实际像素范围裁剪, 并做水平青→紫渐变
    mask = text_layer.split()[3]
    bbox = mask.getbbox()
    cropped = text_layer.crop(bbox)
    cmask = cropped.split()[3]
    cw, ch = cropped.size
    grad = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for x in range(cw):
        t = x / max(cw - 1, 1)
        gd.line([(x, 0), (x, ch)], fill=lerp(CYAN, PURPLE, t), width=1)
    colored = Image.composite(grad, Image.new("RGBA", (cw, ch), (0, 0, 0, 0)), cmask)
    canvas.alpha_composite(colored, (bbox[0], bbox[1]))

    # 3) 副标题 "AI SUBTITLE WORKFLOW"(主文字下方居中)
    f_sub = load_font("consola.ttf", int(height * 0.052))
    sub_img = Image.new("RGBA", (size, height), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sub_img)
    ds.text(
        (text_x0 + main_w / 2, ty + main_h / 2 + int(height * 0.045)),
        "AI SUBTITLE WORKFLOW", font=f_sub, fill=GRAY, anchor="mm",
    )
    sub_mask = sub_img.split()[3]
    sub_bbox = sub_mask.getbbox()
    if sub_bbox:
        canvas.alpha_composite(sub_img.crop(sub_bbox), (sub_bbox[0], sub_bbox[1]))
    return canvas


if __name__ == "__main__":
    import pathlib
    out = pathlib.Path(__file__).resolve().parent
    build_icon().save(out / "cunsub-logo-icon.png")
    build_lockup().save(out / "cunsub-logo.png")
    print("done:", out / "cunsub-logo-icon.png", out / "cunsub-logo.png")
