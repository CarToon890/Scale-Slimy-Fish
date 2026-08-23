"""
Bot Core Engine for Scale Slimy Fish Auto Fishing Bot.
Implements the 5-State Closed-Loop Engine with:
- Dynamic Sinking Timeout (Calculated automatically from Depth: (Depth/12.0)+5.0s)
- Adaptive Min Charge Gate (0.30s for fast-responding high-tier rods)
- Failsafe Auto-Recovery on Consecutive Timeouts (Unequip/Re-equip Slot 1)
- State 4 Click-to-Dismiss (Instant Loot Skip & Fast Cast)
- Triple Double-Check Validation (State 1 Green Peak, State 2 Template Match, State 3 Reeling Extension)
- Dynamic Rod Reeling Duration Formula
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

# Set DPI awareness
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

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001
KEYEVENTF_KEYUP = 0x0002
VK_KEY_1 = 0x31

user32 = ctypes.windll.user32


class BotState(Enum):
    IDLE = "STATE 0: IDLE / READY (สแตนด์บาย Safe Zone)"
    CASTING = "STATE 1: CASTING (ชาร์จเกจพลังงาน -> ดับเบิ้ลเช็คโซนเขียว)"
    SINKING = "STATE 2: SINKING (เบ็ดจมน้ำตาม Depth & ดับเบิ้ลเช็คปลาติด)"
    REELING = "STATE 3: REELING (กดค้างดึงปลา + ดับเบิ้ลเช็คปุ่ม Cancel)"
    LOOT_RESET = "STATE 4: LOOT & RESET (คลิกข้ามการ์ดปลา & วนรอบเหวี่ยงเบ็ด)"


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
        """Presses key '1' to toggle tool slot 1 in Roblox."""
        user32.keybd_event(VK_KEY_1, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_KEY_1, 0, KEYEVENTF_KEYUP, 0)

    @staticmethod
    def micro_anti_afk():
        user32.mouse_event(MOUSEEVENTF_MOVE, 2, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(MOUSEEVENTF_MOVE, -2, 0, 0, 0)


class FishingBot:
    def __init__(self, config_path="config.json", log_callback=None, state_callback=None, stats_callback=None, progress_callback=None):
        self.config_path = config_path
        self.log_callback = log_callback or print
        self.state_callback = state_callback
        self.stats_callback = stats_callback
        self.progress_callback = progress_callback

        self.detector = VisionDetector(config_path=config_path)
        self.config = self.detector.config

        self.state = BotState.IDLE
        self.is_running = False
        self.worker_thread = None

        self.stats = {
            "casts_count": 0,
            "fish_caught": 0,
            "perfect_casts": 0,
            "start_time": None,
            "uptime_seconds": 0
        }

        self.consecutive_sinking_timeouts = 0
        self.last_anti_afk_time = time.time()

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

    def set_progress(self, percent: float, sub_msg: str = ""):
        if self.progress_callback:
            self.progress_callback(percent, sub_msg)

    def update_stats(self):
        if self.stats["start_time"]:
            self.stats["uptime_seconds"] = int(time.time() - self.stats["start_time"])
        if self.stats_callback:
            self.stats_callback(self.stats)

    def calculate_reel_duration(self):
        rod = self.config.get("rod_stats", {"depth": 280, "strength": 90})
        depth = float(rod.get("depth", 280))
        strength = max(1.0, float(rod.get("strength", 90)))
        calc_duration = round((depth / strength) * 1.65 + 0.5, 1)
        override = self.config.get("timings", {}).get("reel_hold_duration_sec", None)
        return override if override is not None else max(3.0, calc_duration)

    def calculate_sinking_timeout(self):
        """Calculates dynamic sinking timeout based on rod depth."""
        rod = self.config.get("rod_stats", {"depth": 280, "strength": 90})
        depth = float(rod.get("depth", 280))
        calc_timeout = round(max(14.0, (depth / 12.0) + 5.0), 1)
        override = self.config.get("timings", {}).get("sinking_timeout_sec", None)
        return override if override is not None else calc_timeout

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
        self.log(f"🚀 บอทเริ่มทำงาน (Dynamic Depth & Adaptive Engine | โหมด: {mode})")

    def stop(self):
        if not self.is_running:
            return

        self.is_running = False
        InputSimulator.mouse_up()
        self.set_state(BotState.IDLE)
        self.set_progress(0, "ระบบหยุดการทำงาน")
        self.log("⏹️ บอทหยุดการทำงาน (Stopped)")

    def _perform_failsafe_recovery(self):
        """Emergency recovery: Unequips and Re-equips tool slot 1 and clicks water."""
        self.log("🚨 [Failsafe Auto-Recovery] เกิด Timeout ติดต่อกัน 2 ครั้ง -> ดำเนินการรีเซ็ตคันเบ็ด (Unequip/Re-equip Slot 1)...")
        self.set_progress(100.0, "🚨 Failsafe: กำลังรีเซ็ตคันเบ็ด Slot 1...")
        InputSimulator.move_to_safe_water_zone(self.config)
        InputSimulator.click(0.04)
        time.sleep(0.5)
        # Toggle unequip slot 1
        InputSimulator.press_key_1()
        time.sleep(1.0)
        # Toggle re-equip slot 1
        InputSimulator.press_key_1()
        time.sleep(1.5)
        self.consecutive_sinking_timeouts = 0
        self.log("✅ [Failsafe Recovery] รีเซ็ตคันเบ็ดและตัวละครเรียบร้อยแล้ว พร้อมเริ่มรอบใหม่")

    def _execute_casting_state(self):
        timings = self.config.get("timings", {})
        features = self.config.get("features", {})
        min_gate = timings.get("min_charge_gate_sec", 0.30)
        backup_timeout = timings.get("charge_backup_sec", 1.4)
        poll_interval = timings.get("cast_poll_interval_sec", 0.005)
        settle_delay = timings.get("cast_settle_delay_sec", 1.0)
        double_check = features.get("double_check_enabled", True)

        # 0. Pre-Cast Validation
        if features.get("pre_cast_validation", True):
            if self.detector.detect_red_cancel_button():
                self.log("⚠️ [Pre-Cast Validation] ตรวจพบสายเบ็ดยังจมน้ำอยู่ -> ส่งคลิก 1 ครั้งดึงเบ็ดกลับก่อน...")
                InputSimulator.move_to_safe_water_zone(self.config)
                InputSimulator.click(0.04)
                time.sleep(1.5)

        # 1. ย้ายเคอร์เซอร์ไป Safe Water Zone
        InputSimulator.move_to_safe_water_zone(self.config)

        # 2. เริ่มกดค้างเพื่อชาร์จเกจ
        InputSimulator.mouse_down()
        start_ts = time.perf_counter()
        vision_success = False
        last_green_ratio = 0.0

        # 3. High-Frequency Polling Loop with Adaptive Gate
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
            self.log(f"✨ [State 1: Double-Checked ✅] ตรวจพบสีเขียว 2 เฟรมติด ({int(last_green_ratio*100)}%) ที่ {cast_time_ms}ms -> ปล่อยเมาส์ Perfect !")
        else:
            self.log(f"⚡ [State 1: Cast] ชาร์จครบกำหนด {cast_time_ms}ms -> ปล่อยเมาส์ตาม Safety Backup")

        # 5. รอทุ่นลอยตกน้ำ
        self.set_progress(100.0, "รอทุ่นลอยตกกระทบผิวน้ำ...")
        time.sleep(settle_delay)
        return vision_success

    def _bot_loop(self):
        timings = self.config.get("timings", {})
        features = self.config.get("features", {})

        reaction_delay = timings.get("bite_reaction_delay_sec", 0.35)
        recast_delay = timings.get("recast_delay_sec", 1.8)
        jitter_interval = timings.get("jitter_interval_sec", 0.12)
        scan_interval = timings.get("scan_interval_sec", 0.025)
        anti_afk_interval = timings.get("anti_afk_interval_sec", 120.0)
        cancel_extension_max = timings.get("reeling_cancel_extension_sec", 2.5)
        double_check = features.get("double_check_enabled", True)

        try:
            while self.is_running:
                # Anti-AFK Check
                if features.get("anti_afk_enabled", True):
                    if time.time() - self.last_anti_afk_time > anti_afk_interval:
                        InputSimulator.micro_anti_afk()
                        self.last_anti_afk_time = time.time()
                        self.log("🛡️ Anti-AFK ทำงาน (ป้องกัน Roblox Kick)")

                # ====================================================
                # STATE 0: IDLE / READY (เตรียมตัวละคร)
                # ====================================================
                self.set_state(BotState.IDLE)
                self.set_progress(0, "เตรียมความพร้อมตัวละคร (Safe Water Zone)...")
                InputSimulator.move_to_safe_water_zone(self.config)
                time.sleep(0.15)

                # ====================================================
                # STATE 1: CASTING (ชาร์จเกจพลังงาน)
                # ====================================================
                self.set_state(BotState.CASTING)
                self.log("🎣 [State 1: Casting] ส่ง MouseDown ชาร์จเกจพลังงาน (สแกนสีเขียวหัวเกจ)...")
                self.stats["casts_count"] += 1
                self.update_stats()

                self._execute_casting_state()

                # ====================================================
                # STATE 2: SINKING (Dynamic Depth Sinking & Double-Check)
                # ====================================================
                self.set_state(BotState.SINKING)
                sinking_timeout = self.calculate_sinking_timeout()
                depth_val = self.config.get("rod_stats", {}).get("depth", 280)
                self.log(f"🌊 [State 2: Sinking] สายเบ็ดกำลังจมลงสู่ใต้ทะเล (Depth: {depth_val}m | Dynamic Timeout: {sinking_timeout}s)...")
                
                start_sink = time.time()
                hooked = False
                last_score = 0.0

                while time.time() - start_sink < sinking_timeout:
                    if not self.is_running:
                        break

                    elapsed_sink = time.time() - start_sink
                    sink_pct = min(100.0, (elapsed_sink / sinking_timeout) * 100.0)
                    
                    is_text, details = self.detector.detect_hold_text()
                    last_score = details.get("match_score", 0.0)
                    
                    self.set_progress(sink_pct, f"สายเบ็ดกำลังจมน้ำ (Depth: {depth_val}m)... ({elapsed_sink:.1f}s / {sinking_timeout:.1f}s) | Match: {int(last_score*100)}%")

                    if is_text:
                        if double_check:
                            time.sleep(0.025)
                            is_text_2, details_2 = self.detector.detect_hold_text()
                            if is_text_2:
                                hooked = True
                                last_score = details_2.get("match_score", last_score)
                                break
                        else:
                            hooked = True
                            break
                    time.sleep(scan_interval)

                if not hooked:
                    self.consecutive_sinking_timeouts += 1
                    self.log(f"⚠️ [State 2 Timeout #{self.consecutive_sinking_timeouts}] ครบ {sinking_timeout}s ไม่พบปลาติดเบ็ด -> ส่งคลิกตัดสาย 1 ครั้ง")
                    InputSimulator.move_to_safe_water_zone(self.config)
                    InputSimulator.click(duration=0.04)
                    time.sleep(1.2)

                    # Trigger Failsafe Auto-Recovery if timed out 2 times in a row
                    if features.get("failsafe_auto_recovery", True) and self.consecutive_sinking_timeouts >= 2:
                        self._perform_failsafe_recovery()
                    continue

                # Reset timeout streak on successful hook
                self.consecutive_sinking_timeouts = 0

                # ====================================================
                # STATE 2 -> STATE 3 TRANSITION: BITE REACTION DELAY
                # ====================================================
                InputSimulator.mouse_up()
                self.log(f"🐟 [State 2->3: Double-Checked ✅] ยืนยัน 'Hold to fish' 2 เฟรมติด (Match: {int(last_score*100)}%) -> หน่วง Reaction {int(reaction_delay*1000)}ms...")
                self.set_progress(100.0, f"ยืนยันปลาติดเบ็ด 100%! (Match: {int(last_score*100)}%) สลับเข้าสู่ Reeling...")
                time.sleep(reaction_delay)

                InputSimulator.move_to_safe_water_zone(self.config)
                InputSimulator.mouse_down()

                # ====================================================
                # STATE 3: REELING PROCESS (กดค้างดึงปลา + Double-Check Cancel Button)
                # ====================================================
                self.set_state(BotState.REELING)
                reel_hold_duration = self.calculate_reel_duration()
                self.log(f"🎣 [State 3: Reeling] เริ่มกดคลิกซ้ายค้างดึงปลาเต็มเวลา ({reel_hold_duration}s) + Micro-Jitter ทุก 120ms...")

                start_reel = time.perf_counter()
                last_jitter = time.time()

                while self.is_running and (time.perf_counter() - start_reel) < reel_hold_duration:
                    now = time.time()
                    elapsed_reel = time.perf_counter() - start_reel
                    reel_pct = min(100.0, (elapsed_reel / reel_hold_duration) * 100.0)
                    self.set_progress(reel_pct, f"กำลังกดค้างดึงปลา: {elapsed_reel:.1f}s / {reel_hold_duration:.1f}s (Micro-Jitter Active)")

                    if now - last_jitter >= jitter_interval:
                        InputSimulator.send_micro_jitter()
                        last_jitter = now
                    time.sleep(scan_interval)

                # DOUBLE-CHECK 3: Check if red Cancel button is still on screen after base time
                if double_check and self.is_running:
                    if self.detector.detect_red_cancel_button():
                        self.log(f"⚠️ [State 3 Double-Check] ครบเวลา {reel_hold_duration}s แต่ปุ่ม Cancel ยังอยู่ -> ขยายเวลากดค้างต่ออัตโนมัติ (สูงสุด +{cancel_extension_max}s)...")
                        ext_start = time.perf_counter()
                        while self.is_running and (time.perf_counter() - ext_start) < cancel_extension_max:
                            now = time.time()
                            elapsed_ext = time.perf_counter() - ext_start
                            self.set_progress(100.0, f"ขยายเวลาดึงปลาต่อ: +{elapsed_ext:.1f}s (รอปุ่ม Cancel หายไป)...")

                            if now - last_jitter >= jitter_interval:
                                InputSimulator.send_micro_jitter()
                                last_jitter = now

                            if not self.detector.detect_red_cancel_button():
                                self.log(f"✨ [State 3 Double-Check] ปุ่ม Cancel หายไปแล้ว (+{elapsed_ext:.1f}s) -> ปลาลอยขึ้นสู่ผิวน้ำเรียบร้อย!")
                                break
                            time.sleep(scan_interval)

                InputSimulator.mouse_up()
                self.stats["fish_caught"] += 1
                self.update_stats()
                self.log(f"🎉 [State 3: Double-Checked ✅] ดึงปลาขึ้นสู่ผิวน้ำครบ 100% -> ส่ง MouseUp เรียบร้อย (+1 ตัว รวม {self.stats['fish_caught']} ตัว)")

                # ====================================================
                # STATE 4: LOOT & FAST RESET (Click Left Tap to Dismiss Card & Cast)
                # ====================================================
                self.set_state(BotState.LOOT_RESET)
                self.log(f"⏳ [State 4: Loot & Reset] รอการ์ดแสดงผล ({recast_delay}s)... ส่งคลิกซ้าย 1 ครั้งเพื่อข้ามการ์ดและเตรียมเหวี่ยงเบ็ด")

                time.sleep(0.6)

                InputSimulator.move_to_safe_water_zone(self.config)
                InputSimulator.click(duration=0.04)

                remaining_recast = max(0.4, recast_delay - 0.6)
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
            self.set_state(BotState.IDLE)
            self.set_progress(0, "ระบบหยุดการทำงาน")
