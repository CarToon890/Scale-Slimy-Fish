"""
Vision Module for Scale Slimy Fish Auto Fishing Bot.
Implements:
1. High-Performance Template Matching for 'Hold to fish'
2. is_click_to_continue_present(): Template Matching on "Click to Continue" (Score >= 0.70)
3. is_inventory_full(): HSV Red Masking on "Inventory full" text (Red Ratio >= 0.04)
4. High-Precision Cancel Button Detection (Bottom-Edge UI + Dual Red/White Contrast)
5. Dual Anchor Detection: Hold to fish Template + Red '!' Exclamation Mark
6. High-Accuracy Power Bar Green Peak Detector (15% Top Sub-ROI + Morphological OPEN)
7. Lightning Flash Rejection Filter
"""

import sys
import time
import json
import os
import threading
import ctypes
import cv2
import numpy as np
import mss

# Enable Per-Monitor DPI Awareness
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


class VisionDetector:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.config = self.load_config()
        self._thread_local = threading.local()

        # Cache primary monitor dimensions
        with mss.mss() as sct:
            self.monitor = dict(sct.monitors[1])

        # Reusable Morphological Kernel (3x3)
        self.kernel_3x3 = np.ones((3, 3), np.uint8)

        # HSV Red Range for Inventory Full
        self.lower_red1 = np.array([0, 140, 100], dtype=np.uint8)
        self.upper_red1 = np.array([10, 255, 255], dtype=np.uint8)
        self.lower_red2 = np.array([170, 140, 100], dtype=np.uint8)
        self.upper_red2 = np.array([180, 255, 255], dtype=np.uint8)

        # Template Caches
        self.hold_template_gray = None
        self.continue_template_gray = None
        self.load_hold_template()
        self.load_continue_template()

    @property
    def sct(self):
        if not hasattr(self._thread_local, "sct") or self._thread_local.sct is None:
            self._thread_local.sct = mss.mss()
        return self._thread_local.sct

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Vision] Error loading config: {e}")
        return {}

    def load_hold_template(self):
        tpl_path = self.config.get("screen", {}).get("template_path", "template_hold.png")
        if os.path.exists(tpl_path):
            try:
                img = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
                if img is not None and img.size > 0:
                    self.hold_template_gray = img
                    return True
            except Exception as e:
                print(f"[Vision] Error loading hold template: {e}")
        self.hold_template_gray = None
        return False

    def load_continue_template(self):
        tpl_path = self.config.get("screen", {}).get("template_continue_path", "template_continue.png")
        if os.path.exists(tpl_path):
            try:
                img = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
                if img is not None and img.size > 0:
                    self.continue_template_gray = img
                    return True
            except Exception as e:
                print(f"[Vision] Error loading continue template: {e}")
        self.continue_template_gray = None
        return False

    def save_hold_template(self, frame):
        if frame is None or frame.size == 0:
            return False
        tpl_path = self.config.get("screen", {}).get("template_path", "template_hold.png")
        cv2.imwrite(tpl_path, frame)
        self.load_hold_template()
        return True

    def save_continue_template(self, frame):
        if frame is None or frame.size == 0:
            return False
        tpl_path = self.config.get("screen", {}).get("template_continue_path", "template_continue.png")
        cv2.imwrite(tpl_path, frame)
        self.load_continue_template()
        return True

    def get_screen_dimensions(self):
        return self.monitor["width"], self.monitor["height"]

    def ratio_to_pixel_box(self, roi_ratio):
        sw = self.monitor["width"]
        sh = self.monitor["height"]
        left = self.monitor["left"] + int(roi_ratio.get("x_ratio", 0.35) * sw)
        top = self.monitor["top"] + int(roi_ratio.get("y_ratio", 0.40) * sh)
        width = int(roi_ratio.get("w_ratio", 0.30) * sw)
        height = int(roi_ratio.get("h_ratio", 0.15) * sh)

        return {
            "left": max(0, left),
            "top": max(0, top),
            "width": max(10, width),
            "height": max(10, height)
        }

    def capture_screen(self, roi_box=None):
        box = roi_box if roi_box else self.monitor
        screenshot = self.sct.grab(box)
        img = np.array(screenshot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def is_lightning_flash(self, frame):
        if frame is None or frame.size == 0:
            return False
        flash_threshold = self.config.get("thresholds", {}).get("flash_brightness_threshold", 235)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        return np.mean(gray) >= flash_threshold

    # ----------------------------------------------------
    # 1. CLICK TO CONTINUE (LEGENDARY / NEW FISH POPUP)
    # ----------------------------------------------------
    def is_click_to_continue_present(self) -> bool:
        modal_roi = self.config.get("screen", {}).get("modal_continue_roi", {
            "x_ratio": 0.30,
            "y_ratio": 0.10,
            "w_ratio": 0.40,
            "h_ratio": 0.15
        })
        box = self.ratio_to_pixel_box(modal_roi)
        frame = self.capture_screen(box)

        if frame is None or frame.size == 0:
            return False

        if self.is_lightning_flash(frame):
            return False

        # 1. Primary: Template Matching with template_continue.png
        if self.continue_template_gray is None:
            self.load_continue_template()

        if self.continue_template_gray is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            th, tw = self.continue_template_gray.shape[:2]
            gh, gw = gray.shape[:2]

            if gh >= th and gw >= tw:
                res = cv2.matchTemplate(gray, self.continue_template_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                score_threshold = self.config.get("thresholds", {}).get("modal_continue_score", 0.70)
                if max_val >= score_threshold:
                    return True

        # 2. Fallback: Golden 'Found New Fish!' + White text banner detection
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        yellow_mask = cv2.inRange(hsv, np.array([16, 130, 140]), np.array([34, 255, 255]))
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, white_mask = cv2.threshold(gray_frame, 235, 255, cv2.THRESH_BINARY)

        modal_pixels = cv2.countNonZero(yellow_mask) + cv2.countNonZero(white_mask)
        return modal_pixels >= 650

    def detect_click_to_continue(self) -> bool:
        return self.is_click_to_continue_present()

    # ----------------------------------------------------
    # 2. INVENTORY FULL WARNING DETECTOR
    # ----------------------------------------------------
    def is_inventory_full(self) -> bool:
        inv_roi = self.config.get("screen", {}).get("inventory_full_roi", {
            "x_ratio": 0.38,
            "y_ratio": 0.12,
            "w_ratio": 0.24,
            "h_ratio": 0.08
        })
        box = self.ratio_to_pixel_box(inv_roi)
        frame = self.capture_screen(box)

        if frame is None or frame.size == 0:
            return False

        if self.is_lightning_flash(frame):
            return False

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, self.lower_red1, self.upper_red1)
        mask2 = cv2.inRange(hsv, self.lower_red2, self.upper_red2)
        red_mask = cv2.bitwise_or(mask1, mask2)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, self.kernel_3x3)

        total_pixels = box["width"] * box["height"]
        red_ratio = cv2.countNonZero(red_mask) / max(1, total_pixels)

        threshold = self.config.get("thresholds", {}).get("inventory_red_ratio", 0.04)
        return red_ratio >= threshold

    # ----------------------------------------------------
    # 3. HIGH-PRECISION CANCEL BUTTON DETECTOR
    # ----------------------------------------------------
    def detect_red_cancel_button(self):
        cancel_roi = self.config.get("screen", {}).get("cancel_btn_roi", {
            "x_ratio": 0.42,
            "y_ratio": 0.83,
            "w_ratio": 0.16,
            "h_ratio": 0.11
        })
        box = self.ratio_to_pixel_box(cancel_roi)
        frame = self.capture_screen(box)

        if frame is None or frame.size == 0:
            return False

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, np.array([0, 140, 110]), np.array([10, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([170, 140, 110]), np.array([180, 255, 255]))
        red_mask = cv2.bitwise_or(mask1, mask2)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, self.kernel_3x3)

        red_pixels = cv2.countNonZero(red_mask)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, white_mask = cv2.threshold(gray, 215, 255, cv2.THRESH_BINARY)
        white_pixels = cv2.countNonZero(white_mask)

        return red_pixels >= 250 and white_pixels >= 20

    # ----------------------------------------------------
    # MANUAL & AUTO ROI CAPTURES
    # ----------------------------------------------------
    def capture_cast_bar(self):
        cast_roi = self.config.get("screen", {}).get("cast_bar_roi", {
            "x_ratio": 0.76,
            "y_ratio": 0.22,
            "w_ratio": 0.06,
            "h_ratio": 0.35
        })
        box = self.ratio_to_pixel_box(cast_roi)
        return self.capture_screen(box)

    def get_cast_bar_peak_box(self):
        cast_roi = self.config.get("screen", {}).get("cast_bar_roi", {
            "x_ratio": 0.76,
            "y_ratio": 0.22,
            "w_ratio": 0.06,
            "h_ratio": 0.35
        })
        base_box = self.ratio_to_pixel_box(cast_roi)
        sub_ratio = self.config.get("thresholds", {}).get("cast_peak_subroi_ratio", 0.15)
        peak_h = max(4, int(base_box["height"] * sub_ratio))

        return {
            "left": base_box["left"],
            "top": base_box["top"],
            "width": base_box["width"],
            "height": peak_h
        }

    def capture_cast_bar_peak(self):
        box = self.get_cast_bar_peak_box()
        return self.capture_screen(box)

    def capture_hold_text(self):
        hold_roi = self.config.get("screen", {}).get("hold_roi", {
            "x_ratio": 0.35,
            "y_ratio": 0.40,
            "w_ratio": 0.30,
            "h_ratio": 0.15
        })
        box = self.ratio_to_pixel_box(hold_roi)
        return self.capture_screen(box)

    def capture_auto_cast_area(self):
        auto_roi = self.config.get("screen", {}).get("auto_cast_search_roi", {
            "x_ratio": 0.65,
            "y_ratio": 0.15,
            "w_ratio": 0.30,
            "h_ratio": 0.60
        })
        box = self.ratio_to_pixel_box(auto_roi)
        return self.capture_screen(box)

    def capture_auto_hold_area(self):
        auto_roi = self.config.get("screen", {}).get("auto_hold_search_roi", {
            "x_ratio": 0.25,
            "y_ratio": 0.25,
            "w_ratio": 0.50,
            "h_ratio": 0.45
        })
        box = self.ratio_to_pixel_box(auto_roi)
        return self.capture_screen(box)

    # ----------------------------------------------------
    # POWER BAR GREEN PEAK DETECTION
    # ----------------------------------------------------
    def _detect_green_peak_manual(self, frame=None):
        if frame is None:
            frame = self.capture_cast_bar_peak()

        if frame is None or frame.size == 0:
            return False, {"error": "Empty frame"}

        if self.config.get("features", {}).get("lightning_flash_rejection", True) and self.is_lightning_flash(frame):
            return False, {"mode": "manual", "is_green_reached": False, "rejected_flash": True}

        h, w = frame.shape[:2]
        sub_ratio = self.config.get("thresholds", {}).get("cast_peak_subroi_ratio", 0.15)
        if h > 50:
            top_h = max(4, int(h * sub_ratio))
            sub_crop = frame[0:top_h, :]
        else:
            sub_crop = frame

        hsv = cv2.cvtColor(sub_crop, cv2.COLOR_BGR2HSV)
        total_pixels = sub_crop.shape[0] * sub_crop.shape[1]

        lower_g = np.array(self.config.get("thresholds", {}).get("cast_lower_green", [35, 120, 100]), dtype=np.uint8)
        upper_g = np.array(self.config.get("thresholds", {}).get("cast_upper_green", [85, 255, 255]), dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_g, upper_g)
        filtered_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel_3x3)
        green_pixel_count = cv2.countNonZero(filtered_mask)
        green_ratio = green_pixel_count / max(1, total_pixels)

        threshold = self.config.get("thresholds", {}).get("cast_green_density_threshold", 0.18)
        is_reached = green_ratio >= threshold

        details = {
            "mode": "manual",
            "is_green_reached": is_reached,
            "green_ratio": round(green_ratio, 4),
            "threshold": threshold,
            "green_pixels": green_pixel_count
        }
        return is_reached, details

    def _detect_green_peak_auto(self, frame=None):
        if frame is None:
            frame = self.capture_auto_cast_area()

        if frame is None or frame.size == 0:
            return False, {"error": "Empty frame"}

        if self.config.get("features", {}).get("lightning_flash_rejection", True) and self.is_lightning_flash(frame):
            return False, {"mode": "auto", "is_green_reached": False, "rejected_flash": True}

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower_g = np.array(self.config.get("thresholds", {}).get("cast_lower_green", [35, 120, 100]), dtype=np.uint8)
        upper_g = np.array(self.config.get("thresholds", {}).get("cast_upper_green", [85, 255, 255]), dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_g, upper_g)
        filtered_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel_3x3)

        contours, _ = cv2.findContours(filtered_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        is_reached = False
        largest_area = 0

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = cv2.contourArea(cnt)
            if area > largest_area:
                largest_area = area
            if area >= 120 and w <= 75:
                is_reached = True
                break

        details = {
            "mode": "auto",
            "is_green_reached": is_reached,
            "green_pixels": cv2.countNonZero(filtered_mask),
            "largest_cluster_area": largest_area
        }
        return is_reached, details

    def detect_green_peak(self, frame=None, force_mode=None):
        mode = force_mode or self.config.get("screen", {}).get("detection_mode", "auto")
        if mode == "manual":
            return self._detect_green_peak_manual(frame)
        else:
            return self._detect_green_peak_auto(frame)

    def is_power_bar_present(self) -> bool:
        mode = self.config.get("screen", {}).get("detection_mode", "auto")
        if mode == "auto":
            frame = self.capture_auto_cast_area()
        else:
            frame = self.capture_cast_bar()

        if frame is None or frame.size == 0:
            return False

        if self.config.get("features", {}).get("lightning_flash_rejection", True) and self.is_lightning_flash(frame):
            return False

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower_g = np.array(self.config.get("thresholds", {}).get("cast_lower_green", [35, 120, 100]), dtype=np.uint8)
        upper_g = np.array(self.config.get("thresholds", {}).get("cast_upper_green", [85, 255, 255]), dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_g, upper_g)
        filtered_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel_3x3)
        green_pixels = cv2.countNonZero(filtered_mask)

        if mode == "auto":
            contours, _ = cv2.findContours(filtered_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                x, y, w, h = cv2.boundingRect(cnt)
                if area >= 60 and w <= 80:
                    return True
            return green_pixels >= 80
        else:
            total_pixels = frame.shape[0] * frame.shape[1]
            return (green_pixels / max(1, total_pixels)) >= 0.05

    # ----------------------------------------------------
    # DUAL ANCHOR: ORIGINAL FAST TEMPLATE MATCH + RED '!'
    # ----------------------------------------------------
    def _detect_exclamation_mark(self, frame):
        if frame is None or frame.size == 0:
            return False, 0
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, np.array([0, 140, 150]), np.array([10, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([170, 140, 150]), np.array([180, 255, 255]))
        red_mark = cv2.bitwise_or(mask1, mask2)
        red_mark = cv2.morphologyEx(red_mark, cv2.MORPH_OPEN, self.kernel_3x3)
        cnt = cv2.countNonZero(red_mark)
        return cnt >= 60, cnt

    def _match_template_engine(self, search_frame):
        threshold = self.config.get("thresholds", {}).get("hold_template_match_threshold", 0.65)

        if self.hold_template_gray is None:
            self.load_hold_template()

        if search_frame is None or search_frame.size == 0:
            return False, 0.0, {"error": "Empty search frame"}

        if self.config.get("features", {}).get("lightning_flash_rejection", True) and self.is_lightning_flash(search_frame):
            return False, 0.0, {"is_detected": False, "match_score": 0.0, "rejected_flash": True}

        has_excl, excl_px = self._detect_exclamation_mark(search_frame)

        if self.hold_template_gray is None:
            return has_excl, 0.0, {"mode": "exclamation_anchor", "is_detected": has_excl}

        search_gray = cv2.cvtColor(search_frame, cv2.COLOR_BGR2GRAY)
        th, tw = self.hold_template_gray.shape[:2]
        sh, sw = search_gray.shape[:2]

        if sh < th or sw < tw:
            return has_excl, 0.0, {"error": "Search frame smaller than template"}

        # Fast direct TM_CCOEFF_NORMED matching
        res = cv2.matchTemplate(search_gray, self.hold_template_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

        match_score = round(float(max_val), 4)
        is_detected = (match_score >= threshold) or has_excl

        details = {
            "is_detected": is_detected,
            "match_score": match_score,
            "has_exclamation": has_excl,
            "threshold": threshold,
            "location": max_loc
        }
        return is_detected, match_score, details

    def detect_hold_anchor(self, frame=None, force_mode=None):
        mode = force_mode or self.config.get("screen", {}).get("detection_mode", "auto")
        if frame is None:
            frame = self.capture_auto_hold_area() if mode == "auto" else self.capture_hold_text()
        is_detected, score, details = self._match_template_engine(frame)
        details["mode"] = mode
        return is_detected, details

    def detect_hold_text(self, frame=None, force_mode=None):
        return self.detect_hold_anchor(frame, force_mode)


if __name__ == "__main__":
    detector = VisionDetector()
    print("Testing Hold anchor:", detector.detect_hold_anchor())
