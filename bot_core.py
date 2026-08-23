"""
Bot Core Engine for Scale Slimy Fish Auto Fishing Bot.
Implements the 6-State FSM Architecture with Interrupt Layer:
1. Global Interrupt Layer:
   - Click to Continue Modal Handler (Legendary / New Fish Unlock)
   - Inventory Full Warning Detector (Auto-Pause Bot to prevent wasted casts)
2. Precision Casting: Uninterrupted MouseDown charge to green peak
3. Dual-Anchor Sinking: Template Match + Red '!' Icon
4. High-Precision Cancel Button Validation in State 3
5. Zero-Drift Micro-Jitter 120ms
6. State 4 Click-to-Dismiss fast reset (1.9s)
"""

import sys
import os
import time
import threading
import json
import ctypes
import traceback
from enum import Enum
from vision import VisionDetector

# Set DPI awareness and 1ms high-resolution timer
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001
KEYEVENTF_KEYUP = 0x0002
VK_KEY_1 = 0x31

user32 = ctypes.windll.user32


class BotState(Enum):
    IDLE = "STATE 0: IDLE / READY (สแตนด์บาย Safe Zone 0.4s)"
    CASTING = "STATE 1: CASTING (ชาร์จเกจ 450ms+ -> ดับเบิ้ลเช็คโซนเขียว)"
    SINKING = "STATE 2: SINKING (เบ็ดจมน้ำ 18.0s+ & Dual-Anchor '!'/Hold)"
    REELING = "STATE 3: REELING (กดค้างดึงปลา + Micro-Jitter 120ms & Extension)"
    LOOT_RESET = "STATE 4: LOOT & RESET (คลิกข้ามการ์ด & วนรอบ 1.9s)"
    PAUSED_INVENTORY_FULL = "🚨 PAUSED: กระเป๋าปลาเต็ม (Inventory Full)!"


class InputSimulator:
    @staticmethod
    def get_safe_coords(config=None):
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        target = config.get("screen", {}).get("mouse_target", {"x_ratio": 0.50, "y_ratio": 0.38}) if config else {"x_ratio": 0.50, "y_ratio": 0.38}
        cx = int(sw * target.get("x_ratio", 0.50))
        cy = int(sh * target.get("y_ratio", 0.38))
        return cx, cy

    @staticmethod
    def move_to_safe_water_zone(config=None):
        cx, cy = InputSimulator.get_safe_coords(config)
        user32.SetCursorPos(cx, cy)
        time.sleep(0.04)

    @staticmethod
    def mouse_down():
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    @staticmethod
    def mouse_up():
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    @staticmethod
    def click(duration=0.04):
        InputSimulator.mouse_down()
        time.sleep(duration)
        InputSimulator.mouse_up()

    @staticmethod
    def send_micro_jitter():
        user32.mouse_event(MOUSEEVENTF_MOVE, 1, 0, 0, 0)
        time.sleep(0.004)
        user32.mouse_event(MOUSEEVENTF_MOVE, -1, 0, 0, 0)

    @staticmethod
    def press_key_1():
        user32.keybd_event(VK_KEY_1, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_KEY_1, 0, KEYEVENTF_KEYUP, 0)

    @staticmethod
    def micro_anti_afk():
        user32.mouse_event(MOUSEEVENTF_MOVE, 2, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(MOUSEEVENTF_MOVE, -2, 0, 0, 0)

    @staticmethod
    def click_cancel_button(config=None):
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        cancel_roi = config.get("screen", {}).get("cancel_btn_roi", {
            "x_ratio": 0.42,
            "y_ratio": 0.83,
            "w_ratio": 0.16,
            "h_ratio": 0.11
        }) if config else {"x_ratio": 0.42, "y_ratio": 0.83, "w_ratio": 0.16, "h_ratio": 0.11}
        
        cx = int(sw * (cancel_roi.get("x_ratio", 0.42) + cancel_roi.get("w_ratio", 0.16) / 2.0))
        cy = int(sh * (cancel_roi.get("y_ratio", 0.83) + cancel_roi.get("h_ratio", 0.11) / 2.0))
        user32.SetCursorPos(cx, cy)
        time.sleep(0.06)
        InputSimulator.click(0.04)
        time.sleep(0.15)
        InputSimulator.move_to_safe_water_zone(config)


class FishingBot:
    def __init__(self, config_path="config.json", log_callback=None, state_callback=None, stats_callback=None, progress_callback=None, overlay_callback=None):
        self.config_path = config_path
        self.log_callback = log_callback
        self.state_callback = state_callback
        self.stats_callback = stats_callback
        self.progress_callback = progress_callback
        self.overlay_callback = overlay_callback

        self.detector = VisionDetector(config_path=config_path)
        self.config = self.detector.config

        self.state = BotState.IDLE
        self.is_running = False
        self.worker_thread = None

        self.stats = {
            "casts_count": 0,
            "fish_caught": 0,
            "perfect_casts": 0,
            "modals_cleared": 0,
            "start_time": None,
            "uptime_seconds": 0
        }

        self.consecutive_sinking_timeouts = 0
        self.last_anti_afk_time = time.time()
        self.last_progress_time = 0.0

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        if self.log_callback:
            self.log_callback(formatted)
        else:
            try:
                print(formatted)
            except Exception:
                pass

    def set_state(self, new_state: BotState):
        self.state = new_state
        if self.state_callback:
            self.state_callback(new_state)

    def set_overlay(self, roi_dict=None, color="#50fa7b", label=""):
        if self.overlay_callback:
            try:
                self.overlay_callback(roi_dict, color, label)
            except Exception:
                pass

    def set_progress(self, percent: float, sub_msg: str = "", force: bool = False):
        now = time.perf_counter()
        if force or percent >= 100.0 or percent <= 0.0 or (now - self.last_progress_time) >= 0.040:
            self.last_progress_time = now
            if self.progress_callback:
                self.progress_callback(percent, sub_msg)

    def update_stats(self):
        if self.stats["start_time"]:
            self.stats["uptime_seconds"] = int(time.time() - self.stats["start_time"])
        if self.stats_callback:
            self.stats_callback(self.stats)

    def check_global_interrupt(self):
        features = self.config.get("features", {})

        # 1. Click to Continue (New / Legendary Fish Unlock)
        if features.get("global_interrupt_enabled", True):
            if self.detector.is_click_to_continue_present():
                self.log("⚡ [Global Interrupt] ตรวจพบ 'Click to Continue' (ปลาใหม่/หายาก) -> ส่งคลิกเคลียร์หน้าต่างทันที")
                InputSimulator.move_to_safe_water_zone(self.config)
                InputSimulator.click(0.04)
                time.sleep(0.5)
                self.stats["modals_cleared"] += 1
                self.update_stats()
                return True

        # 2. Inventory Full Detection (Pause Bot)
        if features.get("inventory_full_detection", True):
            if self.detector.is_inventory_full():
                self.log("🚨 [Inventory Full] ตรวจพบกระเป๋าปลาเต็ม! หยุดการทำงานชั่วคราวเพื่อป้องกันการเหวี่ยงฟรี")
                self.set_state(BotState.PAUSED_INVENTORY_FULL)
                self.set_progress(0, "🚨 หยุดชั่วคราว: กระเป๋าปลาเต็ม (กรุณาเทกระเป๋า)")
                self.stop(reason="INVENTORY_FULL")
                return True

        return False

    def calculate_reel_duration(self):
        override = self.config.get("timings", {}).get("reel_hold_duration_sec", None)
        if override is not None:
            return max(0.5, float(override))
        rod = self.config.get("rod_stats", {"depth": 330, "strength": 146})
        depth = float(rod.get("depth", 330))
        strength = max(1.0, float(rod.get("strength", 146)))
        calc_duration = round((depth / strength) * 1.65 + 0.5, 1)
        return max(0.5, calc_duration)

    def calculate_sinking_timeout(self):
        base_timeout = float(self.config.get("timings", {}).get("sinking_timeout_sec", 18.0) or 18.0)
        return round(base_timeout, 1)

    def reload_config(self):
        self.detector.config = self.detector.load_config()
        self.config = self.detector.config
        mode = self.config.get("screen", {}).get("detection_mode", "auto").upper()
        self.log(f"🔄 อัปเดตการตั้งค่า Config เรียบร้อยแล้ว (โหมด: {mode})")

    def start(self):
        if self.is_running:
            return

        self.reload_config()
        self.is_running = True
        self.consecutive_sinking_timeouts = 0
        self.stats["start_time"] = time.time()
        self.last_anti_afk_time = time.time()

        self.worker_thread = threading.Thread(target=self._bot_loop, daemon=True)
        self.worker_thread.start()
        mode = self.config.get("screen", {}).get("detection_mode", "auto").upper()
        self.log(f"🚀 บอทเริ่มทำงาน (Modal Handler & Inventory Full Check | โหมด: {mode})")

    def stop(self, reason=None):
        if not self.is_running:
            return

        self.is_running = False
        self.set_overlay(None)
        InputSimulator.mouse_up()
        if reason == "INVENTORY_FULL":
            self.set_state(BotState.PAUSED_INVENTORY_FULL)
        else:
            self.set_state(BotState.IDLE)
            self.set_progress(0, "ระบบหยุดการทำงาน")
            self.log("⏹️ บอทหยุดการทำงาน (Stopped)")

    def _perform_failsafe_recovery(self):
        self.log("🚨 [Failsafe Auto-Recovery] เกิด Timeout ติดต่อกัน 2 ครั้ง -> รีเซ็ตคันเบ็ด (Unequip/Re-equip Slot 1)...")
        self.set_progress(100.0, "🚨 Failsafe: กำลังรีเซ็ตคันเบ็ด Slot 1...")
        InputSimulator.move_to_safe_water_zone(self.config)
        InputSimulator.click(0.04)
        time.sleep(0.5)
        InputSimulator.press_key_1()
        time.sleep(1.0)
        InputSimulator.press_key_1()
        time.sleep(1.5)
        self.consecutive_sinking_timeouts = 0
        self.log("✅ [Failsafe Recovery] รีเซ็ตคันเบ็ดเรียบร้อยแล้ว พร้อมเริ่มรอบใหม่")

    def _execute_casting_state(self):
        timings = self.config.get("timings", {})
        features = self.config.get("features", {})
        min_gate = (timings.get("min_charge_gate_ms", 450) or 450) / 1000.0
        backup_timeout = timings.get("charge_backup_sec", 1.4)
        poll_interval = timings.get("cast_poll_interval_sec", 0.005)
        settle_delay = timings.get("cast_settle_delay_sec", 1.0)
        double_check = features.get("double_check_enabled", True)

        # 1. ย้ายเคอร์เซอร์ไป Safe Water Zone (50%, 38%)
        InputSimulator.move_to_safe_water_zone(self.config)

        # 2. เริ่มกดค้างเพื่อชาร์จเกจ (Uninterrupted Charge)
        InputSimulator.mouse_down()
        start_ts = time.perf_counter()
        vision_success = False
        last_green_ratio = 0.0

        # 3. High-Frequency Polling Loop with Min Gate
        while (time.perf_counter() - start_ts) < backup_timeout:
            if not self.is_running:
                break
            
            elapsed = time.perf_counter() - start_ts
            pct = min(100.0, (elapsed / backup_timeout) * 100.0)
            self.set_progress(pct, f"กำลังชาร์จเกจพลังงาน: {int(elapsed*1000)}ms / {int(backup_timeout*1000)}ms")

            if elapsed >= min_gate:
                is_green, details = self.detector.detect_green_peak()
                last_green_ratio = details.get("green_ratio", 0.0)
                if is_green:
                    if double_check:
                        time.sleep(0.003)
                        is_green_2, details_2 = self.detector.detect_green_peak()
                        if is_green_2:
                            vision_success = True
                            last_green_ratio = details_2.get("green_ratio", last_green_ratio)
                            break
                    else:
                        vision_success = True
                        break

            time.sleep(poll_interval)

        # 4. ปล่อยเมาส์ทันทีเพื่อล็อก Perfect !
        InputSimulator.mouse_up()
        cast_time_ms = int((time.perf_counter() - start_ts) * 1000)

        if vision_success:
            self.stats["perfect_casts"] += 1
            self.update_stats()
            self.log(f"✨ [State 1: Cast] ตรวจพบสีเขียว ({int(last_green_ratio*100)}%) ที่ {cast_time_ms}ms -> ปล่อยเมาส์ทันที (Perfect !)")
        else:
            self.log(f"⚡ [State 1: Cast] ชาร์จครบกำหนด {cast_time_ms}ms -> ปล่อยเมาส์ตาม Safety Backup")

        # 5. รอทุ่นลอยตกน้ำ
        self.set_progress(100.0, "รอทุ่นลอยตกกระทบผิวน้ำ...")
        time.sleep(settle_delay)
        return vision_success

    def _bot_loop(self):
        timings = self.config.get("timings", {})
        features = self.config.get("features", {})

        idle_delay = timings.get("idle_delay_sec", 0.4)
        reaction_delay = (timings.get("bite_reaction_delay_ms", 350) or 350) / 1000.0
        recast_delay = timings.get("recast_delay_sec", 1.9)
        jitter_interval = (timings.get("jitter_interval_ms", 120) or 120) / 1000.0
        scan_interval = timings.get("scan_interval_sec", 0.025)
        anti_afk_interval = timings.get("anti_afk_interval_sec", 120.0)
        cancel_extension_max = timings.get("reeling_cancel_extension_sec", 2.5)
        double_check = features.get("double_check_enabled", True)

        try:
            # 🎯 Initial Focus: Move to Safe Zone and Left-Click 1 time to focus game window
            self.log("🎯 [Initial Focus] เลื่อนเมาส์ไปยัง Safe Water Zone และคลิกซ้าย 1 ครั้งเพื่อโฟกัสหน้าต่างเกมก่อนเริ่ม...")
            self.set_progress(0, "กำลังโฟกัสหน้าต่างเกม (Safe Zone 50%, 38%)...")
            InputSimulator.move_to_safe_water_zone(self.config)
            time.sleep(0.1)
            InputSimulator.click(0.04)
            time.sleep(0.4)

            while self.is_running:
                # 0. Global Pre-Check (Click to Continue & Inventory Full)
                if self.check_global_interrupt():
                    if not self.is_running:
                        break

                # Anti-AFK Check
                if features.get("anti_afk_enabled", True):
                    if time.time() - self.last_anti_afk_time > anti_afk_interval:
                        InputSimulator.micro_anti_afk()
                        self.last_anti_afk_time = time.time()
                        self.log("🛡️ Anti-AFK ทำงาน (ป้องกัน Roblox Kick)")

                # ====================================================
                # STATE 0: IDLE / READY (0.4s Fast Standby)
                # ====================================================
                self.set_state(BotState.IDLE)
                self.set_overlay(None)
                self.set_progress(0, "เตรียมความพร้อมตัวละคร (Safe Water Zone 50%, 38%)...")
                InputSimulator.move_to_safe_water_zone(self.config)
                time.sleep(idle_delay)

                # Check Interrupt before Cast
                if self.check_global_interrupt():
                    if not self.is_running:
                        break

                # ====================================================
                # STATE 1: CASTING (Sub-ROI 15% + 450ms Min Gate)
                # ====================================================
                self.set_state(BotState.CASTING)
                mode = self.config.get("screen", {}).get("detection_mode", "auto")
                cast_roi = self.config.get("screen", {}).get("auto_cast_search_roi" if mode == "auto" else "cast_bar_roi")
                self.set_overlay(cast_roi, "#50fa7b", "🎣 สแกนเกจ Power Bar (State 1)")
                self.log("🎣 [State 1: Casting] ส่ง MouseDown ชาร์จเกจพลังงาน (Min Gate 450ms)...")
                self.stats["casts_count"] += 1
                is_perfect = self._execute_casting_state()

                # ====================================================
                # STATE 2: SINKING (Dual Anchor '!'/Hold | Dynamic Timeout)
                # ====================================================
                self.set_state(BotState.SINKING)
                hold_roi = self.config.get("screen", {}).get("auto_hold_search_roi" if mode == "auto" else "hold_roi")
                self.set_overlay(hold_roi, "#f1fa8c", "🌊 สแกน Hold to fish / ! (State 2)")

                # Pre-validation: Check if Power Bar is still on screen (Cast Failed -> Loop back to State 1)
                time.sleep(0.2)
                if self.detector.is_power_bar_present():
                    self.log("⚠️ [State 2 Validation] ตรวจพบ Power Bar ยังอยู่บนหน้าจอ (การเหวี่ยงเบ็ดไม่สำเร็จ) -> ส่ง MouseUp เคลียร์สถานะ และวนกลับไปเหวี่ยงเบ็ด State 1 ทันที")
                    InputSimulator.mouse_up()
                    if self.stats["casts_count"] > 0:
                        self.stats["casts_count"] -= 1
                    if is_perfect and self.stats["perfect_casts"] > 0:
                        self.stats["perfect_casts"] -= 1
                    self.update_stats()
                    time.sleep(0.4)
                    continue

                sinking_timeout = self.calculate_sinking_timeout()
                depth_val = self.config.get("rod_stats", {}).get("depth", 330)
                self.log(f"🌊 [State 2: Sinking] สายเบ็ดกำลังจมลงสู่ใต้ทะเล (Depth: {depth_val}m | Timeout: {sinking_timeout}s)...")
                
                start_sink = time.time()
                last_interrupt_check = 0.0
                hooked = False
                cast_failed = False
                last_score = 0.0

                while time.time() - start_sink < sinking_timeout:
                    if not self.is_running:
                        break

                    elapsed_sink = time.time() - start_sink

                    # Early Sinking Validation: Check if Power Bar is still stuck on screen
                    if elapsed_sink <= 1.5 and self.detector.is_power_bar_present():
                        self.log("⚠️ [State 2 Validation] ตรวจพบ Power Bar ยังคงค้างอยู่ -> ส่ง MouseUp และวนกลับไปเหวี่ยงเบ็ด State 1 ทันที")
                        InputSimulator.mouse_up()
                        if self.stats["casts_count"] > 0:
                            self.stats["casts_count"] -= 1
                        if is_perfect and self.stats["perfect_casts"] > 0:
                            self.stats["perfect_casts"] -= 1
                        self.update_stats()
                        time.sleep(0.4)
                        cast_failed = True
                        break

                    # Check Global Interrupt periodically (every 1.5s) to maximize loop FPS
                    now_ts = time.time()
                    if now_ts - last_interrupt_check > 1.5:
                        last_interrupt_check = now_ts
                        if self.check_global_interrupt():
                            if not self.is_running:
                                break

                    sink_pct = min(100.0, (elapsed_sink / sinking_timeout) * 100.0)
                    
                    is_detected, details = self.detector.detect_hold_anchor()
                    last_score = details.get("match_score", 0.0)
                    has_excl = details.get("has_exclamation", False)
                    
                    anchor_text = "ปลาติดเบ็ด (!)" if has_excl else f"Match: {int(last_score*100)}%"
                    self.set_progress(sink_pct, f"สายเบ็ดกำลังจมน้ำ (Depth: {depth_val}m)... ({elapsed_sink:.1f}s / {sinking_timeout:.1f}s) | {anchor_text}")

                    if is_detected:
                        if double_check:
                            time.sleep(0.025)
                            is_det_2, details_2 = self.detector.detect_hold_anchor()
                            if is_det_2:
                                hooked = True
                                last_score = details_2.get("match_score", last_score)
                                break
                        else:
                            hooked = True
                            break
                    time.sleep(scan_interval)

                if not self.is_running:
                    break

                if cast_failed:
                    continue

                if not hooked:
                    self.consecutive_sinking_timeouts += 1
                    self.log(f"⚠️ [State 2 Timeout #{self.consecutive_sinking_timeouts}] ครบ {sinking_timeout}s ไม่พบปลาติดเบ็ด -> ส่งคลิกตัดสาย 1 ครั้ง")
                    InputSimulator.move_to_safe_water_zone(self.config)
                    InputSimulator.click(duration=0.04)
                    time.sleep(1.2)

                    if features.get("failsafe_auto_recovery", True) and self.consecutive_sinking_timeouts >= 2:
                        self._perform_failsafe_recovery()
                    continue

                self.consecutive_sinking_timeouts = 0

                # ====================================================
                # TRANSITION: BITE REACTION DELAY (350ms)
                # ====================================================
                InputSimulator.mouse_up()
                self.log(f"🐟 [Transition: Bite Reaction] ตรวจพบปลาติดเบ็ด! (Match: {int(last_score*100)}%) -> หน่วง {int(reaction_delay*1000)}ms...")
                self.set_progress(100.0, f"ปลาติดเบ็ด! กำลังสลับเข้าสู่ Reeling ({int(reaction_delay*1000)}ms)...")
                time.sleep(reaction_delay)

                InputSimulator.move_to_safe_water_zone(self.config)
                InputSimulator.mouse_down()

                # ====================================================
                # STATE 3: REELING PROCESS (Adaptive Vision & Micro-Jitter 120ms)
                # ====================================================
                self.set_state(BotState.REELING)
                cancel_roi = self.config.get("screen", {}).get("cancel_btn_roi")
                self.set_overlay(cancel_roi, "#ff79c6", "🎣 ดึงปลา / เช็กปุ่ม Cancel (State 3)")
                reel_hold_duration = self.calculate_reel_duration()
                self.log(f"🎣 [State 3: Reeling] เริ่มกดคลิกซ้ายค้างดึงปลา ({reel_hold_duration}s) + Micro-Jitter ทุก 120ms...")

                start_reel = time.perf_counter()
                last_jitter = time.time()

                # Reeling hold loop
                while self.is_running and (time.perf_counter() - start_reel) < reel_hold_duration:
                    now = time.time()
                    elapsed_reel = time.perf_counter() - start_reel
                    reel_pct = min(100.0, (elapsed_reel / reel_hold_duration) * 100.0)
                    self.set_progress(reel_pct, f"กำลังกดค้างดึงปลา: {elapsed_reel:.1f}s / {reel_hold_duration:.1f}s (Micro-Jitter 120ms)")

                    if now - last_jitter >= jitter_interval:
                        InputSimulator.send_micro_jitter()
                        last_jitter = now
                    time.sleep(scan_interval)

                cancel_extension_enabled = features.get("cancel_extension_enabled", True)
                cancel_extension_max = float(timings.get("reeling_cancel_extension_max_sec", 35.0) or 35.0)

                if cancel_extension_enabled and self.is_running:
                    # ====================================================
                    # Mode A: Cancel Extension Enabled (Keep reeling until fish surfaces)
                    # ====================================================
                    if self.detector.detect_red_cancel_button():
                        self.log(f"🔄 [Cancel Auto-Extension] ครบเวลา {reel_hold_duration:.1f}s แต่ปุ่ม Cancel ยังคงอยู่ -> กดค้างดึงต่อไปเรื่อยๆ จนกว่าปุ่ม Cancel จะหายไป...")
                        ext_start = time.perf_counter()
                        while self.is_running and (time.perf_counter() - ext_start) < cancel_extension_max:
                            now = time.time()
                            elapsed_ext = time.perf_counter() - ext_start
                            self.set_progress(100.0, f"กำลังกดดึงต่ออัตโนมัติ: +{elapsed_ext:.1f}s (รอปุ่ม Cancel หายไป)...")

                            if now - last_jitter >= jitter_interval:
                                InputSimulator.send_micro_jitter()
                                last_jitter = now

                            # Check if Cancel button has disappeared
                            if not self.detector.detect_red_cancel_button():
                                time.sleep(0.02)
                                if not self.detector.detect_red_cancel_button():
                                    self.log(f"✨ [Cancel Auto-Extension] ปุ่ม Cancel หายไปแล้ว (+{elapsed_ext:.1f}s) -> ปลาลอยขึ้นสู่ผิวน้ำเรียบร้อย! ปล่อยเมาส์ทันที")
                                    break
                            time.sleep(scan_interval)

                    InputSimulator.mouse_up()
                    self.stats["fish_caught"] += 1
                    self.update_stats()
                    self.log(f"🎉 [State 3: Reeling Complete] ดึงปลาขึ้นสู่ผิวน้ำครบ 100% -> ส่ง MouseUp เรียบร้อย (+1 ตัว รวม {self.stats['fish_caught']} ตัว)")

                else:
                    # ====================================================
                    # Mode B: Cancel Extension Disabled (Release mouse at exact time, click Cancel if still present to loop back to State 1)
                    # ====================================================
                    InputSimulator.mouse_up()
                    time.sleep(0.08)

                    if self.is_running and self.detector.detect_red_cancel_button():
                        self.log(f"🛑 [Fast Cancel Reset] ครบเวลาดึงปลา {reel_hold_duration:.1f}s แต่ปลายังไม่ขึ้นน้ำ (ปิดสวิตช์ Extension) -> คลิกปุ่ม Cancel เพื่อตัดสายและวนกลับไปเหวี่ยงเบ็ด State 1 ทันที!")
                        self.set_progress(100.0, "🛑 กำลังคลิกปุ่ม Cancel เพื่อตัดสายเบ็ดและเริ่มเหวี่ยงใหม่...")
                        InputSimulator.click_cancel_button(self.config)
                        time.sleep(0.4)
                        continue  # Loop back to STATE 1 immediately!
                    else:
                        self.stats["fish_caught"] += 1
                        self.update_stats()
                        self.log(f"🎉 [State 3: Reeling Complete] ดึงปลาขึ้นสู่ผิวน้ำครบตามเวลา {reel_hold_duration:.1f}s (+1 ตัว รวม {self.stats['fish_caught']} ตัว)")

                # ====================================================
                # STATE 4: LOOT & FAST RESET (1.9s Recast + Click-to-Dismiss)
                # ====================================================
                self.set_state(BotState.LOOT_RESET)
                self.set_overlay(None)
                self.log(f"⏳ [State 4: Loot & Reset] รอการ์ดแสดงผล ({recast_delay}s)... ส่งคลิกซ้าย 1 ครั้งเพื่อข้ามการ์ดและเตรียมเหวี่ยงเบ็ด")

                time.sleep(0.5)

                # Check global interrupt / Legendary popup
                if self.check_global_interrupt():
                    if not self.is_running:
                        break

                # Left Click at Safe Zone to dismiss notification cards
                InputSimulator.move_to_safe_water_zone(self.config)
                InputSimulator.click(duration=0.04)

                remaining_recast = max(0.4, recast_delay - 0.5)
                start_loot = time.time()
                while time.time() - start_loot < remaining_recast:
                    if not self.is_running:
                        break
                    remain = remaining_recast - (time.time() - start_loot)
                    pct = min(100.0, ((remaining_recast - remain) / remaining_recast) * 100.0)
                    self.set_progress(pct, f"คลิกข้ามการ์ดปลาแล้ว -> เตรียมเหวี่ยงเบ็ด: {remain:.1f}s...")
                    time.sleep(0.05)

        except Exception as e:
            err_msg = traceback.format_exc()
            self.log(f"❌ เกิดข้อผิดพลาดในการทำงาน: {e}")
            print(f"[Bot Error] {err_msg}")
        finally:
            InputSimulator.mouse_up()
            if self.state != BotState.PAUSED_INVENTORY_FULL:
                self.set_state(BotState.IDLE)
                self.set_progress(0, "ระบบหยุดการทำงาน")
