"""
CYBER HEARTBREAK SECURITY CONSOLE
=================================
Standalone Python hand-tracking console dengan tema cyber-security, patah hati,
dan bucin. Dirancang untuk diedit di Acode lalu dijalankan dari Termux/Pydroid.

Install:
    pip install opencv-python mediapipe numpy

Jalankan:
    python hand_tracking_patah_hati.py
    python hand_tracking_patah_hati.py --camera 0 --width 1280 --height 720
    python hand_tracking_patah_hati.py --record

Gesture utama:
    Telapak terbuka       : SCANNING
    Pinch ibu jari-index   : LOVE LOCK
    Telunjuk ke dahi       : FILTER SWITCH
    Tangan mengepal        : HEARTBREAK
    Dua jari V             : PEACE PATCH
    Dua tangan pinch       : LOVE PORTAL / bounding box antar-tangan

Kontrol keyboard:
    Q / ESC : keluar
    S       : simpan screenshot
    R       : mulai/berhenti merekam video
    H       : tampil/sembunyikan panduan
    L       : tampil/sembunyikan log terminal
    N / P   : next/previous filter
    SPACE   : pause/resume kamera
"""

from __future__ import annotations

import argparse
import logging
import math
import random
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional, Sequence, Tuple

import cv2
import mediapipe as mp
import numpy as np

from advanced_logic import TelemetryMetrics, SecurityRiskEngine

# ------------------------------- Palet ----------------------------------
BGR = Tuple[int, int, int]
CYAN: BGR = (255, 220, 0)
BLUE: BGR = (255, 90, 20)
PINK: BGR = (190, 20, 255)
RED: BGR = (45, 45, 255)
GREEN: BGR = (80, 255, 140)
ORANGE: BGR = (30, 150, 255)
PURPLE: BGR = (210, 60, 190)
WHITE: BGR = (245, 245, 245)
MUTED: BGR = (120, 135, 165)
DARK_PANEL: BGR = (8, 14, 28)
GRID: BGR = (22, 36, 58)

FILTERS: List[Tuple[str, BGR]] = [
    ("PINK LOVE", PINK),
    ("SKETCH BREAK", WHITE),
    ("THERMAL RAGE", RED),
    ("GLITCH HEART", CYAN),
    ("MATRIX MEMORY", GREEN),
]

GESTURE_NAMES = (
    "SCANNING", "LOVE LOCK", "FILTER SWITCH", "HEARTBREAK", "PEACE PATCH",
)


@dataclass
class Config:
    camera: int = 0
    width: int = 1280
    height: int = 720
    max_hands: int = 2
    mirror: bool = True
    detection_confidence: float = 0.68
    tracking_confidence: float = 0.62
    model_complexity: int = 1
    output_dir: Path = Path("cyber_heartbreak_output")


@dataclass
class HandObservation:
    landmarks: object
    label: str
    gesture: str
    score: float
    wrist: Tuple[int, int]
    index_tip: Tuple[int, int]
    thumb_tip: Tuple[int, int]
    bbox: Tuple[int, int, int, int]


@dataclass
class RuntimeState:
    current_gesture: str = "SCANNING"
    stable_gesture: str = "SCANNING"
    filter_index: int = 0
    love_lock: bool = False
    heartbreak: bool = False
    portal_active: bool = False
    show_help: bool = True
    show_logs: bool = True
    paused: bool = False
    recording: bool = False
    last_switch: float = 0.0
    last_event: float = 0.0
    session_start: float = 0.0
    event_count: int = 0


# ---------------------------- Utilitas umum ------------------------------
def now_code() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def distance(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def text(img: np.ndarray, value: str, xy: Tuple[int, int], scale: float = 0.55,
         color: BGR = WHITE, thickness: int = 1) -> None:
    x, y = xy
    cv2.putText(img, value, (x + 2, y + 2), cv2.FONT_HERSHEY_SIMPLEX,
                scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(img, value, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thickness, cv2.LINE_AA)


def glow_line(img: np.ndarray, p1: Tuple[int, int], p2: Tuple[int, int],
              color: BGR, width: int = 2) -> None:
    layer = img.copy()
    cv2.line(layer, p1, p2, color, width + 8, cv2.LINE_AA)
    layer = cv2.GaussianBlur(layer, (0, 0), 5)
    img[:] = cv2.addWeighted(img, 0.80, layer, 0.20, 0)
    cv2.line(img, p1, p2, color, width, cv2.LINE_AA)


def corner_box(img: np.ndarray, x1: int, y1: int, x2: int, y2: int,
               color: BGR = CYAN, length: int = 24, thickness: int = 2) -> None:
    segments = [
        ((x1, y1), (x1 + length, y1)), ((x1, y1), (x1, y1 + length)),
        ((x2, y1), (x2 - length, y1)), ((x2, y1), (x2, y1 + length)),
        ((x1, y2), (x1 + length, y2)), ((x1, y2), (x1, y2 - length)),
        ((x2, y2), (x2 - length, y2)), ((x2, y2), (x2, y2 - length)),
    ]
    for a, b in segments:
        cv2.line(img, a, b, color, thickness, cv2.LINE_AA)


def heart_polygon(cx: int, cy: int, size: int) -> np.ndarray:
    points = []
    for i in range(121):
        t = 2 * math.pi * i / 120
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        points.append((int(cx + x * size / 32), int(cy - y * size / 32)))
    return np.array(points, dtype=np.int32)


def draw_heart(img: np.ndarray, center: Tuple[int, int], size: int,
               color: BGR, broken: bool = False, pulse: float = 0.0) -> None:
    cx, cy = center
    size = int(size * (1.0 + 0.08 * math.sin(pulse)))
    poly = heart_polygon(cx, cy, size)
    glow = img.copy()
    cv2.fillPoly(glow, [poly], color)
    glow = cv2.GaussianBlur(glow, (0, 0), 14)
    img[:] = cv2.addWeighted(img, 0.72, glow, 0.28, 0)
    cv2.polylines(img, [poly], True, color, 2, cv2.LINE_AA)
    if broken:
        crack = np.array([(cx - 5, cy - size // 2), (cx + 5, cy - 10),
                          (cx - 8, cy + 4), (cx + 6, cy + size // 2)])
        cv2.polylines(img, [crack], False, WHITE, 2, cv2.LINE_AA)


# -------------------------- Particle / effects --------------------------
class ParticleField:
    def __init__(self, width: int, height: int, amount: int = 90) -> None:
        self.width, self.height = width, height
        self.items = [[random.randrange(width), random.randrange(height),
                       random.choice((-0.7, -0.3, 0.3, 0.7)),
                       random.choice((-0.35, -0.15, 0.15, 0.35)),
                       random.randrange(70, 210)] for _ in range(amount)]

    def draw(self, img: np.ndarray) -> None:
        h, w = img.shape[:2]
        for p in self.items:
            p[0] = (p[0] + p[2]) % w
            p[1] = (p[1] + p[3]) % h
            value = int(p[4])
            cv2.circle(img, (int(p[0]), int(p[1])), 1,
                       (value, value // 2, 80 + value // 3), -1)


def add_grid(img: np.ndarray, offset: int) -> None:
    h, w = img.shape[:2]
    overlay = img.copy()
    step = 46
    for x in range(-step + offset % step, w, step):
        cv2.line(overlay, (x, 0), (x, h), GRID, 1)
    for y in range(-step + offset % step, h, step):
        cv2.line(overlay, (0, y), (w, y), GRID, 1)
    img[:] = cv2.addWeighted(img, 0.95, overlay, 0.18, 0)


def add_scanlines(img: np.ndarray) -> None:
    overlay = img.copy()
    for y in range(0, img.shape[0], 7):
        cv2.line(overlay, (0, y), (img.shape[1], y), (30, 48, 70), 1)
    img[:] = cv2.addWeighted(img, 0.94, overlay, 0.06, 0)


# ------------------------- Gesture recognition --------------------------
class GestureRecognizer:
    """Deteksi gesture berbasis rasio jarak agar lebih stabil terhadap jarak kamera."""

    @staticmethod
    def points(hand_landmarks: object, width: int, height: int) -> List[Tuple[int, int]]:
        return [(clamp(int(p.x * width), 0, width - 1),
                 clamp(int(p.y * height), 0, height - 1))
                for p in hand_landmarks.landmark]

    def recognize(self, hand_landmarks: object, width: int, height: int) -> Tuple[str, float]:
        p = self.points(hand_landmarks, width, height)
        wrist, index, middle, ring, pinky, thumb = p[0], p[8], p[12], p[16], p[20], p[4]
        palm = max(distance(wrist, p[9]), 1.0)
        pinch_ratio = distance(thumb, index) / palm
        index_ratio = distance(index, wrist) / palm
        middle_ratio = distance(middle, wrist) / palm
        ring_ratio = distance(ring, wrist) / palm
        pinky_ratio = distance(pinky, wrist) / palm

        # Telunjuk ke dahi/pelipis, meniru gesture pada video referensi.
        index_extended = index_ratio > 1.30
        fingers_folded = middle_ratio < 1.45 and ring_ratio < 1.35 and pinky_ratio < 1.30
        near_forehead = index[1] < int(height * 0.36)
        if index_extended and fingers_folded and near_forehead:
            return "FILTER SWITCH", min(1.0, 0.72 + (0.36 - index[1] / height))

        if pinch_ratio < 0.36:
            return "LOVE LOCK", min(1.0, 0.65 + (0.36 - pinch_ratio))

        folded = sum(ratio < 1.18 for ratio in (index_ratio, middle_ratio, ring_ratio, pinky_ratio))
        if folded >= 3:
            return "HEARTBREAK", 0.82

        if index_ratio > 1.35 and middle_ratio > 1.25 and ring_ratio < 1.16 and pinky_ratio < 1.16:
            return "PEACE PATCH", 0.78

        return "SCANNING", 0.55

    def observe(self, hand_landmarks: object, handedness: object,
                width: int, height: int) -> HandObservation:
        points = self.points(hand_landmarks, width, height)
        gesture, score = self.recognize(hand_landmarks, width, height)
        xs, ys = zip(*points)
        label = handedness.classification[0].label if handedness and handedness.classification else "HAND"
        return HandObservation(
            landmarks=hand_landmarks,
            label=label,
            gesture=gesture,
            score=score,
            wrist=points[0],
            index_tip=points[8],
            thumb_tip=points[4],
            bbox=(min(xs), min(ys), max(xs), max(ys)),
        )


class GestureStabilizer:
    def __init__(self, size: int = 7) -> None:
        self.history: Deque[str] = deque(maxlen=size)
        self.last = "SCANNING"

    def update(self, gesture: str) -> str:
        self.history.append(gesture)
        winner, count = Counter(self.history).most_common(1)[0]
        if count >= max(3, len(self.history) // 2):
            self.last = winner
        return self.last


# ------------------------------ Renderer --------------------------------
class CyberRenderer:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.particles = ParticleField(config.width, config.height)
        self.start_time = time.time()

    def apply_filter(self, img: np.ndarray, filter_index: int) -> None:
        name, color = FILTERS[filter_index]
        h, w = img.shape[:2]
        layer = img.copy()
        if name == "PINK LOVE":
            tint = np.zeros_like(img)
            tint[:] = (80, 15, 100)
            layer = cv2.addWeighted(layer, 0.78, tint, 0.22, 0)
        elif name == "SKETCH BREAK":
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 55, 135)
            layer = cv2.addWeighted(layer, 0.74, cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR), 0.34, 0)
        elif name == "THERMAL RAGE":
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            thermal = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)
            layer = cv2.addWeighted(layer, 0.48, thermal, 0.52, 0)
        elif name == "GLITCH HEART":
            shift = int((time.time() * 24) % 14) - 7
            if shift >= 0:
                layer[:, shift:] = img[:, :-shift or None]
            else:
                layer[:, :shift] = img[:, -shift:]
            for _ in range(4):
                y = random.randrange(0, h)
                cv2.line(layer, (0, y), (w, y), color, random.choice((1, 2)), cv2.LINE_AA)
        elif name == "MATRIX MEMORY":
            green = np.zeros_like(img)
            green[:, :, 1] = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            layer = cv2.addWeighted(layer, 0.54, green, 0.62, 0)

        img[:] = cv2.addWeighted(img, 0.84, layer, 0.16, 0)
        corner_box(img, 58, 72, w - 58, h - 62, color, 18, 2)
        text(img, f"ACTIVE FILTER // {name}", (78, 98), 0.48, color, 1)

    def skeleton(self, img: np.ndarray, obs: HandObservation, drawer: object) -> None:
        color = PINK if obs.gesture == "LOVE LOCK" else GREEN if obs.gesture == "FILTER SWITCH" else CYAN
        drawer.draw_landmarks(
            img, obs.landmarks, mp.solutions.hands.HAND_CONNECTIONS,
            mp.solutions.drawing_utils.DrawingSpec(color=color, thickness=2, circle_radius=3),
            mp.solutions.drawing_utils.DrawingSpec(color=CYAN, thickness=2, circle_radius=2),
        )
        for p in obs.landmarks.landmark:
            cv2.circle(img, (int(p.x * img.shape[1]), int(p.y * img.shape[0])), 3, WHITE, -1, cv2.LINE_AA)
        x1, y1, x2, y2 = obs.bbox
        corner_box(img, x1 - 12, y1 - 12, x2 + 12, y2 + 12, color, 13, 1)
        text(img, f"{obs.label} // {obs.gesture} // {obs.score:.0%}",
             (x1, max(66, y1 - 18)), 0.40, color, 1)

    def portal(self, img: np.ndarray, observations: Sequence[HandObservation], active: bool) -> None:
        if len(observations) < 2 or not active:
            return
        a, b = observations[0].index_tip, observations[1].index_tip
        x1, x2 = sorted((a[0], b[0]))
        y1, y2 = sorted((a[1], b[1]))
        x1, y1 = max(10, x1), max(60, y1)
        x2, y2 = min(img.shape[1] - 10, x2), min(img.shape[0] - 15, y2)
        overlay = img.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (90, 10, 130), -1)
        img[:] = cv2.addWeighted(img, 0.82, overlay, 0.18, 0)
        corner_box(img, x1, y1, x2, y2, PINK, 22, 2)
        text(img, "LOVE PORTAL // TRUST CHANNEL LOCKED", (x1 + 12, y1 + 28), 0.42, PINK, 1)
        glow_line(img, a, b, PINK, 2)

    def hud(self, img: np.ndarray, state: RuntimeState, fps: int,
            hand_count: int, logs: Sequence[str]) -> None:
        h, w = img.shape[:2]
        corner_box(img, 12, 12, w - 12, h - 12, CYAN, 28, 2)
        text(img, "// CYBER HEARTBREAK SECURITY CONSOLE", (30, 42), 0.70, CYAN, 2)
        text(img, "[LOVE.FIREWALL v3.0]", (w - 228, 42), 0.47, PINK, 1)
        cv2.line(img, (30, 57), (w - 30, 57), (75, 95, 125), 1)

        # Panel status kiri.
        x1, y1, x2, y2 = 30, 78, 310, 248
        cv2.rectangle(img, (x1, y1), (x2, y2), DARK_PANEL, -1)
        cv2.rectangle(img, (x1, y1), (x2, y2), BLUE, 1)
        text(img, "SYSTEM STATUS", (x1 + 15, y1 + 27), 0.52, CYAN, 1)
        lines = [
            ("CAMERA", "PAUSED" if state.paused else "ONLINE", GREEN if not state.paused else ORANGE),
            ("HAND NODES", f"{hand_count}/{self.config.max_hands}", WHITE),
            ("FPS", f"{fps:02d}", WHITE),
            ("MODE", state.stable_gesture, PINK if state.stable_gesture == "LOVE LOCK" else RED if state.stable_gesture == "HEARTBREAK" else CYAN),
            ("FILTER", FILTERS[state.filter_index][0], FILTERS[state.filter_index][1]),
        ]
        for i, (key, value, color) in enumerate(lines):
            text(img, f"{key:<10}: {value}", (x1 + 15, y1 + 56 + i * 24), 0.43, color, 1)

        # Panel emosi kanan.
        px = w - 310
        text(img, "EMOTION ANALYZER", (px, 102), 0.52, PINK, 1)
        text(img, "BUCIN / LOVE SIGNAL", (px, 127), 0.42, MUTED, 1)
        cv2.rectangle(img, (px, 137), (w - 42, 149), (25, 35, 58), -1)
        meter = 0.95 if state.love_lock else 0.68 if state.portal_active else 0.30
        cv2.rectangle(img, (px, 137), (px + int((w - 42 - px) * meter), 149), PINK, -1)
        text(img, f"LOVE SIGNAL: {int(meter * 100):03d}%", (px, 174), 0.46, PINK, 1)
        text(img, "HEART FIREWALL : BROKEN", (px, 198), 0.42, RED, 1)
        text(img, "TRUST TOKEN    : EXPIRED", (px, 220), 0.42, MUTED, 1)
        text(img, f"EVENTS         : {state.event_count:03d}", (px, 242), 0.42, WHITE, 1)

        # Terminal log bawah kiri.
        if state.show_logs:
            lx, ly, lw, lh = 30, h - 164, 390, 132
            cv2.rectangle(img, (lx, ly), (lx + lw, ly + lh), (5, 12, 24), -1)
            cv2.rectangle(img, (lx, ly), (lx + lw, ly + lh), (55, 82, 110), 1)
            text(img, "LIVE THREAT / HEART LOG", (lx + 14, ly + 23), 0.43, GREEN, 1)
            for i, line in enumerate(logs[-5:]):
                text(img, line[:53], (lx + 14, ly + 45 + i * 16), 0.34, MUTED, 1)

        if state.recording:
            cv2.circle(img, (w - 38, h - 38), 7, RED, -1)
            text(img, "REC", (w - 80, h - 31), 0.42, RED, 1)
        if state.show_help:
            text(img, "Q/ESC exit | S screenshot | R record | H help | L logs | N/P filter | SPACE pause",
                 (30, h - 14), 0.39, WHITE, 1)

    def render(self, frame: np.ndarray, observations: Sequence[HandObservation],
               state: RuntimeState, fps: int, logs: Sequence[str], drawer: object) -> np.ndarray:
        canvas = frame.copy()
        add_grid(canvas, int(time.time() * 18))
        self.particles.draw(canvas)
        for obs in observations:
            self.skeleton(canvas, obs, drawer)
        state.portal_active = len(observations) >= 2 and sum(o.gesture == "LOVE LOCK" for o in observations) >= 2
        self.portal(canvas, observations, state.portal_active)
        self.apply_filter(canvas, state.filter_index)
        pulse = time.time() * 4
        heart_color = PINK if state.love_lock else RED if state.heartbreak else PURPLE
        draw_heart(canvas, (canvas.shape[1] // 2, 117), 42, heart_color, state.heartbreak, pulse)
        if state.love_lock:
            text(canvas, "HATI TERKUNCI // BUCIN PROTOCOL ACTIVE", (canvas.shape[1] // 2 - 220, 174), 0.48, PINK, 1)
        elif state.heartbreak:
            text(canvas, "ACCESS DENIED // DIA MEMILIH YANG LAIN", (canvas.shape[1] // 2 - 220, 174), 0.46, RED, 1)
        elif state.stable_gesture == "FILTER SWITCH":
            text(canvas, "FILTER SWITCH // MEMORY ROUTING UPDATED", (canvas.shape[1] // 2 - 220, 174), 0.45, GREEN, 1)
        scan_y = int((time.time() * 190) % canvas.shape[0])
        cv2.line(canvas, (20, scan_y), (canvas.shape[1] - 20, scan_y), (100, 180, 255), 1, cv2.LINE_AA)
        add_scanlines(canvas)
        self.hud(canvas, state, fps, len(observations), logs)
        return canvas


# -------------------------- App controller ------------------------------
class CyberHeartbreakConsole:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = RuntimeState(session_start=time.time())
        self.recognizer = GestureRecognizer()
        self.stabilizer = GestureStabilizer()
        self.renderer = CyberRenderer(config)
        self.logs: Deque[str] = deque(maxlen=18)
        self.frame_times: Deque[float] = deque(maxlen=20)
        self.last_log = 0.0
        self.writer: Optional[cv2.VideoWriter] = None
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger("cyber-heartbreak")
        self.telemetry = TelemetryMetrics()
        self.security_engine = SecurityRiskEngine()
        self.add_log("> advanced logic: telemetry and risk engine attached")
        self.add_log("> system: love firewall initialized")
        self.add_log("> security: emotional packet scanner online")

    def add_log(self, message: str) -> None:
        self.logs.append(f"> {message}")

    def open_camera(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.config.camera)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        if not cap.isOpened():
            raise RuntimeError("Kamera tidak dapat dibuka. Cek izin kamera atau --camera.")
        return cap

    def set_recording(self, enabled: bool) -> None:
        if enabled and self.writer is None:
            path = self.config.output_dir / f"cyber_heartbreak_{now_code()}.mp4"
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer = cv2.VideoWriter(str(path), fourcc, 25.0,
                                          (self.config.width, self.config.height))
            if not self.writer.isOpened():
                self.writer.release()
                self.writer = None
                self.add_log("recording: codec unavailable")
                return
            self.state.recording = True
            self.add_log(f"recording started: {path.name}")
        elif not enabled and self.writer is not None:
            self.writer.release()
            self.writer = None
            self.state.recording = False
            self.add_log("recording saved successfully")

    def cycle_filter(self, direction: int) -> None:
        self.state.filter_index = (self.state.filter_index + direction) % len(FILTERS)
        self.state.last_switch = time.time()
        self.state.event_count += 1
        self.add_log(f"filter route: {FILTERS[self.state.filter_index][0].lower()}")

    def handle_gestures(self, observations: Sequence[HandObservation], timestamp: float) -> None:
        raw = "SCANNING"
        if observations:
            priority = {"SCANNING": 0, "PEACE PATCH": 1, "FILTER SWITCH": 2,
                        "HEARTBREAK": 3, "LOVE LOCK": 4}
            raw = max((o.gesture for o in observations), key=lambda g: priority[g])
        stable = self.stabilizer.update(raw)
        self.state.current_gesture = raw
        self.state.stable_gesture = stable
        self.state.love_lock = stable == "LOVE LOCK"
        self.state.heartbreak = stable == "HEARTBREAK"

        if stable == "FILTER SWITCH" and timestamp - self.state.last_switch > 1.15:
            self.cycle_filter(1)
        if stable != self.state.current_gesture:
            return
        if timestamp - self.state.last_event > 0.65:
            if stable != "SCANNING":
                self.state.event_count += 1
                self.add_log(f"gesture detected: {stable.lower()}")
            self.state.last_event = timestamp

    def run(self, record_at_start: bool = False) -> None:
        cap = self.open_camera()
        if record_at_start:
            self.set_recording(True)
        mp_hands = mp.solutions.hands
        drawer = mp.solutions.drawing_utils
        last_timestamp = time.time()

        try:
            with mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=self.config.max_hands,
                model_complexity=self.config.model_complexity,
                min_detection_confidence=self.config.detection_confidence,
                min_tracking_confidence=self.config.tracking_confidence,
            ) as hands:
                while True:
                    if not self.state.paused:
                        ok, frame = cap.read()
                        if not ok:
                            self.add_log("camera: frame read failed")
                            break
                        if self.config.mirror:
                            frame = cv2.flip(frame, 1)
                        frame = cv2.resize(frame, (self.config.width, self.config.height))
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        result = hands.process(rgb)
                        observations: List[HandObservation] = []
                        if result.multi_hand_landmarks:
                            labels = result.multi_handedness or []
                            for i, landmarks in enumerate(result.multi_hand_landmarks):
                                handedness = labels[i] if i < len(labels) else None
                                observations.append(self.recognizer.observe(landmarks, handedness,
                                                                            self.config.width, self.config.height))
                        timestamp = time.time()
                        signal = float(len(observations)) + sum(o.score for o in observations)
                        self.telemetry.metric_01(signal, 1.0, timestamp * 0.01)
                        self.security_engine.risk_01(signal, 0.8, timestamp * 0.02)
                        self.handle_gestures(observations, timestamp)
                        self.frame_times.append(timestamp)
                        elapsed = max(self.frame_times[-1] - self.frame_times[0], 0.001)
                        fps = int(len(self.frame_times) / elapsed) if len(self.frame_times) > 1 else 0
                        output = self.renderer.render(frame, observations, self.state, fps,
                                                      list(self.logs), drawer)
                        if self.state.recording and self.writer is not None:
                            self.writer.write(output)
                    else:
                        output = np.zeros((self.config.height, self.config.width, 3), dtype=np.uint8)
                        output[:] = DARK_PANEL
                        text(output, "CAMERA PAUSED // PRESS SPACE TO RESUME", (self.config.width // 2 - 220, self.config.height // 2), 0.65, ORANGE, 2)

                    cv2.imshow("CYBER HEARTBREAK // SECURITY CONSOLE", output)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (27, ord("q"), ord("Q")):
                        break
                    if key in (ord("h"), ord("H")):
                        self.state.show_help = not self.state.show_help
                    elif key in (ord("l"), ord("L")):
                        self.state.show_logs = not self.state.show_logs
                    elif key in (ord("n"), ord("N")):
                        self.cycle_filter(1)
                    elif key in (ord("p"), ord("P")):
                        self.cycle_filter(-1)
                    elif key in (ord("r"), ord("R")):
                        self.set_recording(not self.state.recording)
                    elif key in (ord("s"), ord("S")):
                        path = self.config.output_dir / f"screenshot_{now_code()}.png"
                        cv2.imwrite(str(path), output)
                        self.add_log(f"screenshot saved: {path.name}")
                    elif key == 32:
                        self.state.paused = not self.state.paused
                        self.add_log("camera paused" if self.state.paused else "camera resumed")
                    last_timestamp = timestamp
        finally:
            self.set_recording(False)
            cap.release()
            cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cyber Heartbreak professional hand tracking console")
    parser.add_argument("--camera", type=int, default=0, help="index kamera, default 0")
    parser.add_argument("--width", type=int, default=1280, help="lebar frame")
    parser.add_argument("--height", type=int, default=720, help="tinggi frame")
    parser.add_argument("--max-hands", type=int, default=2, choices=(1, 2), help="jumlah maksimal tangan")
    parser.add_argument("--no-mirror", action="store_true", help="nonaktifkan mirror webcam")
    parser.add_argument("--record", action="store_true", help="langsung merekam saat mulai")
    parser.add_argument("--output", default="cyber_heartbreak_output", help="folder output screenshot/video")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config = Config(camera=args.camera, width=args.width, height=args.height,
                    max_hands=args.max_hands, mirror=not args.no_mirror,
                    output_dir=Path(args.output))
    try:
        CyberHeartbreakConsole(config).run(record_at_start=args.record)
    except KeyboardInterrupt:
        print("\nProgram dihentikan.")
    except Exception as exc:
        print(f"Error: {exc}")
        print("Pastikan OpenCV, MediaPipe, NumPy terpasang dan izin kamera aktif.")


if __name__ == "__main__":
    main()
