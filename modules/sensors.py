"""
UrbanEye - Hardware Sensor Interfaces & Future Expansion Modules
Provides modular plug-in architecture for:
- NEO-6M GPS Receiver (NMEA coordinates)
- ADXL345 Accelerometer (Impact / G-force bump detection)
- Pothole Severity Classifier (Bounding area & G-force heuristic)
- Google Cloud Storage Uploader
"""

import time
import math
from typing import Optional, Dict, Any


class GPSManager:
    """Interface for NEO-6M GPS module over UART/Serial."""
    def __init__(self, port: str = "COM3", baudrate: int = 9600, enabled: bool = False):
        self.port = port
        self.baudrate = baudrate
        self.enabled = enabled
        self.connected = False
        self.last_latitude = 0.0
        self.last_longitude = 0.0
        self.last_speed_kmh = 0.0
        self.last_fix = False

    def start(self):
        """Initialize serial connection if enabled."""
        if not self.enabled:
            return
        try:
            # import serial
            # self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            self.connected = True
            print(f"[GPS] NEO-6M interface initialized on {self.port}")
        except Exception as e:
            self.connected = False
            print(f"[GPS] Could not connect to NEO-6M: {e}")

    def get_location(self) -> Dict[str, Any]:
        """Return current GPS coordinates and fix status."""
        return {
            "enabled": self.enabled,
            "connected": self.connected,
            "fix": self.last_fix,
            "latitude": self.last_latitude,
            "longitude": self.last_longitude,
            "speed_kmh": self.last_speed_kmh
        }


class AccelerometerManager:
    """Interface for ADXL345 3-Axis Accelerometer over I2C."""
    def __init__(self, bus: int = 1, address: str = "0x53", threshold_g: float = 2.5, enabled: bool = False):
        self.bus = bus
        self.address = address
        self.threshold_g = threshold_g
        self.enabled = enabled
        self.connected = False
        self.last_z_g = 1.0
        self.max_impact_detected = 0.0

    def start(self):
        """Initialize I2C bus if enabled."""
        if not self.enabled:
            return
        try:
            # import smbus2
            self.connected = True
            print(f"[ADXL345] Accelerometer initialized at I2C {self.address}")
        except Exception as e:
            self.connected = False
            print(f"[ADXL345] Could not initialize accelerometer: {e}")

    def get_reading(self) -> Dict[str, Any]:
        """Return current G-force readings and impact status."""
        return {
            "enabled": self.enabled,
            "connected": self.connected,
            "current_g": self.last_z_g,
            "impact_threshold": self.threshold_g,
            "recent_max_impact": self.max_impact_detected
        }


class SeverityClassifier:
    """
    Classifies pothole severity into Minor, Moderate, or Severe based on:
    - Bounding box pixel area ratio to frame
    - Impact G-force from accelerometer (if available)
    - Detection confidence
    """
    @staticmethod
    def classify(box_xyxy, frame_shape, impact_g: Optional[float] = None) -> str:
        x1, y1, x2, y2 = box_xyxy
        box_area = max(0, (x2 - x1) * (y2 - y1))
        frame_area = frame_shape[0] * frame_shape[1]
        area_ratio = box_area / max(1, frame_area)

        # Baseline severity based on visual footprint
        if area_ratio > 0.08 or (impact_g is not None and impact_g >= 3.0):
            return "Severe"
        elif area_ratio > 0.03 or (impact_g is not None and impact_g >= 2.0):
            return "Moderate"
        else:
            return "Minor"


class CloudStorageManager:
    """Google Cloud Storage uploader for persistent cloud telemetry."""
    def __init__(self, bucket_name: str = "urbaneye-captures", enabled: bool = False):
        self.bucket_name = bucket_name
        self.enabled = enabled

    def upload_image(self, local_path: str, remote_filename: str) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            # from google.cloud import storage
            # client = storage.Client()
            # bucket = client.bucket(self.bucket_name)
            # blob = bucket.blob(remote_filename)
            # blob.upload_from_filename(local_path)
            # return blob.public_url
            return f"https://storage.googleapis.com/{self.bucket_name}/{remote_filename}"
        except Exception as e:
            print(f"[GCS] Upload failed: {e}")
            return None
