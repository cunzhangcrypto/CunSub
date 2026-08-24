# -*- coding: utf-8 -*-
"""CunSub Launcher — 村长实验室
深色科技感 GUI 启动器: 一键启动/停止前后端服务, 状态指示灯, 实时日志面板。
"""
import os
import socket
import subprocess
import sys
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
LOG_BE = BACKEND / "backend.log"
LOG_BE_ERR = BACKEND / "backend.err.log"
LOG_FE = FRONTEND / "vite.log"
LOG_FE_ERR = FRONTEND / "vite.err.log"
ICON = ROOT / "logo" / "cunsub-logo-icon.png"

# ---- 配色(与产品 UI 一致: 暗色 + 青/紫渐变) ----
BG = "#0b0f17"
CARD = "#0f172a"
BORDER = "#1e293b"
CYAN = "#22d3ee"
PURPLE = "#a855f7"
WHITE = "#e2e8f0"
DIM = "#64748b"
GREEN = "#22c55e"
RED = "#ef4444"
YELLOW = "#facc15"


def port_open(port: int) -> bool:
    # Vite 可能监听 IPv6 ::1, 后端监听 IPv4 127.0.0.1, 两个都要试
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            continue
    return False


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CunSub Launcher · 村长实验室")
        self.configure(bg=BG)
        self.geometry("940x700")
        self.minsize(880, 620)

        self.be_proc = None
        self.fe_proc = None
        self.be_tail = 0
        self.fe_tail = 0
        self.be_restarts = 0
        self.fe_restarts = 0
        self._started = False  # start_services 是否已被调用
        self._browser_opened = False  # 浏览器是否已打开(仅在 _tick 中开一次)

        self._fonts()
        self._build()
        # 初始状态:显示"正在启动..."(黄灯), 避免 start_services(1200ms) 前出现"未运行"(红灯)
        self._set_card(self._card_be, None)
        self._set_card(self._card_fe, None)
        self.after(800, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # 打开后自动启动服务(无需手动点按钮)
        self.after(1200, self.start_services)

    # ---------------- UI ----------------
    def _fonts(self):
        self.f_title = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.f_sub = tkfont.Font(family="Consolas", size=10)
        self.f_card = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_btn = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_log = tkfont.Font(family="Consolas", size=9)

    def _build(self):
        # ---- Header ----
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=28, pady=(24, 8))
        logo = tk.Label(header, bg=BG)
        if HAS_PIL and ICON.exists():
            img = Image.open(ICON).convert("RGBA").resize((88, 88), Image.LANCZOS)
            self._logo_img = ImageTk.PhotoImage(img)
            logo.config(image=self._logo_img)
        else:
            logo.config(text="C", fg=CYAN, font=("Segoe UI", 44, "bold"))
        logo.pack(side="left")
        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left", padx=(18, 0))
        tk.Label(title_box, text="CunSub", fg=WHITE, bg=BG, font=self.f_title).pack(anchor="w")
        tk.Label(title_box, text="村长实验室 · AI 字幕工作流助手", fg=DIM, bg=BG, font=self.f_sub).pack(anchor="w", pady=(2, 0))
        tk.Label(header, text="v1.0", fg=CYAN, bg=BG, font=("Consolas", 11, "bold")).pack(side="right")

        # ---- 状态卡片 ----
        status = tk.Frame(self, bg=BG)
        status.pack(fill="x", padx=28, pady=10)
        self._card_be = self._make_card(status, "后端服务  BACKEND", 5278)
        self._card_be["frame"].pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._card_fe = self._make_card(status, "前端服务  FRONTEND", 5277)
        self._card_fe["frame"].pack(side="left", fill="x", expand=True, padx=(8, 0))

        # ---- 按钮 ----
        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", padx=28, pady=14)
        self._btn_start = self._mk_button(btns, "启动服务", CYAN, self.start_services, bg="#0891b2")
        self._btn_start.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._btn_stop = self._mk_button(btns, "停止服务", RED, self.stop_services, bg="#b91c1c")
        self._btn_stop.pack(side="left", fill="x", expand=True, padx=6)
        self._btn_open = self._mk_button(btns, "打开界面", PURPLE, self.open_browser, bg="#7c3aed")
        self._btn_open.pack(side="left", fill="x", expand=True, padx=(6, 0))

        # ---- 日志 ----
        log_box = tk.Frame(self, bg=CARD)
        log_box.pack(fill="both", expand=True, padx=28, pady=(6, 26))
        tk.Label(log_box, text="运行日志", fg=DIM, bg=CARD, font=self.f_sub).pack(anchor="w", padx=14, pady=(10, 4))
        log_area = tk.Frame(log_box, bg=BG)
        log_area.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.log = tk.Text(
            log_area, bg=BG, fg=WHITE, font=self.f_log, wrap="word",
            bd=0, highlightthickness=0, insertbackground=CYAN, state="disabled"
        )
        scroll = tk.Scrollbar(log_area, command=self.log.yview, bg=BORDER, troughcolor=BG, bd=0)
        self.log.config(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        for tag, color in (("SYSTEM", CYAN), ("backend", "#94a3b8"), ("frontend", WHITE), ("ERR", RED)):
            self.log.tag_config(tag, foreground=color)

    def _make_card(self, parent, label, port):
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        dot = tk.Canvas(card, width=16, height=16, bg=CARD, highlightthickness=0)
        dot.create_oval(3, 3, 13, 13, fill="#334155", outline="")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=16, pady=(14, 4))
        dot.pack(side="left", in_=row, padx=(0, 10))
        tk.Label(row, text=label, fg=WHITE, bg=CARD, font=self.f_card).pack(side="left")
        state = tk.Frame(card, bg=CARD)
        state.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(state, text="PORT " + str(port), fg=DIM, bg=CARD, font=("Consolas", 9)).pack(side="left")
        lbl = tk.Label(state, text="未运行", fg=DIM, bg=CARD, font=("Consolas", 9, "bold"))
        lbl.pack(side="right")
        return {"frame": card, "dot": dot, "lbl": lbl}

    def _mk_button(self, parent, text, fg, cmd, bg):
        return tk.Button(
            parent, text=text, command=cmd, fg=fg, bg=bg,
            activeforeground="white", activebackground=bg,
            font=self.f_btn, bd=0, highlightthickness=1,
            highlightbackground=bg, cursor="hand2",
            padx=10, pady=10, relief="flat",
        )

    # ---------------- 日志 ----------------
    def _log_line(self, tag, text):
        self.log.config(state="normal")
        self.log.insert("end", f"[{tag}] {text}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _tail(self, path, pos):
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return pos, []
        return len(lines), lines[pos:]

    # ---------------- 服务控制 ----------------
    def start_services(self):
        """启动缺失的服务(后端/前端各自独立判断)。
        旧逻辑: 任一服务已在运行就整段跳过, 导致"后端在跑、前端没跑"时
        点启动永远无法把前端拉起。现在只补齐缺失的那一个。
        """
        be_up = port_open(5278) or (self.be_proc and self.be_proc.poll() is None)
        fe_up = port_open(5277) or (self.fe_proc and self.fe_proc.poll() is None)
        if be_up and fe_up:
            self._started = True
            self._log_line("SYSTEM", "前后端服务均已在运行")
            self.open_browser()
            return
        if not be_up:
            self._spawn_backend()
        if not fe_up:
            self._spawn_frontend()
        self._started = True
        self._log_line("SYSTEM", f"服务状态: 后端={'运行中' if be_up else '已启动'} 前端={'运行中' if fe_up else '已启动'}")

    def _spawn_backend(self):
        try:
            for f in (LOG_BE, LOG_BE_ERR):
                try:
                    f.unlink()
                except OSError:
                    pass
            be_out = open(LOG_BE, "wb", buffering=0)
            be_err = open(LOG_BE_ERR, "wb", buffering=0)
            self.be_proc = subprocess.Popen(
                [sys.executable, "run.py"], cwd=str(BACKEND),
                stdout=be_out, stderr=be_err, env=dict(os.environ, NO_COLOR="1"),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.be_restarts = 0
            self._log_line("SYSTEM", "后端已启动 (5278)")
        except Exception as e:
            self._log_line("ERR", f"后端启动失败: {e}")

    def _spawn_frontend(self):
        try:
            for f in (LOG_FE, LOG_FE_ERR):
                try:
                    f.unlink()
                except OSError:
                    pass
            fe_out = open(LOG_FE, "wb", buffering=0)
            fe_err = open(LOG_FE_ERR, "wb", buffering=0)
            self.fe_proc = subprocess.Popen(
                ["cmd", "/c", "npm run dev"], cwd=str(FRONTEND),
                stdout=fe_out, stderr=fe_err, env=dict(os.environ, NO_COLOR="1"),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.fe_restarts = 0
            self._log_line("SYSTEM", "前端已启动 (5277)")
        except Exception as e:
            self._log_line("ERR", f"前端启动失败: {e}")

    def stop_services(self):
        for name, proc in (("backend", self.be_proc), ("frontend", self.fe_proc)):
            if proc and proc.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                self._log_line("SYSTEM", f"{name} 已停止")
        self.be_proc = self.fe_proc = None

    def open_browser(self):
        if port_open(5277) and port_open(5278):
            try:
                import webbrowser
                webbrowser.open("http://localhost:5277")
                self._log_line("SYSTEM", "已打开浏览器: http://localhost:5277")
            except Exception as e:
                self._log_line("ERR", f"打开浏览器失败: {e}")
        else:
            self._log_line("SYSTEM", "服务未就绪，等待重试...")
            self.after(2000, self.open_browser)

    # ---------------- 轮询 ----------------
    def _tick(self):
        be_ok = port_open(5278)
        fe_ok = port_open(5277)
        # 自动重启: 已托管的进程意外退出且端口不在监听时补拉起来(最多 3 次, 防死循环)
        if not be_ok and self.be_proc and self.be_proc.poll() is not None:
            if self.be_restarts < 3:
                self.be_restarts += 1
                self._log_line("ERR", f"后端已退出, 自动重启 ({self.be_restarts}/3)...")
                self._spawn_backend()
        if not fe_ok and self.fe_proc and self.fe_proc.poll() is not None:
            if self.fe_restarts < 3:
                self.fe_restarts += 1
                self._log_line("ERR", f"前端已退出, 自动重启 ({self.fe_restarts}/3)...")
                self._spawn_frontend()

        self._set_card(self._card_be, be_ok)
        self._set_card(self._card_fe, fe_ok)
        self._set_start_btn(be_ok and fe_ok)

        # 前后端都就绪后自动打开浏览器(仅一次)
        if be_ok and fe_ok and not self._browser_opened:
            self._browser_opened = True
            self._log_line("SYSTEM", "正在打开浏览器...")
            try:
                import webbrowser
                webbrowser.open("http://localhost:5277")
                self._log_line("SYSTEM", "已打开浏览器: http://localhost:5277")
            except Exception as e:
                self._log_line("ERR", f"打开浏览器失败: {e}")

        for tag, path, attr in (("backend", LOG_BE, "be_tail"), ("frontend", LOG_FE, "fe_tail")):
            pos, new = self._tail(path, getattr(self, attr))
            if new:
                for line in new:
                    bad = ("ERROR", "Traceback", "Error", "error", "Exception", "FAILED")
                    t = "ERR" if tag == "backend" and any(b in line for b in bad) else tag
                    self._log_line(t, line)
                setattr(self, attr, pos)
        self.after(1000, self._tick)

    def _set_start_btn(self, running):
        if running:
            self._btn_start.config(text="启动服务 · 运行中", bg=CYAN, fg=BG,
                                   activebackground=CYAN, activeforeground=BG)
        else:
            self._btn_start.config(text="启动服务", bg="#0891b2", fg=CYAN,
                                   activebackground="#0891b2", activeforeground="white")

    def _set_card(self, card, ok):
        if ok is None:
            card["dot"].itemconfig(1, fill=YELLOW)
            card["lbl"].config(text="正在启动...", fg=YELLOW)
        elif ok:
            card["dot"].itemconfig(1, fill=GREEN)
            card["lbl"].config(text="运行中", fg=GREEN)
        else:
            card["dot"].itemconfig(1, fill=RED)
            label = "未运行" if self._started else "正在启动..."
            card["lbl"].config(text=label, fg=RED if self._started else YELLOW)

    def _on_close(self):
        if (self.be_proc and self.be_proc.poll() is None) or (self.fe_proc and self.fe_proc.poll() is None):
            self.stop_services()
        self.destroy()


# 单实例锁端口(仅用于防止启动器双开, 不影响服务端口)
LOCK_PORT = 5290


def _acquire_lock():
    """绑定固定端口做单实例互斥, 已有实例则返回 None"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


if __name__ == "__main__":
    lock = _acquire_lock()
    if lock is None:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "CunSub 启动器已在运行, 请查看已打开的窗口。", "CunSub", 0x40
            )
        except Exception:
            pass
        sys.exit(0)
    try:
        Launcher().mainloop()
    finally:
        lock.close()
