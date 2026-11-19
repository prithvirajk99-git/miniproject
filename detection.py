"""
UrbanEye - AI-Based Pothole Detection Engine
Utilizes Ultralytics YOLO with custom/placeholder weights, confidence filtering,
visual bounding-box annotations, and automatic cooldown-protected image capture.
"""

import os
import cv2
import time
from datetime import datetime
import numpy as np


class PotholeDetector:
    def __init__(self, config: dict):
        self.config = config
        self.model_path = config.get("model_path", "models/best.pt")
        self.confidence_threshold = float(config.get("confidence_threshold", 0.50))
        self.iou_threshold = float(config.get("iou_threshold", 0.45))
        self.cooldown_seconds = float(config.get("cooldown_seconds", 3.0))
        self.save_dir = config.get("save_dir", "detected_potholes")
        self.pothole_class_names = [c.lower() for c in config.get("pothole_class_names", ["pothole", "potholes", "hole"])]

        # State flags and telemetry
        self.model = None
        self.model_loaded = False
        self.model_name = "Not Loaded"
        self.model_status_message = "Initializing..."
        self.is_detection_active = True
        
        # Live detection metrics (updated each frame)
        self.current_pothole_detected = False
        self.current_potholes_count = 0
        self.current_max_confidence = 0.0
        self.total_potholes_detected = 0
        self.last_capture_time = 0.0
        self.recent_captures = []  # List of saved pothole records

        # Ensure save directory exists
        os.makedirs(self.save_dir, exist_ok=True)

        # Load AI model
        self.load_model()

    def load_model(self, custom_path: str = None):
        """Load YOLO model from best.pt or fallback model with error handling."""
        if custom_path:
            self.model_path = custom_path

        try:
            from ultralytics import YOLO

            # 1. First priority: custom trained pothole model
            if os.path.exists(self.model_path) and os.path.getsize(self.model_path) > 1000:
                print(f"[UrbanEye] Loading custom model from: {self.model_path}")
                self.model = YOLO(self.model_path)
                self.model_name = os.path.basename(self.model_path)
                self.model_loaded = True
                self.model_status_message = f"Custom model '{self.model_name}' loaded successfully"
                return True

            # 2. Fallback: placeholder model (e.g., yolov8n.pt)
            fallback = self.config.get("fallback_model_name", "yolov8n.pt")
            print(f"[UrbanEye] Custom model '{self.model_path}' not found. Loading placeholder '{fallback}'...")
            self.model = YOLO(fallback)
            self.model_name = f"{fallback} (Placeholder)"
            self.model_loaded = True
            self.model_status_message = f"Placeholder model active. Replace '{self.model_path}' with your trained pothole weights."
            return True

        except ImportError:
            self.model_loaded = False
            self.model_name = "Ultralytics Not Installed"
            self.model_status_message = "Please install ultralytics (`pip install ultralytics`)"
            print(f"[UrbanEye] Error: {self.model_status_message}")
            return False
        except Exception as e:
            self.model_loaded = False
            self.model_name = "Load Error"
            self.model_status_message = f"Failed to load model: {str(e)}"
            print(f"[UrbanEye] Model load error: {e}")
            return False

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Process a single video frame:
        - Runs YOLO detection if active & model is loaded
        - Filters out low confidence and non-target classes
        - Annotates bounding boxes with confidence %
        - Triggers cooldown-protected automatic snapshot saving
        """
        if frame is None:
            return None

        # Reset per-frame flags
        self.current_pothole_detected = False
        self.current_potholes_count = 0
        self.current_max_confidence = 0.0

        # If detection is stopped or model is not loaded, return clean frame with status text
        if not self.is_detection_active or not self.model_loaded or self.model is None:
            return self._annotate_idle_hud(frame)

        orig_frame = frame.copy()
        annotated_frame = frame.copy()
        detected_potholes = []

        try:
            # Run inference
            results = self.model.predict(
                source=frame,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                verbose=False
            )

            if results and len(results) > 0:
                result = results[0]
                boxes = result.boxes

                if boxes is not None and len(boxes) > 0:
                    names = result.names  # Dictionary of class id -> class name

                    for box in boxes:
                        conf = float(box.conf[0])
                        cls_id = int(box.cls[0])
                        class_name = names.get(cls_id, f"class_{cls_id}").lower()

                        # Determine if this detection is a pothole
                        is_pothole = self._is_pothole_class(class_name, len(names))

                        if is_pothole and conf >= self.confidence_threshold:
                            xyxy = box.xyxy[0].cpu().numpy().astype(int)
                            detected_potholes.append({
                                "box": xyxy,
                                "conf": conf,
                                "class_name": class_name
                            })

            # Update metrics if potholes were detected
            if len(detected_potholes) > 0:
                self.current_pothole_detected = True
                self.current_potholes_count = len(detected_potholes)
                self.current_max_confidence = round(max(p["conf"] for p in detected_potholes) * 100, 1)

                # Draw bounding boxes and HUD
                for item in detected_potholes:
                    x1, y1, x2, y2 = item["box"]
                    conf_pct = item["conf"] * 100
                    self._draw_pothole_box(annotated_frame, x1, y1, x2, y2, conf_pct)

                # Check automatic capture with cooldown
                current_time = time.time()
                if (current_time - self.last_capture_time) >= self.cooldown_seconds:
                    self._save_detection_incident(orig_frame, annotated_frame, self.current_max_confidence)
                    self.last_capture_time = current_time
                    self.total_potholes_detected += len(detected_potholes)

            # Draw HUD bar at the top
            self._draw_status_hud(annotated_frame)

        except Exception as e:
            print(f"[UrbanEye] Inference error: {e}")
            cv2.putText(annotated_frame, f"Inference Error: {str(e)[:40]}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        return annotated_frame

    def _is_pothole_class(self, class_name: str, total_model_classes: int) -> bool:
        """
        Check if detected class is a pothole.
        - If the model is custom-trained (usually 1 or 2 classes like 'pothole', 'potholes'),
          any class or matching name counts as pothole.
        - If placeholder COCO model (80 classes), only target names match.
        """
        if total_model_classes <= 2:
            # Dedicated custom model
            return True
        return any(target in class_name for target in self.pothole_class_names)

    def _draw_pothole_box(self, img: np.ndarray, x1: int, y1: int, x2: int, y2: int, conf_pct: float):
        """Draw a high-visibility, professional bounding box with styled label."""
        # Bright Alert Color: Crimson Red / Bright Amber (BGR: 0, 90, 255)
        color = (0, 70, 255)
        bg_color = (0, 40, 180)
        
        # Bounding rectangle
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

        # Corner accents for a modern tactical HUD look
        corner_len = min(20, (x2 - x1) // 3, (y2 - y1) // 3)
        if corner_len > 4:
            # Top-left
            cv2.line(img, (x1, y1), (x1 + corner_len, y1), (0, 230, 255), 3)
            cv2.line(img, (x1, y1), (x1, y1 + corner_len), (0, 230, 255), 3)
            # Top-right
            cv2.line(img, (x2, y1), (x2 - corner_len, y1), (0, 230, 255), 3)
            cv2.line(img, (x2, y1), (x2, y1 + corner_len), (0, 230, 255), 3)
            # Bottom-left
            cv2.line(img, (x1, y2), (x1 + corner_len, y2), (0, 230, 255), 3)
            cv2.line(img, (x1, y2), (x1, y2 - corner_len), (0, 230, 255), 3)
            # Bottom-right
            cv2.line(img, (x2, y2), (x2 - corner_len, y2), (0, 230, 255), 3)
            cv2.line(img, (x2, y2), (x2 - corner_len, y2), (0, 230, 255), 3)

        # Label tag
        label = f"POTHOLE {conf_pct:.1f}%"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.55
        thickness = 1
        (label_w, label_h), baseline = cv2.getTextSize(label, font, scale, thickness)

        # Ensure label fits within top frame
        tag_y1 = max(0, y1 - label_h - 10)
        tag_y2 = tag_y1 + label_h + 8
        tag_x2 = min(img.shape[1], x1 + label_w + 14)

        # Filled badge background
        cv2.rectangle(img, (x1, tag_y1), (tag_x2, tag_y2), bg_color, -1)
        cv2.rectangle(img, (x1, tag_y1), (tag_x2, tag_y2), (0, 230, 255), 1)

        # Badge text
        cv2.putText(img, label, (x1 + 6, tag_y2 - 5), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

    def _draw_status_hud(self, img: np.ndarray):
        """Draw an unobtrusive top status banner on the stream."""
        h, w = img.shape[:2]
        
        # Semi-transparent top banner
        overlay = img.copy()
        cv2.rectangle(overlay, (0, 0), (w, 36), (15, 20, 26), -1)
        cv2.addWeighted(overlay, 0.75, img, 0.25, 0, img)

        font = cv2.FONT_HERSHEY_SIMPLEX
        if self.current_pothole_detected:
            # Danger alert
            badge_color = (0, 50, 230)
            status_text = f"! POTHOLE DETECTED ({self.current_potholes_count}) - {self.current_max_confidence}%"
        else:
            # Safe status
            badge_color = (40, 180, 80)
            status_text = "CLEAR - NO POTHOLE"

        cv2.putText(img, status_text, (15, 24), font, 0.55, badge_color, 2, cv2.LINE_AA)

        # Right side: threshold and total count
        right_info = f"Threshold: {int(self.confidence_threshold * 100)}% | Total: {self.total_potholes_detected}"
        (rw, rh), _ = cv2.getTextSize(right_info, font, 0.45, 1)
        cv2.putText(img, right_info, (w - rw - 15, 23), font, 0.45, (200, 210, 220), 1, cv2.LINE_AA)

    def _annotate_idle_hud(self, img: np.ndarray) -> np.ndarray:
        """Annotate frame when detection is paused or model not loaded."""
        annotated = img.copy()
        h, w = annotated.shape[:2]

        overlay = annotated.copy()
        cv2.rectangle(overlay, (0, 0), (w, 36), (20, 25, 30), -1)
        cv2.addWeighted(overlay, 0.8, annotated, 0.2, 0, annotated)

        msg = "AI DETECTION: PAUSED" if not self.is_detection_active else f"AI MODEL: {self.model_name}"
        color = (130, 140, 150) if not self.is_detection_active else (80, 130, 255)
        cv2.putText(annotated, msg, (15, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
        return annotated

    def _save_detection_incident(self, orig_frame: np.ndarray, annotated_frame: np.ndarray, conf_pct: float):
        """Save original and annotated images with timestamp and record event."""
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")[:19]  # YYYYMMDD_HHMMSS_mmm
        display_time = now.strftime("%Y-%m-%d %H:%M:%S")

        orig_filename = f"pothole_{timestamp_str}_orig.jpg"
        annotated_filename = f"pothole_{timestamp_str}_annotated.jpg"

        orig_filepath = os.path.join(self.save_dir, orig_filename)
        annotated_filepath = os.path.join(self.save_dir, annotated_filename)

        try:
            cv2.imwrite(orig_filepath, orig_frame)
            cv2.imwrite(annotated_filepath, annotated_frame)

            # Store in recent captures
            record = {
                "id": timestamp_str,
                "timestamp": display_time,
                "orig_filename": orig_filename,
                "annotated_filename": annotated_filename,
                "orig_url": f"/detected_potholes/{orig_filename}",
                "annotated_url": f"/detected_potholes/{annotated_filename}",
                "confidence": conf_pct,
                "potholes_count": self.current_potholes_count
            }
            self.recent_captures.insert(0, record)
            # Keep max 50 recent records in memory
            if len(self.recent_captures) > 50:
                self.recent_captures.pop()

            print(f"[UrbanEye] Incident captured! Saved {annotated_filename} (Confidence: {conf_pct}%)")
        except Exception as e:
            print(f"[UrbanEye] Error saving detection images: {e}")
