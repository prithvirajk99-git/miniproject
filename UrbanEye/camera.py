"""
UrbanEye - ESP32-CAM Stream Reader & Manager
Handles continuous MJPEG stream reception, thread-safe frame access,
zero-latency latest-frame buffering, and automatic reconnection.
"""

import cv2
import time
import threading
import numpy as np


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
        self._reconnect_interval = 2.5  # seconds between reconnect attempts

    def start(self):
        """Start the background streaming worker thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="ESP32StreamThread")
        self._thread.start()

    def stop(self):
        """Stop the streaming worker thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.is_connected = False

    def update_url(self, new_url: str):
        """Update stream URL dynamically and trigger reconnection."""
        with self._lock:
            if self.stream_url == new_url:
                return
            self.stream_url = new_url
            self.is_connected = False
        # Restart reader with new URL
        self.stop()
        self.start()

    def get_frame(self):
        """Return the most recent frame (or a generated placeholder if disconnected)."""
        with self._lock:
            if self.latest_frame is not None and self.is_connected:
                return self.latest_frame.copy(), True
            else:
                return self._create_disconnected_frame(), False

    def _create_disconnected_frame(self) -> np.ndarray:
        """Create a clear status banner frame when the camera is not connected."""
        height, width = 480, 640
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Dark modern slate background
        frame[:] = (22, 26, 30)

        # Pulse indicator / crosshair design
        cv2.rectangle(frame, (20, 20), (width - 20, height - 20), (45, 55, 72), 2)
        cv2.line(frame, (width // 2 - 30, height // 2 - 60), (width // 2 + 30, height // 2 - 60), (70, 80, 95), 1)

        # Disconnected icon / text
        title = "ESP32-CAM DISCONNECTED"
        cv2.putText(frame, title, (width // 2 - 190, height // 2 - 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 120, 255), 2, cv2.LINE_AA)

        info1 = f"Attempting connection to:"
        cv2.putText(frame, info1, (width // 2 - 160, height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 174, 192), 1, cv2.LINE_AA)

        # Show stream URL
        url_text = self.stream_url if len(self.stream_url) < 45 else self.stream_url[:42] + "..."
        cv2.putText(frame, url_text, (width // 2 - (len(url_text) * 5), height // 2 + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (226, 232, 240), 1, cv2.LINE_AA)

        hint = "Verify ESP32-CAM power, Wi-Fi IP and port :81/stream"
        cv2.putText(frame, hint, (width // 2 - 210, height // 2 + 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (113, 128, 150), 1, cv2.LINE_AA)

        # Animated dots based on time
        dots = "." * (int(time.time() * 2) % 4)
        cv2.putText(frame, f"Reconnecting{dots}", (width // 2 - 60, height // 2 + 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (52, 211, 153), 2, cv2.LINE_AA)

        return frame

    def _capture_loop(self):
        """Worker loop that continuously captures frames and handles reconnects."""
        while not self._stop_event.is_set():
            cap = None
            try:
                self.reconnecting = True
                self.last_error = f"Connecting to {self.stream_url}..."
                
                # Open capture stream
                cap = cv2.VideoCapture(self.stream_url)
                
                # Reduce buffer size to ensure zero lag on MJPEG streams
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass

                # Check if stream opened successfully
                if not cap.isOpened():
                    self.is_connected = False
                    self.last_error = f"Failed to open video stream at {self.stream_url}"
                    time.sleep(self._reconnect_interval)
                    continue

                # Test read first frame
                ret, frame = cap.read()
                if not ret or frame is None:
                    self.is_connected = False
                    self.last_error = "Unable to read initial frame from ESP32-CAM"
                    cap.release()
                    time.sleep(self._reconnect_interval)
                    continue

                # Successfully connected!
                self.is_connected = True
                self.reconnecting = False
                self.last_error = ""
                fps_start_time = time.time()
                frames_in_period = 0

                while not self._stop_event.is_set():
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        self.is_connected = False
                        self.last_error = "Lost connection to ESP32-CAM stream"
                        break

                    # Update latest frame thread-safely
                    with self._lock:
                        self.latest_frame = frame
                        self.frame_count += 1
                        frames_in_period += 1

                    # FPS calculation
                    elapsed = time.time() - fps_start_time
                    if elapsed >= 1.0:
                        self.fps = round(frames_in_period / elapsed, 1)
                        frames_in_period = 0
                        fps_start_time = time.time()

            except Exception as e:
                self.is_connected = False
                self.last_error = str(e)
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

            if not self._stop_event.is_set():
                time.sleep(self._reconnect_interval)
