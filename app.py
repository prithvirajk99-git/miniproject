"""
UrbanEye - Main Flask Application Server (Optimized)
Fixes:
  1. YOLO detection runs in a dedicated background thread — stream is never blocked.
  2. Flask streams the latest annotated frame at full speed.
  3. No sleep() inside stream generator — maximum throughput.
  4. Added /api/control/reload endpoint for live model hot-swap.
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

# Shared annotated frame buffer (produced by detection thread, read by stream)
_annotated_lock = threading.Lock()
_annotated_frame = None


# ------------------------------------------------------------------ #
#  Dedicated Detection Thread (decoupled from streaming)
# ------------------------------------------------------------------ #

def detection_worker():
    """
    Runs YOLO inference in a tight loop on whatever the camera returns.
    Result is stored in _annotated_frame for the MJPEG stream to pick up.
    """
    global _annotated_frame
    while True:
        try:
            frame, is_connected = camera.get_frame()

            if is_connected:
                processed = detector.process_frame(frame)
            else:
                processed = frame  # Shows disconnected status screen

            with _annotated_lock:
                _annotated_frame = processed

        except Exception as e:
            print(f"[Detection Worker] Error: {e}")
            time.sleep(0.05)


# Start the background detection thread
_det_thread = threading.Thread(target=detection_worker, daemon=True, name="DetectionWorker")
_det_thread.start()


# ------------------------------------------------------------------ #
#  MJPEG Stream Generator (reads pre-processed frame, never blocks)
# ------------------------------------------------------------------ #

def generate_frames():
    global _annotated_frame
    while True:
        try:
            with _annotated_lock:
                frame = _annotated_frame

            if frame is None:
                time.sleep(0.01)
                continue

            ret, buffer = cv2.imencode(
                ".jpg", frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), 70]   # 70 quality = fast + small
            )
            if not ret:
                time.sleep(0.01)
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + buffer.tobytes()
                + b"\r\n"
            )

        except Exception:
            time.sleep(0.05)


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
    return jsonify({"success": True, "detection_active": True})


@app.route("/api/control/stop", methods=["POST"])
def api_control_stop():
    detector.is_detection_active = False
    return jsonify({"success": True, "detection_active": False})


@app.route("/api/control/reload", methods=["POST"])
def api_control_reload():
    """Hot-reload AI model (useful after replacing best.pt without restart)."""
    success = detector.load_model()
    return jsonify({
        "success": success,
        "model_name": detector.model_name,
        "message": detector.model_status_message
    })


@app.route("/api/control/snapshot", methods=["POST"])
def api_control_snapshot():
    frame, is_connected = camera.get_frame()
    if not is_connected or frame is None:
        return jsonify({"success": False, "message": "Camera is currently disconnected."})

    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
    orig_name = f"manual_{ts}_orig.jpg"
    ann_name = f"manual_{ts}_annotated.jpg"

    annotated = detector.process_frame(frame.copy())
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


# ------------------------------------------------------------------ #
#  Entry Point
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    host = config.get("server_host", "0.0.0.0")
    port = int(config.get("server_port", 5000))

    print("=" * 60)
    print("  UrbanEye - AI Road Pothole Detection System")
    print(f"  Dashboard  : http://localhost:{port}")
    print(f"  ESP32 URL  : {config.get('esp32_stream_url')}")
    print(f"  AI Model   : {detector.model_name}")
    print("=" * 60)

    app.run(host=host, port=port, debug=False, threaded=True)
