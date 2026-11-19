# UrbanEye YOLO Models Directory

Place your custom-trained pothole detection model weights file here:
`models/best.pt`

### Model Requirements:
- Trained with **Ultralytics YOLO** (YOLOv8, YOLOv9, YOLOv10, or YOLO11).
- Recommended class: `pothole` (Class 0).
- If `best.pt` is not present, UrbanEye automatically falls back to `yolov8n.pt` as a placeholder model to ensure the pipeline runs without errors until your custom weights are placed here.
