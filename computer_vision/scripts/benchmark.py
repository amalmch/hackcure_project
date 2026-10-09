"""
Benchmark Script
================
Measures inference speed (FPS, latency) on the RTX 4060.

Usage:
    python scripts/benchmark.py
    python scripts/benchmark.py --model path/to/best.pt
    python scripts/benchmark.py --imgsz 512
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import torch
import yaml
from ultralytics import YOLO

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))


def benchmark_model(
    model_path: Path,
    imgsz: int = 640,
    device: str | int = "0",
    warmup_runs: int = 10,
    test_runs: int = 100,
) -> dict:
    """
    Benchmark inference performance.

    Returns:
        Dict with FPS, latency statistics.
    """
    logger = logging.getLogger(__name__)

    model = YOLO(str(model_path))

    # Create dummy input
    dummy = np.random.randint(0, 255, (imgsz, imgsz, 3), dtype=np.uint8)

    # Warmup
    logger.info(f"Warming up ({warmup_runs} runs)...")
    for _ in range(warmup_runs):
        model.predict(dummy, device=device, imgsz=imgsz, verbose=False)

    # Benchmark
    logger.info(f"Benchmarking ({test_runs} runs, imgsz={imgsz})...")
    latencies = []
    preprocess_times = []
    inference_times = []
    postprocess_times = []

    for _ in range(test_runs):
        start = time.perf_counter()
        results = model.predict(dummy, device=device, imgsz=imgsz, verbose=False)
        total = (time.perf_counter() - start) * 1000  # ms

        latencies.append(total)

        # Extract speed breakdown from results
        for r in results:
            if hasattr(r, "speed"):
                preprocess_times.append(r.speed.get("preprocess", 0))
                inference_times.append(r.speed.get("inference", 0))
                postprocess_times.append(r.speed.get("postprocess", 0))

    latencies = np.array(latencies)
    fps = 1000.0 / np.mean(latencies)

    result = {
        "model": str(model_path),
        "imgsz": imgsz,
        "device": str(device),
        "runs": test_runs,
        "fps": round(float(fps), 1),
        "latency_ms": {
            "mean": round(float(np.mean(latencies)), 2),
            "median": round(float(np.median(latencies)), 2),
            "min": round(float(np.min(latencies)), 2),
            "max": round(float(np.max(latencies)), 2),
            "std": round(float(np.std(latencies)), 2),
            "p95": round(float(np.percentile(latencies, 95)), 2),
            "p99": round(float(np.percentile(latencies, 99)), 2),
        },
    }

    if preprocess_times:
        result["preprocess_ms"] = round(float(np.mean(preprocess_times)), 2)
    if inference_times:
        result["inference_ms"] = round(float(np.mean(inference_times)), 2)
    if postprocess_times:
        result["postprocess_ms"] = round(float(np.mean(postprocess_times)), 2)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark YOLOv8n inference")
    parser.add_argument(
        "--model", type=str, default=None,
        help="Path to model weights",
    )
    parser.add_argument(
        "--imgsz", type=int, nargs="+", default=[512, 640],
        help="Image sizes to benchmark",
    )
    parser.add_argument(
        "--runs", type=int, default=100,
        help="Number of benchmark runs",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Find model
    if args.model:
        model_path = Path(args.model)
    else:
        runs_dir = CV_DIR / "runs" / "patient_yolov8n"
        model_path = None
        if runs_dir.exists():
            for exp_dir in sorted(
                runs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True
            ):
                best = exp_dir / "weights" / "best.pt"
                if best.exists():
                    model_path = best
                    break
        if model_path is None:
            model_path = Path("yolov8n.pt")
            logger.warning(f"No trained model found, using {model_path}")

    logger.info(f"Model: {model_path}")

    # GPU info
    if torch.cuda.is_available():
        logger.info(f"GPU: {torch.cuda.get_device_name(0)}")
        device: str | int = 0
    else:
        logger.warning("No GPU, benchmarking on CPU")
        device = "cpu"

    all_results = []

    for imgsz in args.imgsz:
        logger.info(f"\n{'='*50}")
        logger.info(f"Benchmarking at imgsz={imgsz}")
        logger.info(f"{'='*50}")

        result = benchmark_model(
            model_path=model_path,
            imgsz=imgsz,
            device=device,
            test_runs=args.runs,
        )
        all_results.append(result)

        logger.info(f"FPS: {result['fps']}")
        logger.info(f"Latency: {result['latency_ms']['mean']:.2f} ms (mean)")
        logger.info(f"         {result['latency_ms']['median']:.2f} ms (median)")
        logger.info(f"         {result['latency_ms']['p95']:.2f} ms (p95)")
        if "inference_ms" in result:
            logger.info(f"Preprocess:  {result.get('preprocess_ms', 0):.2f} ms")
            logger.info(f"Inference:   {result.get('inference_ms', 0):.2f} ms")
            logger.info(f"Postprocess: {result.get('postprocess_ms', 0):.2f} ms")

    # Save results
    output_path = CV_DIR / "reports" / "benchmark_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    logger.info(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
