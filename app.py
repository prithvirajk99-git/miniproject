"""
UrbanEye - AI-Based Road Pothole Detection System
Main Flask Application Server
"""

import os
import time
import cv2
from datetime import datetime
from flask import Flask, render_template, Response, request, jsonify, send_from_directory

from config import load_config, save_config, BASE_DIR
from camera import ESP32StreamReader
from detection import PotholeDetector

app = Flask(__name__)

# Initialize configuration
config = load_config()

# Initialize Hardware Camera Stream Reader
camera = ESP32StreamReader(config.get("esp32_stream_url"))
camera.start()

# Initialize AI Pothole Detector
detector = PotholeDetector(config)


def generate_frames():
    """Generator function that yields MJPEG video stream with detections."""
    while True:
        try:
            # 1. Fetch frame from ESP32 camera reader
            frame, is_connected = camera.get_frame()

            # 2. Run AI detection on the frame if camera is connected
            if is_connected:
                processed_frame = detector.process_frame(frame)
            else:
                processed_frame = frame  # Displays disconnected status screen

            # 3. Encode to JPEG
            ret, buffer = cv2.imencode(".jpg", processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ret:
                time.sleep(0.05)
                continue

            frame_bytes = buffer.tobytes()

            # 4. Stream as multipart MJPEG
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")

            # Regulate frame rate to ~30 FPS
            time.sleep(0.033)

        except Exception as e:
            time.sleep(0.1)


@app.route("/")
def index():
    """Render main UrbanEye monitoring dashboard."""
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    """MJPEG live camera stream route."""
    return Response(generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/status")
def api_status():
    """Return real-time telemetry and status as JSON."""
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
    """Get or update configuration dynamically."""
    global config
    if request.method == "POST":
        data = request.get_json() or {}
        updates = {}

        # 1. Update Camera URL
        if "esp32_stream_url" in data:
            new_url = data["esp32_stream_url"].strip()
            if new_url:
                updates["esp32_stream_url"] = new_url
                camera.update_url(new_url)

        # 2. Update Confidence Threshold
        if "confidence_threshold" in data:
            conf = float(data["confidence_threshold"])
            conf = max(0.10, min(0.95, conf))
            updates["confidence_threshold"] = conf
            detector.confidence_threshold = conf

        # 3. Update Cooldown
        if "cooldown_seconds" in data:
            cooldown = float(data["cooldown_seconds"])
            cooldown = max(0.5, min(30.0, cooldown))
            updates["cooldown_seconds"] = cooldown
            detector.cooldown_seconds = cooldown

        config = save_config(updates)
        return jsonify({"success": True, "config": config})

    return jsonify({"success": True, "config": config})


@app.route("/api/control/start", methods=["POST"])
def api_control_start():
    """Start / resume live AI detection."""
    detector.is_detection_active = True
    return jsonify({"success": True, "detection_active": True})


@app.route("/api/control/stop", methods=["POST"])
def api_control_stop():
    """Stop / pause live AI detection."""
    detector.is_detection_active = False
    return jsonify({"success": True, "detection_active": False})


@app.route("/api/control/snapshot", methods=["POST"])
def api_control_snapshot():
    """Manually trigger a snapshot of current camera frame."""
    frame, is_connected = camera.get_frame()
    if not is_connected or frame is None:
        return jsonify({"success": False, "message": "Camera is currently disconnected."})

    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
    orig_name = f"manual_{timestamp_str}_orig.jpg"
    annotated_name = f"manual_{timestamp_str}_annotated.jpg"

    annotated = detector.process_frame(frame.copy())
    save_dir = config.get("save_dir", "detected_potholes")

    cv2.imwrite(os.path.join(save_dir, orig_name), frame)
    cv2.imwrite(os.path.join(save_dir, annotated_name), annotated)

    record = {
        "id": timestamp_str,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "orig_filename": orig_name,
        "annotated_filename": annotated_name,
        "orig_url": f"/detected_potholes/{orig_name}",
        "annotated_url": f"/detected_potholes/{annotated_name}",
        "confidence": detector.current_max_confidence,
        "potholes_count": detector.current_potholes_count
    }
    detector.recent_captures.insert(0, record)
    return jsonify({"success": True, "record": record})


@app.route("/api/detections")
def api_detections():
    """Return list of recent captured incidents."""
    return jsonify({
        "success": True,
        "total": detector.total_potholes_detected,
        "captures": detector.recent_captures
    })


@app.route("/detected_potholes/<path:filename>")
def serve_detected_image(filename):
    """Serve captured pothole image files."""
    return send_from_directory(config.get("save_dir", "detected_potholes"), filename)


if __name__ == "__main__":
    host = config.get("server_host", "0.0.0.0")
    port = int(config.get("server_port", 5000))
    print("=" * 60)
    print(" UrbanEye - AI Road Pothole Detection System")
    print(f" Dashboard URL : http://localhost:{port}")
    print(f" ESP32 Camera  : {config.get('esp32_stream_url')}")
    print(f" AI Model      : {config.get('model_path')}")
    print("=" * 60)
    app.run(host=host, port=port, debug=False, threaded=True)
