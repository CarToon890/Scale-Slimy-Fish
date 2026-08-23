"""
Main GUI Application for Scale Slimy Fish Auto Fishing Bot.
Features:
- Master Technical Specification Architecture (6-State FSM + Global Interrupt Layer)
- Auto Modal Handler: Detects & clears "Click to Continue" / "Found New Fish!" modals
- Dual Anchor Detection: Hold to fish Template + Red '!' Icon
- Extra-Large High-Definition Camera Monitors (390x190px)
- Dynamic Rod Calculator (Depth: 330m+ & Strength: 146+ -> Auto Reel Duration & Dynamic Timeout)
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import json
import os
import ctypes
import keyboard
import cv2
import numpy as np
from PIL import Image, ImageTk
from bot_core import FishingBot, BotState, InputSimulator

# Enable DPI Awareness at startup
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class ModernColors:
    BG_DARK = "#181825"
    CARD_BG = "#1e1e2e"
    ACCENT_GREEN = "#a6e3a1"
    ACCENT_RED = "#f38ba8"
    ACCENT_BLUE = "#89b4fa"
    ACCENT_YELLOW = "#f9e2af"
    ACCENT_PURPLE = "#cba6f7"
    TEXT_MAIN = "#cdd6f4"
    TEXT_MUTED = "#a6adc8"
    BORDER = "#313244"
    PREVIEW_BG = "#11111b"


class FullscreenFrozenSelector(tk.Toplevel):
    def __init__(self, parent, target_name, mode="box", on_selected=None):
        super().__init__(parent)
        self.target_name = target_name
        self.mode = mode
        self.on_selected = on_selected
        self.title(f"Select - {target_name}")
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.config(cursor="cross")

        self.sw = self.winfo_screenwidth()
        self.sh = self.winfo_screenheight()

        import mss
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            self.raw_shot = shot
            img_rgb = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            self.screen_img = img_rgb.resize((self.sw, self.sh), Image.Resampling.BILINEAR)

        dimmed = Image.blend(self.screen_img, Image.new("RGB", (self.sw, self.sh), (20, 20, 30)), 0.30)
        self.bg_photo = ImageTk.PhotoImage(dimmed)

        self.canvas = tk.Canvas(self, width=self.sw, height=self.sh, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")

        self.start_x = None
        self.start_y = None
        self.rect_id = None

        if self.mode == "box":
            self.canvas.bind("<ButtonPress-1>", self.on_box_press)
            self.canvas.bind("<B1-Motion>", self.on_box_drag)
            self.canvas.bind("<ButtonRelease-1>", self.on_box_release)
            guide_text = f"🎯 คลิกซ้ายแล้วลากกรอบสีเขียวครอบ: {target_name} (กด ESC เพื่อยกเลิก)"
        else:
            self.canvas.bind("<ButtonRelease-1>", self.on_point_click)
            guide_text = f"🎯 คลิกซ้าย 1 ครั้งบนตำแหน่ง: {target_name} (กด ESC เพื่อยกเลิก)"

        self.bind("<Escape>", lambda e: self.destroy())

        self.canvas.create_rectangle(0, 0, self.sw, 55, fill="#11111b", outline="")
        self.canvas.create_text(
            self.sw // 2, 28,
            text=guide_text,
            fill="#a6e3a1", font=("Segoe UI", 15, "bold")
        )

    def on_box_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#50fa7b", width=3, fill="#50fa7b", stipple="gray25"
        )

    def on_box_drag(self, event):
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def on_box_release(self, event):
        end_x, end_y = event.x, event.y
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        w = x2 - x1
        h = y2 - y1

        if w > 8 and h > 8:
            roi_ratio = {
                "x_ratio": round(x1 / self.sw, 4),
                "y_ratio": round(y1 / self.sh, 4),
                "w_ratio": round(w / self.sw, 4),
                "h_ratio": round(h / self.sh, 4)
            }
            crop_img = np.array(self.screen_img.crop((x1, y1, x2, y2)))
            crop_bgr = cv2.cvtColor(crop_img, cv2.COLOR_RGB2BGR)

            if self.on_selected:
                self.on_selected(roi_ratio, crop_bgr)
        self.destroy()

    def on_point_click(self, event):
        pt_ratio = {
            "x_ratio": round(event.x / self.sw, 4),
            "y_ratio": round(event.y / self.sh, 4)
        }
        if self.on_selected:
            self.on_selected(pt_ratio, None)
        self.destroy()


class FishingBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Scale Slimy Fish — Master 6-State Bot")
        self.root.geometry("860x1020")
        self.root.minsize(820, 880)
        self.root.configure(bg=ModernColors.BG_DARK)

        self.config_path = "config.json"
        self.config = self.load_config()

        self.bot = FishingBot(
            config_path=self.config_path,
            log_callback=self.append_log,
            state_callback=self.update_state_display,
            stats_callback=self.update_stats_display,
            progress_callback=self.update_progress_display
        )

        self.preview_cache = {}
        self.is_live_stream_active = True
        self.stream_thread = None

        self.build_ui()
        self.setup_hotkeys()
        self.start_uptime_timer()
        self.start_live_stream_thread()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")
        return {}

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            self.append_log("💾 บันทึกการตั้งค่าลง config.json เรียบร้อยแล้ว")
            self.bot.reload_config()
        except Exception as e:
            messagebox.showerror("Error", f"ไม่สามารถบันทึก config ได้: {e}")

    def build_ui(self):
        # 1. Header
        header = tk.Frame(self.root, bg=ModernColors.CARD_BG, padx=16, pady=8)
        header.pack(fill="x", padx=14, pady=(8, 2))

        title_frame = tk.Frame(header, bg=ModernColors.CARD_BG)
        title_frame.pack(fill="x")

        title_lbl = tk.Label(
            title_frame,
            text="🎣 SCALE SLIMY FISH — MASTER BOT (6-STATE & INTERRUPT)",
            font=("Segoe UI", 14, "bold"),
            fg=ModernColors.ACCENT_BLUE,
            bg=ModernColors.CARD_BG
        )
        title_lbl.pack(side="left")

        self.btn_start = tk.Button(
            title_frame,
            text="▶ เริ่มทำงาน (F6)",
            font=("Segoe UI", 10, "bold"),
            bg="#238636", fg="white", activebackground="#2ea043",
            relief="flat", padx=12, pady=4, cursor="hand2",
            command=self.start_bot
        )
        self.btn_start.pack(side="right", padx=(4, 0))

        self.btn_stop = tk.Button(
            title_frame,
            text="⏹ หยุดชั่วคราว (F7)",
            font=("Segoe UI", 10, "bold"),
            bg="#da3633", fg="white", activebackground="#f85149",
            relief="flat", padx=12, pady=4, cursor="hand2",
            command=self.stop_bot
        )
        self.btn_stop.pack(side="right", padx=4)

        # 2. Activity & Progress Banner
        banner_frame = tk.Frame(self.root, bg=ModernColors.CARD_BG, padx=14, pady=6, relief="solid", bd=1)
        banner_frame.pack(fill="x", padx=14, pady=2)

        banner_top = tk.Frame(banner_frame, bg=ModernColors.CARD_BG)
        banner_top.pack(fill="x")

        self.state_var = tk.StringVar(value="สถานะ: STATE 0: IDLE (หยุดพัก)")
        self.state_badge = tk.Label(
            banner_top,
            textvariable=self.state_var,
            font=("Segoe UI", 11, "bold"),
            fg=ModernColors.ACCENT_YELLOW,
            bg=ModernColors.CARD_BG
        )
        self.state_badge.pack(side="left")

        self.lbl_uptime = tk.Label(banner_top, text="⏱️ เวลาทำงาน: 00:00:00", font=("Segoe UI", 9), fg=ModernColors.TEXT_MUTED, bg=ModernColors.CARD_BG)
        self.lbl_uptime.pack(side="right")

        self.activity_var = tk.StringVar(value="พร้อมทำงาน (กด F6 เพื่อเริ่มต้น หรือปรับสเปกในแท็บการตั้งค่า)")
        self.activity_lbl = tk.Label(
            banner_frame,
            textvariable=self.activity_var,
            font=("Segoe UI", 9, "italic"),
            fg=ModernColors.TEXT_MAIN,
            bg=ModernColors.CARD_BG
        )
        self.activity_lbl.pack(anchor="w", pady=(1, 4))

        style = ttk.Style()
        style.theme_use('default')
        style.configure("Custom.Horizontal.TProgressbar", troughcolor=ModernColors.BORDER, background=ModernColors.ACCENT_BLUE, thickness=7)
        style.configure("TNotebook", background=ModernColors.BG_DARK, borderwidth=0)
        style.configure("TNotebook.Tab", background=ModernColors.CARD_BG, foreground=ModernColors.TEXT_MAIN, padding=[16, 6], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", ModernColors.BORDER)], foreground=[("selected", ModernColors.ACCENT_BLUE)])

        self.progress_bar = ttk.Progressbar(
            banner_frame,
            style="Custom.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
            maximum=100.0
        )
        self.progress_bar.pack(fill="x")

        # Stats Row
        stats_frame = tk.Frame(banner_frame, bg=ModernColors.CARD_BG)
        stats_frame.pack(fill="x", pady=(4, 0))

        self.lbl_casts = tk.Label(stats_frame, text="🎣 เหวี่ยงเบ็ด: 0 ครั้ง", font=("Segoe UI", 9, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG)
        self.lbl_casts.pack(side="left", padx=(0, 10))

        self.lbl_fish = tk.Label(stats_frame, text="🐟 ปลาที่ได้: 0 ตัว", font=("Segoe UI", 9, "bold"), fg=ModernColors.ACCENT_GREEN, bg=ModernColors.CARD_BG)
        self.lbl_fish.pack(side="left", padx=10)

        self.lbl_perfect = tk.Label(stats_frame, text="✨ Perfect: 0 ครั้ง", font=("Segoe UI", 9, "bold"), fg=ModernColors.ACCENT_YELLOW, bg=ModernColors.CARD_BG)
        self.lbl_perfect.pack(side="left", padx=10)

        self.lbl_modals = tk.Label(stats_frame, text="🚨 ปิดป๊อปอัปปลาหายาก: 0 ครั้ง", font=("Segoe UI", 9, "bold"), fg=ModernColors.ACCENT_PURPLE, bg=ModernColors.CARD_BG)
        self.lbl_modals.pack(side="left", padx=10)

        # 3. Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=4)

        self.tab_monitor = tk.Frame(self.notebook, bg=ModernColors.BG_DARK)
        self.notebook.add(self.tab_monitor, text="  📺 จอภาพสดขนาดใหญ่ (Live Monitors)  ")

        self.tab_settings = tk.Frame(self.notebook, bg=ModernColors.BG_DARK)
        self.notebook.add(self.tab_settings, text="  ⚙️ การตั้งค่าแบบละเอียด (Advanced Settings)  ")

        self.tab_logs = tk.Frame(self.notebook, bg=ModernColors.BG_DARK)
        self.notebook.add(self.tab_logs, text="  📋 บันทึกการทำงานสด (Live Logs)  ")

        self.build_tab_monitor()
        self.build_tab_settings()
        self.build_tab_logs()

    def build_tab_monitor(self):
        rod_card = tk.LabelFrame(
            self.tab_monitor,
            text=" 🎣 คำนวณสเปกคันเบ็ดระดับสูง (Depth: 330m+ / Strength: 146+) ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_PURPLE,
            bg=ModernColors.CARD_BG,
            padx=10,
            pady=4
        )
        rod_card.pack(fill="x", padx=6, pady=(4, 2))

        rod_row1 = tk.Frame(rod_card, bg=ModernColors.CARD_BG)
        rod_row1.pack(fill="x")

        tk.Label(rod_row1, text="Depth (m):", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG).pack(side="left", padx=(0, 2))
        self.depth_entry = tk.Entry(rod_row1, width=6, bg="#11111b", fg=ModernColors.ACCENT_YELLOW, insertbackground="white", font=("Segoe UI", 9, "bold"))
        current_depth = self.config.get("rod_stats", {}).get("depth", 330)
        self.depth_entry.insert(0, str(current_depth))
        self.depth_entry.pack(side="left", padx=(0, 8))
        self.depth_entry.bind("<KeyRelease>", self.on_rod_stat_change)

        tk.Label(rod_row1, text="Strength:", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG).pack(side="left", padx=(0, 2))
        self.str_entry = tk.Entry(rod_row1, width=6, bg="#11111b", fg=ModernColors.ACCENT_GREEN, insertbackground="white", font=("Segoe UI", 9, "bold"))
        current_str = self.config.get("rod_stats", {}).get("strength", 146)
        self.str_entry.insert(0, str(current_str))
        self.str_entry.pack(side="left", padx=(0, 8))
        self.str_entry.bind("<KeyRelease>", self.on_rod_stat_change)

        calc_sec = round((float(current_depth) / max(1.0, float(current_str))) * 1.65 + 0.5, 1)
        calc_sink = round(max(18.0, (float(current_depth) / 12.0) + 5.0), 1)

        self.calc_time_lbl = tk.Label(
            rod_row1,
            text=f"⚡ ดึงปลา (Reel): {calc_sec}s  |  🌊 จมน้ำสูงสุด (Sinking): {calc_sink}s",
            font=("Segoe UI", 8, "bold"),
            fg=ModernColors.ACCENT_BLUE,
            bg=ModernColors.CARD_BG
        )
        self.calc_time_lbl.pack(side="left", padx=4)

        tk.Button(
            rod_row1, text="🎯 Safe Zone (50%, 38%)", font=("Segoe UI", 8, "bold"),
            bg=ModernColors.BORDER, fg=ModernColors.ACCENT_PURPLE, relief="flat",
            command=self.open_point_selector
        ).pack(side="right", padx=2)

        # 2 Camera Monitors (390x190px)
        cam_container = tk.Frame(self.tab_monitor, bg=ModernColors.BG_DARK)
        cam_container.pack(fill="both", expand=True, padx=6, pady=2)

        # Monitor 1: Power Bar
        c1 = tk.LabelFrame(
            cam_container,
            text=" 1. แถบเกจพลังงาน (Power Bar Sub-ROI 15% - State 1) ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_GREEN,
            bg=ModernColors.CARD_BG,
            padx=6,
            pady=4
        )
        c1.pack(side="left", fill="both", expand=True, padx=(0, 3))

        self.img_lbl_pb = tk.Label(c1, text="[กำลังเชื่อมต่อกล้องสด...]", fg=ModernColors.TEXT_MUTED, bg=ModernColors.PREVIEW_BG)
        self.img_lbl_pb.pack(fill="both", expand=True, pady=2)

        self.status_lbl_pb = tk.Label(c1, text="⚪ สตรีมสด...", font=("Segoe UI", 9, "bold"), fg=ModernColors.TEXT_MUTED, bg=ModernColors.CARD_BG)
        self.status_lbl_pb.pack()

        tk.Button(
            c1, text="🎯 ลากเลือกพื้นที่เกจ Power Bar (Manual ROI)", font=("Segoe UI", 8, "bold"),
            bg=ModernColors.BORDER, fg=ModernColors.ACCENT_GREEN, relief="flat",
            command=lambda: self.open_roi_selector("Power Bar (แถบเกจพลังทางขวา)", "cast_bar_roi")
        ).pack(fill="x", pady=2)

        # Monitor 2: Hold to Fish Template & Exclamation
        c2 = tk.LabelFrame(
            cam_container,
            text=" 2. ข้อความ Hold to fish & ไอคอน '!' (State 2/3) ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_YELLOW,
            bg=ModernColors.CARD_BG,
            padx=6,
            pady=4
        )
        c2.pack(side="left", fill="both", expand=True, padx=(3, 0))

        self.img_lbl_hold = tk.Label(c2, text="[กำลังเชื่อมต่อกล้องสด...]", fg=ModernColors.TEXT_MUTED, bg=ModernColors.PREVIEW_BG)
        self.img_lbl_hold.pack(fill="both", expand=True, pady=2)

        self.status_lbl_hold = tk.Label(c2, text="⚪ สตรีมสด...", font=("Segoe UI", 9, "bold"), fg=ModernColors.TEXT_MUTED, bg=ModernColors.CARD_BG)
        self.status_lbl_hold.pack()

        c2_btns = tk.Frame(c2, bg=ModernColors.CARD_BG)
        c2_btns.pack(fill="x", pady=2)

        tk.Button(
            c2_btns, text="📸 แคปภาพแม่แบบ Template", font=("Segoe UI", 8, "bold"),
            bg="#238636", fg="white", relief="flat",
            command=self.open_template_capture_selector
        ).pack(side="left", fill="x", expand=True, padx=(0, 2))

        tk.Button(
            c2_btns, text="🎯 ลากกรอบ Hold", font=("Segoe UI", 8),
            bg=ModernColors.BORDER, fg=ModernColors.ACCENT_YELLOW, relief="flat",
            command=lambda: self.open_roi_selector("Hold to fish (ข้อความกึ่งกลางจอ)", "hold_roi")
        ).pack(side="right", fill="x", expand=True, padx=(2, 0))

    def build_tab_settings(self):
        container = tk.Frame(self.tab_settings, bg=ModernColors.BG_DARK, padx=8, pady=4)
        container.pack(fill="both", expand=True)

        s1 = tk.LabelFrame(
            container,
            text=" ⏱️ การปรับแต่งเวลาและจังหวะ (Timing Delays ตาม Master Spec) ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_BLUE,
            bg=ModernColors.CARD_BG,
            padx=10,
            pady=4
        )
        s1.pack(fill="x", pady=3)

        r1 = tk.Frame(s1, bg=ModernColors.CARD_BG)
        r1.pack(fill="x", pady=2)

        current_gate = int(self.config.get("timings", {}).get("min_charge_gate_ms", 450) or 450)
        self.gate_val_lbl = tk.Label(r1, text=f"⚡ หน่วงก่อนสแกนเกจชาร์จ (Min Charge Gate): {current_gate} ms", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG)
        self.gate_val_lbl.pack(anchor="w")

        self.gate_slider = tk.Scale(
            r1, from_=100, to=600, orient="horizontal", resolution=25, showvalue=False,
            bg=ModernColors.CARD_BG, fg=ModernColors.TEXT_MAIN, troughcolor=ModernColors.BORDER, highlightthickness=0,
            command=self.on_gate_slider_change
        )
        self.gate_slider.set(current_gate)
        self.gate_slider.pack(fill="x")

        r2 = tk.Frame(s1, bg=ModernColors.CARD_BG)
        r2.pack(fill="x", pady=2)

        current_recast = self.config.get("timings", {}).get("recast_delay_sec", 1.9)
        self.recast_val_lbl = tk.Label(r2, text=f"⏳ เวลาหน่วงหลังตกเสร็จ (Fast Recast Delay): {current_recast:.1f} s (แนะนำ 1.9s)", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG)
        self.recast_val_lbl.pack(anchor="w")

        self.recast_slider = tk.Scale(
            r2, from_=1.0, to=3.5, orient="horizontal", resolution=0.1, showvalue=False,
            bg=ModernColors.CARD_BG, fg=ModernColors.TEXT_MAIN, troughcolor=ModernColors.BORDER, highlightthickness=0,
            command=self.on_recast_slider_change
        )
        self.recast_slider.set(current_recast)
        self.recast_slider.pack(fill="x")

        r3 = tk.Frame(s1, bg=ModernColors.CARD_BG)
        r3.pack(fill="x", pady=2)

        current_reaction = int(self.config.get("timings", {}).get("bite_reaction_delay_ms", 350) or 350)
        self.reaction_val_lbl = tk.Label(r3, text=f"🐟 เวลาตอบสนองก่อนดึงเบ็ด (Bite Reaction Delay): {current_reaction} ms", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG)
        self.reaction_val_lbl.pack(anchor="w")

        self.reaction_slider = tk.Scale(
            r3, from_=150, to=800, orient="horizontal", resolution=25, showvalue=False,
            bg=ModernColors.CARD_BG, fg=ModernColors.TEXT_MAIN, troughcolor=ModernColors.BORDER, highlightthickness=0,
            command=self.on_reaction_slider_change
        )
        self.reaction_slider.set(current_reaction)
        self.reaction_slider.pack(fill="x")

        s2 = tk.LabelFrame(
            container,
            text=" 🎯 ความแม่นยำและการตรวจจับภาพ (Vision Thresholds) ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_YELLOW,
            bg=ModernColors.CARD_BG,
            padx=10,
            pady=4
        )
        s2.pack(fill="x", pady=3)

        r4 = tk.Frame(s2, bg=ModernColors.CARD_BG)
        r4.pack(fill="x", pady=2)

        current_tpl_score = int(self.config.get("thresholds", {}).get("hold_template_match_threshold", 0.65) * 100)
        self.tpl_val_lbl = tk.Label(r4, text=f"🎯 ความแม่นยำ Template 'Hold to fish': {current_tpl_score}% (แนะนำ 65%)", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG)
        self.tpl_val_lbl.pack(anchor="w")

        self.tpl_slider = tk.Scale(
            r4, from_=40, to=90, orient="horizontal", resolution=1, showvalue=False,
            bg=ModernColors.CARD_BG, fg=ModernColors.TEXT_MAIN, troughcolor=ModernColors.BORDER, highlightthickness=0,
            command=self.on_tpl_slider_change
        )
        self.tpl_slider.set(current_tpl_score)
        self.tpl_slider.pack(fill="x")

        s3 = tk.LabelFrame(
            container,
            text=" 🛡️ สวิตช์ฟังก์ชันความปลอดภัย & Global Interrupt ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_GREEN,
            bg=ModernColors.CARD_BG,
            padx=10,
            pady=4
        )
        s3.pack(fill="x", pady=3)

        features = self.config.get("features", {})
        self.var_interrupt = tk.BooleanVar(value=features.get("global_interrupt_enabled", True))
        self.var_double_check = tk.BooleanVar(value=features.get("double_check_enabled", True))
        self.var_pre_cast = tk.BooleanVar(value=features.get("pre_cast_validation", True))
        self.var_lightning = tk.BooleanVar(value=features.get("lightning_flash_rejection", True))
        self.var_failsafe = tk.BooleanVar(value=features.get("failsafe_auto_recovery", True))

        t_row1 = tk.Frame(s3, bg=ModernColors.CARD_BG)
        t_row1.pack(fill="x", pady=1)

        tk.Checkbutton(
            t_row1, text="🚨 Global Interrupt (ดักจับป๊อปอัปปลาหายาก 'Click to Continue')",
            variable=self.var_interrupt, font=("Segoe UI", 8, "bold"), fg=ModernColors.ACCENT_PURPLE, bg=ModernColors.CARD_BG,
            selectcolor="#11111b", command=self.on_toggle_feature
        ).pack(side="left", padx=4)

        tk.Checkbutton(
            t_row1, text="✅ Triple Double-Check",
            variable=self.var_double_check, font=("Segoe UI", 8), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG,
            selectcolor="#11111b", command=self.on_toggle_feature
        ).pack(side="left", padx=16)

        t_row2 = tk.Frame(s3, bg=ModernColors.CARD_BG)
        t_row2.pack(fill="x", pady=1)

        tk.Checkbutton(
            t_row2, text="⚡ กรองแสงฟ้าผ่า (Lightning Rejection)",
            variable=self.var_lightning, font=("Segoe UI", 8), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG,
            selectcolor="#11111b", command=self.on_toggle_feature
        ).pack(side="left", padx=4)

        tk.Checkbutton(
            t_row2, text="🚨 Failsafe Auto-Recovery (Slot 1)",
            variable=self.var_failsafe, font=("Segoe UI", 8), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG,
            selectcolor="#11111b", command=self.on_toggle_feature
        ).pack(side="left", padx=16)

        tk.Button(
            container, text="🔄 รีเซ็ตการตั้งค่าทั้งหมดกลับเป็นค่ามาตรฐาน Master Spec",
            font=("Segoe UI", 9, "bold"), bg=ModernColors.BORDER, fg=ModernColors.ACCENT_YELLOW, relief="flat",
            command=self.reset_factory_defaults
        ).pack(fill="x", pady=6)

    def build_tab_logs(self):
        log_frame = tk.Frame(self.tab_logs, bg=ModernColors.CARD_BG, padx=8, pady=6)
        log_frame.pack(fill="both", expand=True, padx=6, pady=4)

        self.log_text = tk.Text(
            log_frame,
            bg="#11111b",
            fg=ModernColors.TEXT_MAIN,
            font=("Consolas", 10),
            relief="flat",
            wrap="word"
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

    def _render_thumb(self, frame, target_w=390, target_h=190):
        if frame is None or frame.size == 0:
            return None
        h, w = frame.shape[:2]
        scale = min(target_w / max(1, w), target_h / max(1, h))
        nw, nh = max(10, int(w * scale)), max(10, int(h * scale))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return ImageTk.PhotoImage(Image.fromarray(rgb))

    def start_live_stream_thread(self):
        def _stream_loop():
            while self.is_live_stream_active:
                try:
                    mode = self.config.get("screen", {}).get("detection_mode", "auto")
                    if mode == "auto":
                        pb_frame = self.bot.detector.capture_auto_cast_area()
                        hold_frame = self.bot.detector.capture_auto_hold_area()
                    else:
                        pb_frame = self.bot.detector.capture_cast_bar()
                        hold_frame = self.bot.detector.capture_hold_text()

                    is_green, pb_details = self.bot.detector.detect_green_peak(pb_frame, force_mode=mode)
                    is_text, hold_details = self.bot.detector.detect_hold_anchor(hold_frame, force_mode=mode)

                    thumb_pb = self._render_thumb(pb_frame, 390, 190)
                    thumb_hold = self._render_thumb(hold_frame, 390, 190)

                    score_pct = int(hold_details.get("match_score", 0.0) * 100)
                    green_pct = int(pb_details.get("green_ratio", 0.0) * 100) if "green_ratio" in pb_details else int(pb_details.get("green_pixels", 0))

                    def _update_ui(g_ok=is_green, t_ok=is_text, p_d=pb_details, h_d=hold_details, t_pb=thumb_pb, t_h=thumb_hold, sc=score_pct, gp=green_pct):
                        if not self.is_live_stream_active:
                            return
                        if t_pb:
                            self.preview_cache["pb"] = t_pb
                            self.img_lbl_pb.config(image=t_pb, text="")
                        txt_pb = f"🟢 โซนเขียว! ({gp}%)" if g_ok else f"⚪ รอชาร์จ... ({gp}%)"
                        self.status_lbl_pb.config(text=f"{txt_pb} [{mode.upper()}]", fg=ModernColors.ACCENT_GREEN if g_ok else ModernColors.TEXT_MUTED)

                        if t_h:
                            self.preview_cache["hold"] = t_h
                            self.img_lbl_hold.config(image=t_h, text="")
                        txt_h = f"🟢 ตรวจพบข้อความ! ({sc}%)" if t_ok else f"⚪ สแกนหาข้อความ... ({sc}%)"
                        self.status_lbl_hold.config(text=f"{txt_h} [{mode.upper()}]", fg=ModernColors.ACCENT_GREEN if t_ok else ModernColors.TEXT_MUTED)

                    self.root.after(0, _update_ui)
                except Exception as e:
                    pass
                time.sleep(0.10)

        self.stream_thread = threading.Thread(target=_stream_loop, daemon=True)
        self.stream_thread.start()

    def update_progress_display(self, percent: float, sub_msg: str):
        def _update():
            self.progress_bar["value"] = percent
            if sub_msg:
                self.activity_var.set(sub_msg)
        self.root.after(0, _update)

    def on_rod_stat_change(self, event=None):
        try:
            d = float(self.depth_entry.get() or 330)
            s = float(self.str_entry.get() or 146)
            calc_sec = round((d / max(1.0, s)) * 1.65 + 0.5, 1)
            calc_sink = round(max(18.0, (d / 12.0) + 5.0), 1)
            self.calc_time_lbl.config(text=f"⚡ ดึงปลา (Reel): {calc_sec}s  |  🌊 จมน้ำสูงสุด (Sinking): {calc_sink}s")
            if "rod_stats" not in self.config:
                self.config["rod_stats"] = {}
            self.config["rod_stats"]["depth"] = d
            self.config["rod_stats"]["strength"] = s
            self.config["timings"]["reel_hold_duration_sec"] = calc_sec
            self.save_config()
        except:
            pass

    def on_gate_slider_change(self, val):
        val_i = int(val)
        self.gate_val_lbl.config(text=f"⚡ หน่วงก่อนสแกนเกจชาร์จ (Min Charge Gate): {val_i} ms")
        self.config["timings"]["min_charge_gate_ms"] = val_i
        self.save_config()

    def on_recast_slider_change(self, val):
        val_f = round(float(val), 1)
        self.recast_val_lbl.config(text=f"⏳ เวลาหน่วงหลังตกเสร็จ (Fast Recast Delay): {val_f:.1f} s (แนะนำ 1.9s)")
        self.config["timings"]["recast_delay_sec"] = val_f
        self.save_config()

    def on_reaction_slider_change(self, val):
        val_i = int(val)
        self.reaction_val_lbl.config(text=f"🐟 เวลาตอบสนองก่อนดึงเบ็ด (Bite Reaction Delay): {val_i} ms")
        self.config["timings"]["bite_reaction_delay_ms"] = val_i
        self.save_config()

    def on_tpl_slider_change(self, val):
        val_i = int(val)
        self.tpl_val_lbl.config(text=f"🎯 ความแม่นยำ Template 'Hold to fish': {val_i}% (แนะนำ 65%)")
        self.config["thresholds"]["hold_template_match_threshold"] = val_i / 100.0
        self.save_config()

    def on_toggle_feature(self):
        if "features" not in self.config:
            self.config["features"] = {}
        self.config["features"]["global_interrupt_enabled"] = self.var_interrupt.get()
        self.config["features"]["double_check_enabled"] = self.var_double_check.get()
        self.config["features"]["pre_cast_validation"] = self.var_pre_cast.get()
        self.config["features"]["lightning_flash_rejection"] = self.var_lightning.get()
        self.config["features"]["failsafe_auto_recovery"] = self.var_failsafe.get()
        self.save_config()

    def reset_factory_defaults(self):
        if messagebox.askyesno("ยืนยัน", "ต้องการรีเซ็ตค่าการตั้งค่าทั้งหมดกลับเป็นค่ามาตรฐาน Master Spec หรือไม่?"):
            self.config["timings"]["idle_delay_sec"] = 0.4
            self.config["timings"]["min_charge_gate_ms"] = 450
            self.config["timings"]["recast_delay_sec"] = 1.9
            self.config["timings"]["bite_reaction_delay_ms"] = 350
            self.config["thresholds"]["hold_template_match_threshold"] = 0.65
            self.config["features"] = {
                "global_interrupt_enabled": True,
                "anti_afk_enabled": True,
                "dynamic_green_detection": True,
                "pre_cast_validation": True,
                "lightning_flash_rejection": True,
                "double_check_enabled": True,
                "failsafe_auto_recovery": True
            }
            self.save_config()
            self.gate_slider.set(450)
            self.recast_slider.set(1.9)
            self.reaction_slider.set(350)
            self.tpl_slider.set(65)
            self.var_interrupt.set(True)
            self.var_double_check.set(True)
            self.var_lightning.set(True)
            self.var_failsafe.set(True)
            messagebox.showinfo("สำเร็จ", "รีเซ็ตค่ามาตรฐาน Master Spec เรียบร้อยแล้ว!")

    def open_template_capture_selector(self):
        self.append_log("📸 เปิดหน้าจอแคปแม่แบบข้อความ 'Hold to fish'...")
        def _on_selected(roi_ratio, crop_bgr):
            if crop_bgr is not None and crop_bgr.size > 0:
                self.bot.detector.save_hold_template(crop_bgr)
                self.append_log("✨ บันทึกไฟล์แม่แบบ template_hold.png สำเร็จและโหลดเข้าสู่ระบบแล้ว!")
                messagebox.showinfo("สำเร็จ", "บันทึกแม่แบบข้อความสำเร็จ! ระบบจะใช้รูปนี้ในการเทียบ Template Matching ทันที")

        FullscreenFrozenSelector(self.root, "ข้อความ 'Hold to fish' เพื่อบันทึกเป็นแม่แบบ Template", mode="box", on_selected=_on_selected)

    def open_roi_selector(self, label, config_key):
        self.append_log(f"🎯 เปิดหน้าจอกำหนดพื้นที่: {label}...")
        def _on_selected(roi_ratio, crop_bgr):
            if "screen" not in self.config:
                self.config["screen"] = {}
            self.config["screen"][config_key] = roi_ratio
            self.config["screen"]["detection_mode"] = "manual"
            self.save_config()
            self.append_log(f"✅ บันทึกพิกัด {config_key} สำเร็จ: {roi_ratio} (สลับเข้าสู่โหมด MANUAL อัตโนมัติ)")

        FullscreenFrozenSelector(self.root, label, mode="box", on_selected=_on_selected)

    def open_point_selector(self):
        self.append_log("🎯 เปิดหน้าจอคลิกเลือกจุด Safe Water Zone...")
        def _on_selected(pt_ratio, crop_bgr):
            if "screen" not in self.config:
                self.config["screen"] = {}
            self.config["screen"]["mouse_target"] = pt_ratio
            self.save_config()
            self.append_log(f"✅ บันทึกพิกัด Safe Zone สำเร็จ: {pt_ratio}")

        FullscreenFrozenSelector(self.root, "Safe Water Zone (จุดผิวน้ำที่ต้องการคลิก)", mode="point", on_selected=_on_selected)

    def setup_hotkeys(self):
        def on_f6():
            self.root.after(0, self.start_bot)

        def on_f7():
            self.root.after(0, self.stop_bot)

        try:
            keyboard.add_hotkey("F6", on_f6)
            keyboard.add_hotkey("F7", on_f7)
            self.append_log("⚡ ลงทะเบียนปุ่มลัด: [F6] เริ่มทำงาน / [F7] หยุดการทำงาน")
        except Exception as e:
            self.append_log(f"⚠️ ไม่สามารถลงทะเบียน Hotkey: {e}")

    def start_bot(self):
        if not self.bot.is_running:
            self.bot.start()
            self.state_var.set("สถานะ: กำลังทำงาน (6-State Master Engine)...")
            self.state_badge.config(fg=ModernColors.ACCENT_GREEN)

    def stop_bot(self):
        if self.bot.is_running:
            self.bot.stop()
            self.state_var.set("สถานะ: STATE 0: IDLE (หยุดพัก)")
            self.state_badge.config(fg=ModernColors.ACCENT_RED)
            self.activity_var.set("หยุดการทำงานเรียบร้อยแล้ว")
            self.progress_bar["value"] = 0

    def append_log(self, message):
        def _append():
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
        self.root.after(0, _append)

    def update_state_display(self, new_state: BotState):
        def _update():
            self.state_var.set(f"สถานะ: {new_state.value}")
        self.root.after(0, _update)

    def update_stats_display(self, stats):
        def _update():
            self.lbl_casts.config(text=f"🎣 เหวี่ยงเบ็ด: {stats['casts_count']} ครั้ง")
            self.lbl_fish.config(text=f"🐟 ปลาที่ได้: {stats['fish_caught']} ตัว")
            self.lbl_perfect.config(text=f"✨ Perfect: {stats['perfect_casts']} ครั้ง")
            self.lbl_modals.config(text=f"🚨 ปิดป๊อปอัปปลาหายาก: {stats.get('modals_cleared', 0)} ครั้ง")
        self.root.after(0, _update)

    def start_uptime_timer(self):
        def _tick():
            if self.bot.is_running and self.bot.stats["start_time"]:
                elapsed = int(time.time() - self.bot.stats["start_time"])
                hrs = elapsed // 3600
                mins = (elapsed % 3600) // 60
                secs = elapsed % 60
                self.lbl_uptime.config(text=f"⏱️ เวลาทำงาน: {hrs:02d}:{mins:02d}:{secs:02d}")
            self.root.after(1000, _tick)
        self.root.after(1000, _tick)

    def on_close(self):
        self.is_live_stream_active = False
        self.stop_bot()
        try:
            keyboard.unhook_all_hotkeys()
        except:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = FishingBotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
