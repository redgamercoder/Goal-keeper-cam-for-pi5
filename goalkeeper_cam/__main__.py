"""python -m goalkeeper_cam  (or via the `goalkeeper-cam` console script)"""
import argparse
import sys

from goalkeeper_cam.config import Config
from goalkeeper_cam.main import run


def main():
    parser = argparse.ArgumentParser(
        prog="goalkeeper-cam",
        description="Goalkeeper highlight auto-recorder for Raspberry Pi 5",
    )
    parser.add_argument("--device", default="/dev/video0", help="V4L2 device (default: /dev/video0)")
    parser.add_argument("--resolution", default="1920x1080", help="WxH (default: 1920x1080)")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--confidence", type=float, default=0.45)
    parser.add_argument("--hold-seconds", type=int, default=5,
                        help="Seconds without ball before clip is saved (default: 5)")
    parser.add_argument("--preroll", type=int, default=15,
                        help="Pre-roll buffer in seconds (default: 15)")
    parser.add_argument("--clips-dir", default="/home/pi/goalkeeper-cam/clips")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--model", default="models/yolov8s_ncnn_model",
                        help="Path to NCNN model directory")
    parser.add_argument("--finetune", action="store_true",
                        help="Print instructions for fine-tuning on soccer ball data and exit")

    args = parser.parse_args()

    if args.finetune:
        _print_finetune_instructions()
        sys.exit(0)

    w, h = (int(x) for x in args.resolution.lower().split("x"))
    config = Config(
        device=args.device,
        resolution=(w, h),
        fps=args.fps,
        confidence=args.confidence,
        hold_seconds=args.hold_seconds,
        preroll_seconds=args.preroll,
        clips_dir=args.clips_dir,
        port=args.port,
        model_path=args.model,
    )

    run(config)


def _print_finetune_instructions():
    print("""
Fine-tuning YOLOv8s on soccer ball data
=========================================

1. Create a free Roboflow account at https://roboflow.com
2. Search the Roboflow Universe for "soccer ball" datasets, e.g.:
     https://universe.roboflow.com/search?q=soccer+ball
3. Export a dataset in "YOLOv8" format (YAML + images).
4. Install Ultralytics:  pip install ultralytics
5. Fine-tune from the COCO pre-trained weights:

   from ultralytics import YOLO
   model = YOLO('yolov8s.pt')
   model.train(data='path/to/dataset.yaml', epochs=50, imgsz=640,
               device='cpu', batch=8, name='goalkeeper-ft')

6. Export the fine-tuned model to NCNN:

   model = YOLO('runs/detect/goalkeeper-ft/weights/best.pt')
   model.export(format='ncnn')

7. Point goalkeeper-cam at the new model:
   goalkeeper-cam --model runs/detect/goalkeeper-ft/weights/best_ncnn_model
""")


if __name__ == "__main__":
    main()
