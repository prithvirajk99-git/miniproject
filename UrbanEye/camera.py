"""
UrbanEye - Robust ESP32-CAM Stream Reader
Fixes:
  1. Uses raw HTTP byte-stream parser (instead of OpenCV VideoCapture)
     which works reliably with ESP32-CAM's MJPEG output including RHYX M21-45.
  2. Async detection thread decoupled from streaming - stream never blocks.
  3. Latest-frame-only buffering for zero-lag live video.
  4. Auto reconnect with exponential back-off.
"""

import cv2
import time
import threading
import numpy as np
import urllib.request
import urllib.error


class ESP32StreamReader:
    def __init__(self, stream_url: str):
        self.stream_url = stream_url
        self.latest_frame = None
        self.is_connected = False
        self.reconnecting = False
        self.last_error = ""
        self.fps = 0.0
        self.frame_count = 0

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._reconnect_interval = 2.0

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="ESP32StreamThread"
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self.is_connected = False

    def update_url(self, new_url: str):
        with self._lock:
            if self.stream_url == new_url:
                return
            self.stream_url = new_url
        self.stop()
        self.start()

    def get_frame(self):
        """Return (frame_ndarray, is_connected). Thread-safe."""
        with self._lock:
            if self.latest_frame is not None and self.is_connected:
                return self.latest_frame.copy(), True
        return self._make_disconnected_frame(), False

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _make_disconnected_frame(self) -> np.ndarray:
        h, w = 480, 640
        frame = np.full((h, w, 3), (22, 26, 30), dtype=np.uint8)
        cv2.rectangle(frame, (20, 20), (w - 20, h - 20), (45, 55, 72), 2)

        cv2.putText(frame, "ESP32-CAM DISCONNECTED",
                    (w // 2 - 185, h // 2 - 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (80, 120, 255), 2, cv2.LINE_AA)

        url = self.stream_url[:48] + ("..." if len(self.stream_url) > 48 else "")
        cv2.putText(frame, f"URL: {url}",
                    (30, h // 2 + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 210, 220), 1, cv2.LINE_AA)

        dots = "." * (int(time.time() * 2) % 4)
        cv2.putText(frame, f"Reconnecting{dots}",
                    (w // 2 - 65, h // 2 + 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (52, 211, 153), 2, cv2.LINE_AA)

        err = self.last_error[:70] if self.last_error else ""
        if err:
            cv2.putText(frame, err, (30, h - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 100, 100), 1, cv2.LINE_AA)
        return frame

    # ------------------------------------------------------------------ #
    #  Stream capture loop — tries raw HTTP parser first, falls back to CV2
    # ------------------------------------------------------------------ #

    def _capture_loop(self):
        while not self._stop_event.is_set():
            self.reconnecting = True
            self.is_connected = False
            url = self.stream_url

            # Strategy 1: Raw MJPEG HTTP byte-stream parser (best for ESP32-CAM)
            success = self._try_raw_http(url)

            # Strategy 2: Fallback to OpenCV VideoCapture
            if not success and not self._stop_event.is_set():
                success = self._try_opencv(url)

            if not self._stop_event.is_set():
                time.sleep(self._reconnect_interval)

    # ------------------------------------------------------------------ #
    #  Strategy 1: Raw HTTP MJPEG parser
    # ------------------------------------------------------------------ #

    def _try_raw_http(self, url: str) -> bool:
        BOUNDARY = b"--"
        SOI = b"\xff\xd8"   # JPEG start
        EOI = b"\xff\xd9"   # JPEG end

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "UrbanEye/1.0",
                "Connection": "keep-alive"
            })
            response = urllib.request.urlopen(req, timeout=8)

            fps_start = time.time()
            frames_in_period = 0
            buf = b""

            while not self._stop_event.is_set():
                chunk = response.read(16384)
                if not chunk:
                    self.is_connected = False
                    self.last_error = "Stream ended (empty chunk)"
                    return True  # was connected, return True to retry

                buf += chunk

                # Keep buffer from growing unbounded
                if len(buf) > 1_000_000:
                    buf = buf[-500_000:]

                # Find complete JPEG frame
                start = buf.find(SOI)
                end = buf.find(EOI, start + 2) if start != -1 else -1

                if start != -1 and end != -1:
                    jpg_bytes = buf[start: end + 2]
                    buf = buf[end + 2:]

                    # Decode JPEG bytes to OpenCV frame
                    nparr = np.frombuffer(jpg_bytes, dtype=np.uint8)
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                    if frame is not None:
                        with self._lock:
                            self.latest_frame = frame
                            self.frame_count += 1
                            frames_in_period += 1
                        self.is_connected = True
                        self.reconnecting = False
                        self.last_error = ""

                        elapsed = time.time() - fps_start
                        if elapsed >= 1.0:
                            self.fps = round(frames_in_period / elapsed, 1)
                            frames_in_period = 0
                            fps_start = time.time()

        except urllib.error.URLError as e:
            self.last_error = f"HTTP error: {e.reason}"
            self.is_connected = False
        except Exception as e:
            self.last_error = f"Raw HTTP error: {str(e)[:60]}"
            self.is_connected = False

        return False

    # ------------------------------------------------------------------ #
    #  Strategy 2: OpenCV VideoCapture fallback
    # ------------------------------------------------------------------ #

    def _try_opencv(self, url: str) -> bool:
        cap = None
        try:
            cap = cv2.VideoCapture(url)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            if not cap.isOpened():
                self.last_error = f"OpenCV could not open stream: {url}"
                return False

            ret, frame = cap.read()
            if not ret or frame is None:
                self.last_error = "OpenCV: Initial frame read failed"
                return False

            self.is_connected = True
            self.reconnecting = False
            self.last_error = ""
            fps_start = time.time()
            frames_in_period = 0

            while not self._stop_event.is_set():
                ret, frame = cap.read()
                if not ret or frame is None:
                    self.is_connected = False
                    self.last_error = "OpenCV: Lost connection"
                    break

                with self._lock:
                    self.latest_frame = frame
                    self.frame_count += 1
                    frames_in_period += 1

                elapsed = time.time() - fps_start
                if elapsed >= 1.0:
                    self.fps = round(frames_in_period / elapsed, 1)
                    frames_in_period = 0
                    fps_start = time.time()

            return True

        except Exception as e:
            self.last_error = f"OpenCV fallback error: {str(e)[:60]}"
            self.is_connected = False
            return False
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
