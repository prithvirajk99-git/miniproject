"""
UrbanEye - AI-Based Pothole Detection Prototype
Configuration Settings & Defaults
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# Default settings
DEFAULT_CONFIG = {
    # ESP32-CAM Stream Settings
    # Common ESP32-CAM URLs:
    #   http://<esp32_ip>:81/stream (standard camera web server sketch)
    #   http://<esp32_ip>/stream
    #   http://<esp32_ip>/mjpeg/1
    "esp32_stream_url": "http://192.168.1.100:81/stream",
    
    # Model Settings
    "model_path": os.path.join(BASE_DIR, "models", "best.pt"),
    "fallback_model_name": "yolov8n.pt",
    "confidence_threshold": 0.35,  # 35% default (ideal for screen tests & road feeds)
    "iou_threshold": 0.45,
    
    # Target classes for pothole detection
    # Custom pothole YOLO models typically have class 0 as 'pothole'
    "pothole_class_names": ["pothole", "potholes", "hole"],
    
    # Automatic Capture Settings
    "capture_enabled": True,
    "cooldown_seconds": 3.0,  # Avoid saving duplicate images within 3 seconds
    "save_dir": os.path.join(BASE_DIR, "detected_potholes"),
    
    # Server Settings
    "server_host": "0.0.0.0",
    "server_port": 5000,
    "debug": False,
    
    # Future Expansion Modules
    "gps": {
        "enabled": False,
        "port": "COM3",
        "baudrate": 9600,
        "module": "NEO-6M"
    },
    "accelerometer": {
        "enabled": False,
        "bus": 1,
        "address": "0x53",
        "module": "ADXL345",
        "impact_threshold_g": 2.5
    },
    "cloud_storage": {
        "enabled": False,
        "provider": "google_cloud_storage",
        "bucket_name": "urbaneye-pothole-captures"
    }
}


def load_config() -> dict:
    """Load configuration from config.json or fall back to defaults."""
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception as e:
            print(f"[Config] Error loading config.json: {e}. Using defaults.")
    
    # Ensure directories exist
    os.makedirs(config["save_dir"], exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "models"), exist_ok=True)
    return config


def save_config(updates: dict) -> dict:
    """Save updated configuration to config.json."""
    config = load_config()
    config.update(updates)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"[Config] Error saving config.json: {e}")
    return config
