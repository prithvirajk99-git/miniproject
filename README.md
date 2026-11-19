# UrbanEye – AI-Based Road Pothole Detection Prototype

UrbanEye is an edge-connected AI road pothole detection system using an **ESP32-CAM (AI-Thinker OV2640)** as the primary hardware camera input and **Ultralytics YOLO** for real-time pothole identification, automatic incident image capture, and live telemetry monitoring.

---

## 🌟 Key Features

- **Hardware Camera Input**: Directly captures real-time video stream from an ESP32-CAM over HTTP/MJPEG (`http://<esp32-ip>:81/stream`).
- **Live Reconnection Engine**: Zero-lag threaded stream consumer that buffers only the latest frame, detects camera disconnections, and automatically re-establishes connection in the background.
- **AI Pothole Detection**: Powered by Ultralytics YOLO with real-time confidence calculation, tactical corner-accented bounding boxes, and live confidence threshold calibration.
- **Automatic Cooldown Capture**: When a pothole is detected, UrbanEye automatically saves both the original raw frame and the annotated frame with timestamps into `detected_potholes/`. A configurable cooldown prevents duplicate captures for the same pothole.
- **Modern Telemetry Dashboard**: Responsive dark HUD displaying live stream, detection status, current frame count, total incidents counter, confidence percentage, hardware badges, and recent capture inspection modal.
- **Future-Ready Architecture**: Modular interfaces for NEO-6M GPS module, ADXL345 impact accelerometer, severity classification, and Google Cloud Storage.

---

## 📁 Project Structure

```
UrbanEye/
  ├── app.py                 # Flask server & MJPEG streaming endpoints
  ├── camera.py              # Threaded ESP32-CAM stream reader & auto-reconnect
  ├── detection.py           # YOLO inference, HUD annotation, & cooldown capture
  ├── config.py              # Configuration manager & persistence
  ├── requirements.txt       # Python dependencies
  ├── templates/
  │   └── index.html         # Modern web telemetry dashboard
  ├── static/
  │   ├── style.css          # Dark cyber-tactical dashboard styling
  │   └── script.js          # Live polling & UI controls controller
  ├── models/
  │   ├── README.md          # Guide for custom trained weights
  │   └── best.pt            # Your custom-trained pothole weights (or fallback)
  ├── detected_potholes/     # Auto-saved pothole images (*_orig.jpg, *_annotated.jpg)
  ├── modules/
  │   └── sensors.py         # Hardware expansion stubs (GPS, Accelerometer, GCS)
  └── esp32_cam/
      └── UrbanEye_ESP32_CAM.ino  # Ready-to-flash ESP32-CAM Arduino firmware
```

---

## 🚀 Getting Started on Windows

### 1. Prerequisites
- **Python 3.9+** installed (tested on Python 3.13)
- An **ESP32-CAM AI-Thinker module with OV2640 camera** connected to Wi-Fi (or test URL)

### 2. Install Required Python Packages
Open PowerShell or Command Prompt in the project folder and run:
```powershell
pip install -r requirements.txt
```

### 3. ESP32-CAM Firmware Setup
1. Open [`esp32_cam/UrbanEye_ESP32_CAM.ino`](esp32_cam/UrbanEye_ESP32_CAM.ino) in Arduino IDE.
2. Enter your Wi-Fi credentials:
   ```cpp
   const char* ssid = "YOUR_WIFI_SSID";
   const char* password = "YOUR_WIFI_PASSWORD";
   ```
3. Board: select **"AI Thinker ESP32-CAM"**.
4. Connect GPIO 0 to GND, upload firmware, then remove GPIO 0 jumper and press Reset.
5. Note the IP printed in the Serial Monitor (e.g. `http://192.168.1.100:81/stream`).

### 4. Running the Application
Start the Flask server:
```powershell
python app.py
```

Open your browser and navigate to:
```
http://localhost:5000
```

---

## 🎛️ Dashboard Controls

- **Start / Stop Detection**: Pause or resume the YOLO inference loop at any time without disrupting the video stream.
- **ESP32-CAM Stream URL**: Change the camera IP/port live from the dashboard and click **Update** to reconnect instantly.
- **Confidence Slider**: Dynamically adjust the minimum threshold (15% to 95%) in real time to filter out road markings and shadows.
- **Capture Cooldown**: Adjust interval (default 3.0s) to prevent duplicate snapshots of the same pothole.
- **Incident Gallery**: Click any captured thumbnail in the sidebar to open a side-by-side modal comparing the annotated detection with the raw original frame.

---

## 🧠 Custom Model Placement

UrbanEye comes ready for your trained model:
1. Save your custom weights as `models/best.pt`.
2. Restart `app.py` or hot-reload. UrbanEye will immediately use your custom weights.
3. If `best.pt` is not present, it safely runs with `yolov8n.pt` as a placeholder.
