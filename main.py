"""
Main GUI Application for Scale Slimy Fish Auto Fishing Bot.
Features:
- Enlarged High-Resolution Preview Monitors (340x130px)
- Real-Time Live Activity Banner & Progress Bar (Sub-second status tracking)
- Telemetry Live Logs with Exact Metrics & Milestones
- Dynamic Rod Calculator (Depth & Strength -> Auto Reel Duration)
- Dedicated Reeling Hold Duration (Eliminated Premature Release Desync)
- Pre-Cast State Validation & Inventory Full Detection
- Template Matching Text Detection Engine (Zero False Positives)
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
    """Visual overlay displaying a frozen screenshot for high-precision selection."""
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
        self.root.title("Scale Slimy Fish — Telemetry Dashboard & Auto Bot")
        self.root.geometry("800x1060")
        self.root.minsize(760, 920)
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
        # ----------------------------------------------------
        # 1. HEADER CARD
        # ----------------------------------------------------
        header = tk.Frame(self.root, bg=ModernColors.CARD_BG, padx=16, pady=8)
        header.pack(fill="x", padx=16, pady=(10, 3))

        title_lbl = tk.Label(
            header,
            text="🎣 SCALE SLIMY FISH — TELEMETRY & AUTO BOT",
            font=("Segoe UI", 15, "bold"),
            fg=ModernColors.ACCENT_BLUE,
            bg=ModernColors.CARD_BG
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            header,
            text="Real-Time Telemetry Dashboard | 1.8s Fast Recast | Template Matching | Enlarge Live Vision",
            font=("Segoe UI", 9),
            fg=ModernColors.TEXT_MUTED,
            bg=ModernColors.CARD_BG
        )
        sub_lbl.pack(anchor="w")

        # ----------------------------------------------------
        # 2. LIVE ACTIVITY & STATE BANNER
        # ----------------------------------------------------
        banner_frame = tk.Frame(self.root, bg=ModernColors.CARD_BG, padx=14, pady=6, relief="solid", bd=1)
        banner_frame.pack(fill="x", padx=16, pady=2)

        self.state_var = tk.StringVar(value="สถานะ: STATE 0: IDLE (หยุดพัก)")
        self.state_badge = tk.Label(
            banner_frame,
            textvariable=self.state_var,
            font=("Segoe UI", 12, "bold"),
            fg=ModernColors.ACCENT_YELLOW,
            bg=ModernColors.CARD_BG
        )
        self.state_badge.pack(anchor="w")

        # Real-time Activity Message Label
        self.activity_var = tk.StringVar(value="พร้อมทำงาน (กด F6 เพื่อเริ่มต้น)")
        self.activity_lbl = tk.Label(
            banner_frame,
            textvariable=self.activity_var,
            font=("Segoe UI", 9, "italic"),
            fg=ModernColors.TEXT_MAIN,
            bg=ModernColors.CARD_BG
        )
        self.activity_lbl.pack(anchor="w", pady=(1, 4))

        # Real-time Visual Progress Bar
        style = ttk.Style()
        style.theme_use('default')
        style.configure("Custom.Horizontal.TProgressbar", troughcolor=ModernColors.BORDER, background=ModernColors.ACCENT_BLUE, thickness=8)

        self.progress_bar = ttk.Progressbar(
            banner_frame,
            style="Custom.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
            maximum=100.0
        )
        self.progress_bar.pack(fill="x")

        # ----------------------------------------------------
        # 3. STATS DASHBOARD
        # ----------------------------------------------------
        stats_frame = tk.Frame(self.root, bg=ModernColors.CARD_BG, padx=12, pady=5)
        stats_frame.pack(fill="x", padx=16, pady=2)

        self.lbl_casts = tk.Label(stats_frame, text="🎣 เหวี่ยงเบ็ด: 0 ครั้ง", font=("Segoe UI", 10, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG)
        self.lbl_casts.grid(row=0, column=0, sticky="w", padx=10, pady=1)

        self.lbl_fish = tk.Label(stats_frame, text="🐟 ปลาที่ได้: 0 ตัว", font=("Segoe UI", 10, "bold"), fg=ModernColors.ACCENT_GREEN, bg=ModernColors.CARD_BG)
        self.lbl_fish.grid(row=0, column=1, sticky="w", padx=10, pady=1)

        self.lbl_perfect = tk.Label(stats_frame, text="✨ Perfect: 0 ครั้ง", font=("Segoe UI", 10, "bold"), fg=ModernColors.ACCENT_YELLOW, bg=ModernColors.CARD_BG)
        self.lbl_perfect.grid(row=1, column=0, sticky="w", padx=10, pady=1)

        self.lbl_uptime = tk.Label(stats_frame, text="⏱️ เวลาทำงาน: 00:00:00", font=("Segoe UI", 10), fg=ModernColors.TEXT_MUTED, bg=ModernColors.CARD_BG)
        self.lbl_uptime.grid(row=1, column=1, sticky="w", padx=10, pady=1)

        # Main Control Buttons
        btn_frame = tk.Frame(self.root, bg=ModernColors.BG_DARK)
        btn_frame.pack(fill="x", padx=16, pady=3)

        self.btn_start = tk.Button(
            btn_frame,
            text="▶ เริ่มต้นทำงาน (F6)",
            font=("Segoe UI", 11, "bold"),
            bg="#238636",
            fg="white",
            activebackground="#2ea043",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            command=self.start_bot
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_stop = tk.Button(
            btn_frame,
            text="⏹ หยุดชั่วคราว (F7)",
            font=("Segoe UI", 11, "bold"),
            bg="#da3633",
            fg="white",
            activebackground="#f85149",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            command=self.stop_bot
        )
        self.btn_stop.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # ----------------------------------------------------
        # 4. ENLARGED DUAL LIVE CAMERA CARDS (340x130px)
        # ----------------------------------------------------
        calib_container = tk.Frame(self.root, bg=ModernColors.BG_DARK)
        calib_container.pack(fill="x", padx=16, pady=2)

        # CARD 1: Power Bar (Enlarged)
        c1 = tk.LabelFrame(
            calib_container,
            text=" 1. แถบเกจพลัง (Power Bar Monitor - State 1) ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_GREEN,
            bg=ModernColors.CARD_BG,
            padx=6,
            pady=4
        )
        c1.pack(side="left", fill="both", expand=True, padx=(0, 3))

        self.img_lbl_pb = tk.Label(c1, text="[กำลังเชื่อมต่อกล้อง...]", fg=ModernColors.TEXT_MUTED, bg=ModernColors.PREVIEW_BG, height=7)
        self.img_lbl_pb.pack(fill="both", expand=True, pady=2)

        self.status_lbl_pb = tk.Label(c1, text="⚪ สตรีมสด...", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MUTED, bg=ModernColors.CARD_BG)
        self.status_lbl_pb.pack()

        tk.Button(
            c1, text="🎯 ลากเลือกพื้นที่เกจ (Manual)", font=("Segoe UI", 8, "bold"),
            bg=ModernColors.BORDER, fg=ModernColors.ACCENT_GREEN, relief="flat",
            command=lambda: self.open_roi_selector("Power Bar (แถบเกจพลังทางขวา)", "cast_bar_roi")
        ).pack(fill="x", pady=1)

        # CARD 2: Hold to fish (Enlarged)
        c2 = tk.LabelFrame(
            calib_container,
            text=" 2. ข้อความดึงเบ็ด (Template Matching - State 2/3) ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_YELLOW,
            bg=ModernColors.CARD_BG,
            padx=6,
            pady=4
        )
        c2.pack(side="left", fill="both", expand=True, padx=(3, 0))

        self.img_lbl_hold = tk.Label(c2, text="[กำลังเชื่อมต่อกล้อง...]", fg=ModernColors.TEXT_MUTED, bg=ModernColors.PREVIEW_BG, height=7)
        self.img_lbl_hold.pack(fill="both", expand=True, pady=2)

        self.status_lbl_hold = tk.Label(c2, text="⚪ สตรีมสด...", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MUTED, bg=ModernColors.CARD_BG)
        self.status_lbl_hold.pack()

        c2_btns = tk.Frame(c2, bg=ModernColors.CARD_BG)
        c2_btns.pack(fill="x", pady=1)

        tk.Button(
            c2_btns, text="📸 แคป Template ข้อความ", font=("Segoe UI", 8, "bold"),
            bg="#238636", fg="white", relief="flat",
            command=self.open_template_capture_selector
        ).pack(side="left", fill="x", expand=True, padx=(0, 2))

        tk.Button(
            c2_btns, text="🎯 ลากกรอบ Hold", font=("Segoe UI", 8),
            bg=ModernColors.BORDER, fg=ModernColors.ACCENT_YELLOW, relief="flat",
            command=lambda: self.open_roi_selector("Hold to fish (ข้อความกึ่งกลางจอ)", "hold_roi")
        ).pack(side="right", fill="x", expand=True, padx=(2, 0))

        # ----------------------------------------------------
        # 5. DYNAMIC ROD CALCULATOR & SAFE ZONE
        # ----------------------------------------------------
        rod_card = tk.LabelFrame(
            self.root,
            text=" 🎣 คำนวณเวลาดึงปลาตามสเปกคันเบ็ด (Dynamic Rod Stats) & Safe Zone ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_PURPLE,
            bg=ModernColors.CARD_BG,
            padx=10,
            pady=4
        )
        rod_card.pack(fill="x", padx=16, pady=2)

        rod_row = tk.Frame(rod_card, bg=ModernColors.CARD_BG)
        rod_row.pack(fill="x", pady=1)

        # Depth Input
        tk.Label(rod_row, text="Depth (m):", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG).pack(side="left", padx=(0, 2))
        self.depth_entry = tk.Entry(rod_row, width=6, bg="#11111b", fg=ModernColors.ACCENT_YELLOW, insertbackground="white", font=("Segoe UI", 9, "bold"))
        current_depth = self.config.get("rod_stats", {}).get("depth", 280)
        self.depth_entry.insert(0, str(current_depth))
        self.depth_entry.pack(side="left", padx=(0, 8))
        self.depth_entry.bind("<KeyRelease>", self.on_rod_stat_change)

        # Strength Input
        tk.Label(rod_row, text="Strength:", font=("Segoe UI", 8, "bold"), fg=ModernColors.TEXT_MAIN, bg=ModernColors.CARD_BG).pack(side="left", padx=(0, 2))
        self.str_entry = tk.Entry(rod_row, width=6, bg="#11111b", fg=ModernColors.ACCENT_GREEN, insertbackground="white", font=("Segoe UI", 9, "bold"))
        current_str = self.config.get("rod_stats", {}).get("strength", 90)
        self.str_entry.insert(0, str(current_str))
        self.str_entry.pack(side="left", padx=(0, 8))
        self.str_entry.bind("<KeyRelease>", self.on_rod_stat_change)

        # Calculated Time Label
        calc_sec = round((float(current_depth) / max(1.0, float(current_str))) * 1.65 + 0.5, 1)
        self.calc_time_lbl = tk.Label(rod_row, text=f"⚡ เวลาดึงปลา: {calc_sec}s (คำนวณอัตโนมัติ)", font=("Segoe UI", 8, "bold"), fg=ModernColors.ACCENT_BLUE, bg=ModernColors.CARD_BG)
        self.calc_time_lbl.pack(side="left", padx=4)

        # Safe Zone Buttons
        tk.Button(
            rod_row, text="🎯 คลิกเลือก Safe Zone", font=("Segoe UI", 8, "bold"),
            bg=ModernColors.BORDER, fg=ModernColors.ACCENT_PURPLE, relief="flat",
            command=self.open_point_selector
        ).pack(side="right", padx=2)

        # ----------------------------------------------------
        # 6. TIMING & SENSITIVITY SETTINGS
        # ----------------------------------------------------
        timing_card = tk.LabelFrame(
            self.root,
            text=" ⏱️ ปรับแต่งความเร็วรอบและเกณฑ์การตรวจจับ (Pacing Controls) ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.ACCENT_PURPLE,
            bg=ModernColors.CARD_BG,
            padx=10,
            pady=3
        )
        timing_card.pack(fill="x", padx=16, pady=2)

        # Slider 1: Fast Recast Delay (Streamlined to 1.8s)
        recast_row = tk.Frame(timing_card, bg=ModernColors.CARD_BG)
        recast_row.pack(fill="x", pady=1)

        current_recast = self.config.get("timings", {}).get("recast_delay_sec", 1.8)
        self.recast_val_lbl = tk.Label(recast_row, text=f"⏳ เวลาหน่วงหลังตกเสร็จ (Fast Recast Delay): {current_recast:.1f}s (แนะนำ 1.8s)", font=("Segoe UI", 8, "bold"), fg=ModernColors.ACCENT_GREEN, bg=ModernColors.CARD_BG)
        self.recast_val_lbl.pack(anchor="w")

        self.recast_slider = tk.Scale(
            recast_row,
            from_=1.2,
            to=3.5,
            orient="horizontal",
            resolution=0.1,
            showvalue=False,
            bg=ModernColors.CARD_BG,
            fg=ModernColors.TEXT_MAIN,
            troughcolor=ModernColors.BORDER,
            highlightthickness=0,
            command=self.on_recast_slider_change
        )
        self.recast_slider.set(current_recast)
        self.recast_slider.pack(fill="x")

        # Slider 2: Template Match Threshold
        tpl_row = tk.Frame(timing_card, bg=ModernColors.CARD_BG)
        tpl_row.pack(fill="x", pady=1)

        current_tpl_score = int(self.config.get("thresholds", {}).get("hold_template_match_threshold", 0.65) * 100)
        self.tpl_val_lbl = tk.Label(tpl_row, text=f"🎯 ความแม่นยำจับคู่ Template (Match Score): {current_tpl_score}% (ค่าแนะนำ 60-70%)", font=("Segoe UI", 8, "bold"), fg=ModernColors.ACCENT_YELLOW, bg=ModernColors.CARD_BG)
        self.tpl_val_lbl.pack(anchor="w")

        self.tpl_slider = tk.Scale(
            tpl_row,
            from_=40,
            to=90,
            orient="horizontal",
            resolution=1,
            showvalue=False,
            bg=ModernColors.CARD_BG,
            fg=ModernColors.TEXT_MAIN,
            troughcolor=ModernColors.BORDER,
            highlightthickness=0,
            command=self.on_tpl_slider_change
        )
        self.tpl_slider.set(current_tpl_score)
        self.tpl_slider.pack(fill="x")

        # ----------------------------------------------------
        # 7. TELEMETRY LIVE LOGS
        # ----------------------------------------------------
        log_frame = tk.LabelFrame(
            self.root,
            text=" 📋 บันทึกการทำงานตามจริง (Telemetry Live Logs) ",
            font=("Segoe UI", 9, "bold"),
            fg=ModernColors.TEXT_MUTED,
            bg=ModernColors.CARD_BG,
            padx=8,
            pady=2
        )
        log_frame.pack(fill="both", expand=True, padx=16, pady=(2, 8))

        self.log_text = tk.Text(
            log_frame,
            bg="#11111b",
            fg=ModernColors.TEXT_MAIN,
            font=("Consolas", 9),
            relief="flat",
            wrap="word"
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

    def _render_thumb(self, frame, target_w=340, target_h=130):
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
                    is_text, hold_details = self.bot.detector.detect_hold_text(hold_frame, force_mode=mode)

                    thumb_pb = self._render_thumb(pb_frame, 340, 130)
                    thumb_hold = self._render_thumb(hold_frame, 340, 130)

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
            d = float(self.depth_entry.get() or 280)
            s = float(self.str_entry.get() or 90)
            calc_sec = round((d / max(1.0, s)) * 1.65 + 0.5, 1)
            self.calc_time_lbl.config(text=f"⚡ เวลาดึงปลา: {calc_sec}s (คำนวณอัตโนมัติ)")
            if "rod_stats" not in self.config:
                self.config["rod_stats"] = {}
            self.config["rod_stats"]["depth"] = d
            self.config["rod_stats"]["strength"] = s
            self.config["timings"]["reel_hold_duration_sec"] = calc_sec
            self.save_config()
        except:
            pass

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

    def on_recast_slider_change(self, val):
        val_f = round(float(val), 1)
        self.recast_val_lbl.config(text=f"⏳ เวลาหน่วงหลังตกเสร็จ (Fast Recast Delay): {val_f:.1f}s (แนะนำ 1.8s)")
        if "timings" not in self.config:
            self.config["timings"] = {}
        self.config["timings"]["recast_delay_sec"] = val_f
        self.save_config()

    def on_tpl_slider_change(self, val):
        val_i = int(val)
        self.tpl_val_lbl.config(text=f"🎯 ความแม่นยำจับคู่ Template (Match Score): {val_i}% (ค่าแนะนำ 60-70%)")
        if "thresholds" not in self.config:
            self.config["thresholds"] = {}
        self.config["thresholds"]["hold_template_match_threshold"] = val_i / 100.0
        self.save_config()

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
            self.state_var.set("สถานะ: กำลังทำงาน (5-State Engine Active)...")
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
