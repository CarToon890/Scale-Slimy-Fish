"""
Vision Module for Scale Slimy Fish Auto Fishing Bot.
Implements:
1. High-Accuracy Template Matching Text Detector (cv2.TM_CCOEFF_NORMED)
2. Lightning Flash Spike Rejection Filter (Mean Brightness > 235)
3. Narrow Vertical Bar ROI (Isolates from Right-side Loot UI Overlays)
4. Red Cancel Button Detector (Pre-Cast State Validation)
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
            self.monitor = dict(sct.monitors[1])  # Primary monitor

        # Reusable Morphological Kernel (3x3)
        self.kernel_3x3 = np.ones((3, 3), np.uint8)

        # Template Cache
        self.hold_template_gray = None
        self.load_hold_template()

    @property
    def sct(self):
        """Returns a thread-local MSS instance to prevent cross-thread handle errors."""
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
        """Loads or reloads the 'Hold to fish' reference template image."""
        tpl_path = self.config.get("screen", {}).get("template_path", "template_hold.png")
        if os.path.exists(tpl_path):
            try:
                img = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
                if img is not None and img.size > 0:
                    self.hold_template_gray = img
                    return True
            except Exception as e:
                print(f"[Vision] Error loading template: {e}")
        self.hold_template_gray = None
        return False

    def save_hold_template(self, frame):
        if frame is None or frame.size == 0:
            return False
        tpl_path = self.config.get("screen", {}).get("template_path", "template_hold.png")
        cv2.imwrite(tpl_path, frame)
        self.load_hold_template()
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
        """Detects transient full-screen whiteout caused by lightning."""
        if frame is None or frame.size == 0:
            return False
        flash_threshold = self.config.get("thresholds", {}).get("flash_brightness_threshold", 235)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        return np.mean(gray) >= flash_threshold

    # ----------------------------------------------------
    # MANUAL ROI CAPTURES
    # ----------------------------------------------------
    def capture_cast_bar(self):
        cast_roi = self.config.get("screen", {}).get("cast_bar_roi", {
            "x_ratio": 0.77,
            "y_ratio": 0.22,
            "w_ratio": 0.048,
            "h_ratio": 0.35
        })
        box = self.ratio_to_pixel_box(cast_roi)
        return self.capture_screen(box)

    def get_cast_bar_peak_box(self):
        cast_roi = self.config.get("screen", {}).get("cast_bar_roi", {
            "x_ratio": 0.77,
            "y_ratio": 0.22,
            "w_ratio": 0.048,
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

    # ----------------------------------------------------
    # AUTO SCREEN SCAN CAPTURES (Broad Search Areas)
    # ----------------------------------------------------
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
    # RED CANCEL BUTTON DETECTION
    # ----------------------------------------------------
    def detect_red_cancel_button(self):
        cancel_roi = self.config.get("screen", {}).get("cancel_btn_roi", {
            "x_ratio": 0.40,
            "y_ratio": 0.70,
            "w_ratio": 0.20,
            "h_ratio": 0.18
        })
        box = self.ratio_to_pixel_box(cancel_roi)
        frame = self.capture_screen(box)

        if frame is None or frame.size == 0:
            return False

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, np.array([0, 120, 100]), np.array([10, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([170, 120, 100]), np.array([180, 255, 255]))
        red_mask = cv2.bitwise_or(mask1, mask2)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, self.kernel_3x3)
        return cv2.countNonZero(red_mask) >= 100

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
            if area >= 120 and w <= 70:
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

    # ----------------------------------------------------
    # TEMPLATE MATCHING FOR HOLD TO FISH
    # ----------------------------------------------------
    def _match_template_engine(self, search_frame):
        threshold = self.config.get("thresholds", {}).get("hold_template_match_threshold", 0.65)

        if self.hold_template_gray is None:
            self.load_hold_template()

        if self.hold_template_gray is None:
            return self._fallback_contrast_detect(search_frame)

        if search_frame is None or search_frame.size == 0:
            return False, 0.0, {"error": "Empty search frame"}

        if self.config.get("features", {}).get("lightning_flash_rejection", True) and self.is_lightning_flash(search_frame):
            return False, 0.0, {"is_detected": False, "match_score": 0.0, "rejected_flash": True}

        search_gray = cv2.cvtColor(search_frame, cv2.COLOR_BGR2GRAY)
        th, tw = self.hold_template_gray.shape[:2]
        sh, sw = search_gray.shape[:2]

        if sh < th or sw < tw:
            return False, 0.0, {"error": "Search frame smaller than template"}

        res = cv2.matchTemplate(search_gray, self.hold_template_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

        match_score = round(float(max_val), 4)
        is_detected = match_score >= threshold

        details = {
            "is_detected": is_detected,
            "match_score": match_score,
            "threshold": threshold,
            "location": max_loc
        }
        return is_detected, match_score, details

    def _fallback_contrast_detect(self, frame):
        if frame is None or frame.size == 0:
            return False, 0.0, {"error": "Empty frame"}
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        total_pixels = frame.shape[0] * frame.shape[1]
        _, bright_mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        density = cv2.countNonZero(bright_mask) / total_pixels
        is_detected = density >= 0.015
        return is_detected, round(density, 4), {"mode": "fallback_contrast", "density": density}

    def _detect_hold_text_manual(self, frame=None):
        if frame is None:
            frame = self.capture_hold_text()
        is_detected, score, details = self._match_template_engine(frame)
        details["mode"] = "manual"
        return is_detected, details

    def _detect_hold_text_auto(self, frame=None):
        if frame is None:
            frame = self.capture_auto_hold_area()
        is_detected, score, details = self._match_template_engine(frame)
        details["mode"] = "auto"
        return is_detected, details

    def detect_hold_text(self, frame=None, force_mode=None):
        mode = force_mode or self.config.get("screen", {}).get("detection_mode", "auto")
        if mode == "manual":
            return self._detect_hold_text_manual(frame)
        else:
            return self._detect_hold_text_auto(frame)

    def save_single_debug_crop(self, name, frame=None):
        os.makedirs("debug", exist_ok=True)
        path = os.path.join("debug", name)
        if frame is not None and frame.size > 0:
            cv2.imwrite(path, frame)
        return path


if __name__ == "__main__":
    detector = VisionDetector()
    print("Screen dimensions:", detector.get_screen_dimensions())
    print("Testing Template Matching...")
    ht = detector.capture_hold_text()
    ht_ok, ht_d = detector.detect_hold_text(ht)
    print(f"Hold to fish Template Match: {ht_ok}, details: {ht_d}")
