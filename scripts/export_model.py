#!/usr/bin/env python3
"""Download yolov8s.pt and export to NCNN format.

Run once before starting goalkeeper-cam:
    python scripts/export_model.py
"""
import os
import sys
from pathlib import Path

MODELS_DIR = Path(__file__).parent.parent / "models"
NCNN_DIR = MODELS_DIR / "yolov8s_ncnn_model"


def main():
    MODELS_DIR.mkdir(exist_ok=True)

    if (NCNN_DIR / "model.ncnn.param").exists():
        print(f"NCNN model already exists at {NCNN_DIR} — nothing to do.")
        return

    print("Importing Ultralytics…")
    try:
        from ultralytics import YOLO
    except ImportError:
        sys.exit("ultralytics not installed. Run: pip install ultralytics")

    pt_path = MODELS_DIR / "yolov8s.pt"
    print(f"Loading yolov8s.pt (will download if not cached)…")
    model = YOLO("yolov8s.pt")  # downloads to ~/.cache/ultralytics if needed

    print(f"Exporting to NCNN format → {NCNN_DIR}")
    export_path = model.export(format="ncnn", imgsz=640)
    print(f"Export complete: {export_path}")

    # Ultralytics writes to cwd; move to models/ if needed
    exported = Path(export_path)
    if exported != NCNN_DIR and exported.exists():
        import shutil
        if NCNN_DIR.exists():
            shutil.rmtree(NCNN_DIR)
        shutil.move(str(exported), str(NCNN_DIR))
        print(f"Moved to {NCNN_DIR}")

    print("Done. You can now run: goalkeeper-cam")


if __name__ == "__main__":
    main()
