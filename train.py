"""
UrbanEye - Autonomous Model Trainer
Trains YOLOv8 on your Roboflow pothole dataset and automatically
updates models/best.pt upon completion.
"""

import os
import shutil
from pathlib import Path
from ultralytics import YOLO

def main():
    base_dir = Path(__file__).resolve().parent
    data_yaml = base_dir / "dataset" / "data.yaml"
    
    if not data_yaml.exists():
        print(f"[Trainer] Error: {data_yaml} not found!")
        return

    print("=" * 60)
    print(" UrbanEye - Pothole Detection Model Training")
    print(" Dataset :", data_yaml)
    print(" Base    : YOLOv8n (Nano)")
    print("=" * 60)

    # Load baseline YOLOv8 nano model
    model = YOLO("yolov8n.pt")

    # Train model
    results = model.train(
        data=str(data_yaml),
        epochs=25,
        imgsz=512,            # 512 gives great balance of high accuracy and CPU speed
        batch=16,
        workers=4,
        device="cpu",
        name="urbaneye_pothole",
        project=str(base_dir / "runs" / "detect"),
        exist_ok=True,
        patience=8,
        save=True,
        verbose=True
    )

    # Locate generated best.pt weights
    best_weights = base_dir / "runs" / "detect" / "urbaneye_pothole" / "weights" / "best.pt"
    if best_weights.exists():
        target_1 = base_dir / "models" / "best.pt"
        target_2 = base_dir / "UrbanEye" / "models" / "best.pt"
        
        target_1.parent.mkdir(parents=True, exist_ok=True)
        target_2.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(str(best_weights), str(target_1))
        shutil.copy2(str(best_weights), str(target_2))
        
        print("\n" + "=" * 60)
        print(" TRAINING COMPLETED SUCCESSFULLY!")
        print(f" Best weights deployed to: {target_1}")
        print(" UrbanEye will now use your newly trained custom model.")
        print("=" * 60)
    else:
        print("[Trainer] Training finished, but best.pt was not found at expected path.")

if __name__ == "__main__":
    main()
