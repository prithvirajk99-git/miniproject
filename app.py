"""
UrbanEye - High-Performance App Server
FPS Fix Strategy:
  - Stream thread: sends raw camera frames to browser at FULL camera FPS (no blocking)
  - Detection thread: runs YOLO async on every 3rd frame at imgsz=320 (~10 FPS detection)
  - Cached boxes: last detection bounding boxes are drawn onto every streamed frame
  - Net result: smooth 15-25 FPS video stream with real-time detection overlay
"""

import os
import time
import cv2
import threading
from datetime import datetime
from flask import Flask, render_template, Response, request, jsonify, send_from_directory

from config import load_config, save_config, BASE_DIR
from camera import ESP32StreamReader
from detection import PotholeDetector

app = Flask(__name__)

# ------------------------------------------------------------------ #
#  Initialize core components
# ------------------------------------------------------------------ #
config = load_config()
camera = ESP32StreamReader(config.get("esp32_stream_url"))
camera.start()
detector = PotholeDetector(config)

# ------------------------------------------------------------------ #
#  Shared state: cached detection boxes drawn on every streamed frame
# ------------------------------------------------------------------ #
_cache_lock = threading.Lock()
_cached_boxes = []          # list of {box, conf, label} from last YOLO run
_pothole_active = False     # True if last inference had potholes

# Detection frame counter — only run YOLO every N frames
_DETECT_EVERY_N = 3         # run inference every 3rd frame (~10 FPS detection on CPU)
_frame_counter = 0

# ------------------------------------------------------------------ #
#  Dedicated Detection Thread (async, never blocks stream)
# ------------------------------------------------------------------ #

def detection_worker():
    global _cached_boxes, _pothole_active, _frame_counter
    while True:
        try:
            frame, is_connected = camera.get_frame()

            if not is_connected or not detector.is_detection_active or not detector.model_loaded:
                with _cache_lock:
                    _cached_boxes = []
                    _pothole_active = False
                time.sleep(0.05)
                continue

            _frame_counter += 1

            # Only run YOLO inference every Nth frame
            if _frame_counter % _DETECT_EVERY_N != 0:
                time.sleep(0.005)
                continue

            # Resize to 320 for fast inference, scale boxes back after
            orig_h, orig_w = frame.shape[:2]
            infer_size = 320
            scale_x = orig_w / infer_size
            scale_y = orig_h / infer_size
            small = cv2.resize(frame, (infer_size, infer_size))

            results = detector.model.predict(
                source=small,
                conf=detector.confidence_threshold,
                iou=detector.iou_threshold,
                imgsz=infer_size,
                verbose=False
            )

            new_boxes = []
            if results and results[0].boxes is not None:
                res = results[0]
                names = res.names
                for box in res.boxes:
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    class_name = names.get(cls_id, "pothole").lower()

                    if not detector._is_pothole_class(class_name, len(names)):
                        continue
                    if conf < detector.confidence_threshold:
                        continue

                    # Scale bounding box back to original frame size
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    x1 = int(x1 * scale_x)
                    y1 = int(y1 * scale_y)
                    x2 = int(x2 * scale_x)
                    y2 = int(y2 * scale_y)

                    new_boxes.append({
                        "box": (x1, y1, x2, y2),
                        "conf": conf,
                        "label": f"POTHOLE {conf*100:.1f}%"
                    })

            with _cache_lock:
                _cached_boxes = new_boxes
                _pothole_active = len(new_boxes) > 0

            # Update detector metrics
            detector.current_pothole_detected = _pothole_active
            detector.current_potholes_count = len(new_boxes)
            if new_boxes:
                detector.current_max_confidence = round(
                    max(b["conf"] for b in new_boxes) * 100, 1
                )
                # Auto-capture with cooldown
                now = time.time()
                if (now - detector.last_capture_time) >= detector.cooldown_seconds:
                    detector._save_detection_incident(frame, _draw_boxes(frame.copy(), new_boxes), detector.current_max_confidence)
                    detector.last_capture_time = now
                    detector.total_potholes_detected += len(new_boxes)
            else:
                detector.current_max_confidence = 0.0

        except Exception as e:
            print(f"[DetectionWorker] Error: {e}")
            time.sleep(0.1)


def _draw_boxes(frame, boxes):
    """Draw cached detection boxes onto a frame."""
    for item in boxes:
        x1, y1, x2, y2 = item["box"]
        label = item["label"]
        conf = item["conf"]

        # Color: more confident = brighter red, less = orange
        intensity = int(100 + 155 * conf)
        color = (0, int(255 - intensity * 0.5), intensity)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Corner accents
        cl = min(16, (x2 - x1) // 4, (y2 - y1) // 4)
        if cl > 3:
            for px, py in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
                dx1 = cl if px == x1 else -cl
                dy1 = cl if py == y1 else -cl
                cv2.line(frame, (px, py), (px + dx1, py), (0, 230, 255), 2)
                cv2.line(frame, (px, py), (px, py + dy1), (0, 230, 255), 2)

        # Label badge
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), _ = cv2.getTextSize(label, font, 0.5, 1)
        ty = max(0, y1 - th - 8)
        cv2.rectangle(frame, (x1, ty), (x1 + tw + 10, ty + th + 8), (0, 40, 180), -1)
        cv2.rectangle(frame, (x1, ty), (x1 + tw + 10, ty + th + 8), (0, 200, 255), 1)
        cv2.putText(frame, label, (x1 + 5, ty + th + 3), font, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    return frame


def _draw_hud(frame, boxes_active):
    """Draw minimal top status HUD."""
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 32), (10, 15, 20), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    if boxes_active:
        txt = f"! POTHOLE DETECTED ({detector.current_potholes_count})  {detector.current_max_confidence}%"
        cv2.putText(frame, txt, (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 60, 255), 2, cv2.LINE_AA)
    else:
        txt = "CLEAR - NO POTHOLE"
        cv2.putText(frame, txt, (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (40, 200, 90), 2, cv2.LINE_AA)

    fps_txt = f"{camera.fps:.0f} FPS | Thresh {int(detector.confidence_threshold*100)}%"
    (fw, _), _ = cv2.getTextSize(fps_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
    cv2.putText(frame, fps_txt, (w - fw - 10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 180, 200), 1, cv2.LINE_AA)

    return frame


# Start background detection worker
_det_thread = threading.Thread(target=detection_worker, daemon=True, name="DetectionWorker")
_det_thread.start()


# ------------------------------------------------------------------ #
#  MJPEG Stream Generator — full FPS, overlays cached boxes
# ------------------------------------------------------------------ #

def generate_frames():
    while True:
        try:
            frame, is_connected = camera.get_frame()

            if not is_connected:
                # Show disconnected screen
                processed = frame
            else:
                # Overlay latest cached detection boxes (non-blocking read)
                with _cache_lock:
                    boxes = list(_cached_boxes)
                    active = _pothole_active

                processed = _draw_boxes(frame, boxes)
                processed = _draw_hud(processed, active)

            # Encode: quality=65 gives crisp video at ~2x smaller file size
            ret, buffer = cv2.imencode(
                ".jpg", processed,
                [int(cv2.IMWRITE_JPEG_QUALITY), 65]
            )
            if not ret:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + buffer.tobytes()
                + b"\r\n"
            )

        except Exception as e:
            time.sleep(0.03)


# ------------------------------------------------------------------ #
#  Flask Routes
# ------------------------------------------------------------------ #

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/api/status")
def api_status():
    return jsonify({
        "camera_connected": camera.is_connected,
        "reconnecting": camera.reconnecting,
        "last_error": camera.last_error,
        "camera_url": camera.stream_url,
        "fps": camera.fps,
        "model_loaded": detector.model_loaded,
        "model_name": detector.model_name,
        "model_status_message": detector.model_status_message,
        "detection_active": detector.is_detection_active,
        "pothole_detected": detector.current_pothole_detected,
        "current_potholes_count": detector.current_potholes_count,
        "total_potholes_detected": detector.total_potholes_detected,
        "max_confidence": detector.current_max_confidence,
        "confidence_threshold": detector.confidence_threshold,
        "cooldown_seconds": detector.cooldown_seconds
    })


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    global config
    if request.method == "POST":
        data = request.get_json() or {}
        updates = {}
        if "esp32_stream_url" in data:
            new_url = data["esp32_stream_url"].strip()
            if new_url:
                updates["esp32_stream_url"] = new_url
                camera.update_url(new_url)
        if "confidence_threshold" in data:
            conf = max(0.10, min(0.95, float(data["confidence_threshold"])))
            updates["confidence_threshold"] = conf
            detector.confidence_threshold = conf
        if "cooldown_seconds" in data:
            cooldown = max(0.5, min(30.0, float(data["cooldown_seconds"])))
            updates["cooldown_seconds"] = cooldown
            detector.cooldown_seconds = cooldown
        config = save_config(updates)
        return jsonify({"success": True, "config": config})
    return jsonify({"success": True, "config": config})


@app.route("/api/control/start", methods=["POST"])
def api_control_start():
    detector.is_detection_active = True
    return jsonify({"success": True})


@app.route("/api/control/stop", methods=["POST"])
def api_control_stop():
    detector.is_detection_active = False
    with _cache_lock:
        _cached_boxes.clear()
    return jsonify({"success": True})


@app.route("/api/control/reload", methods=["POST"])
def api_control_reload():
    success = detector.load_model()
    return jsonify({"success": success, "model_name": detector.model_name})


@app.route("/api/control/snapshot", methods=["POST"])
def api_control_snapshot():
    frame, is_connected = camera.get_frame()
    if not is_connected or frame is None:
        return jsonify({"success": False, "message": "Camera disconnected."})
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
    orig_name = f"manual_{ts}_orig.jpg"
    ann_name  = f"manual_{ts}_annotated.jpg"
    with _cache_lock:
        boxes = list(_cached_boxes)
    annotated = _draw_boxes(frame.copy(), boxes)
    save_dir = config.get("save_dir", "detected_potholes")
    cv2.imwrite(os.path.join(save_dir, orig_name), frame)
    cv2.imwrite(os.path.join(save_dir, ann_name), annotated)
    record = {
        "id": ts,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "orig_filename": orig_name,
        "annotated_filename": ann_name,
        "orig_url": f"/detected_potholes/{orig_name}",
        "annotated_url": f"/detected_potholes/{ann_name}",
        "confidence": detector.current_max_confidence,
        "potholes_count": detector.current_potholes_count
    }
    detector.recent_captures.insert(0, record)
    return jsonify({"success": True, "record": record})


@app.route("/api/detections")
def api_detections():
    return jsonify({
        "success": True,
        "total": detector.total_potholes_detected,
        "captures": detector.recent_captures
    })


@app.route("/detected_potholes/<path:filename>")
def serve_detected_image(filename):
    return send_from_directory(config.get("save_dir", "detected_potholes"), filename)


if __name__ == "__main__":
    host = config.get("server_host", "0.0.0.0")
    port = int(config.get("server_port", 5000))
    print("=" * 60)
    print("  UrbanEye - AI Road Pothole Detection System")
    print(f"  Dashboard  : http://localhost:{port}")
    print(f"  ESP32 URL  : {config.get('esp32_stream_url')}")
    print(f"  AI Model   : {detector.model_name}")
    print(f"  Detection  : Every {_DETECT_EVERY_N} frames at imgsz=320 (~10 FPS)")
    print("=" * 60)
    app.run(host=host, port=port, debug=False, threaded=True)
