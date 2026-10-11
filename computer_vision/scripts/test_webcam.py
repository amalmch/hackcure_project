"""
Quick Webcam Test with OpenCV
=============================
Test live video capture from PC webcam, measure FPS, and capture snapshots.

Usage:
    python computer_vision/scripts/test_webcam.py
    python computer_vision/scripts/test_webcam.py --camera 0
"""

import argparse
import time
import cv2


def test_webcam(camera_index: int = 0, width: int = 640, height: int = 480):
    print(f"[INFO] Initializing webcam index {camera_index}...")
    
    # Use cv2.CAP_DSHOW for fast startup on Windows
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    
    if not cap.isOpened():
        print(f"[WARN] CAP_DSHOW failed, falling back to default backend...")
        cap = cv2.VideoCapture(camera_index)
        
    if not cap.isOpened():
        print(f"[ERROR] Cannot open webcam at index {camera_index}!")
        print("Tip: Check if another application (Teams, Zoom, browser) is using the webcam.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[SUCCESS] Webcam connected: {actual_w}x{actual_h}")
    print("[INFO] Controls:")
    print("  - Press 'q' or 'ESC' to quit")
    print("  - Press 's' to save a snapshot")

    prev_time = time.time()
    frame_count = 0
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[ERROR] Failed to read frame from webcam.")
            break

        frame_count += 1
        curr_time = time.time()
        time_diff = curr_time - prev_time
        if time_diff >= 1.0:
            fps = frame_count / time_diff
            frame_count = 0
            prev_time = curr_time

        # Overlay info
        cv2.putText(
            frame,
            f"HackCure Live Webcam - FPS: {fps:.1f}",
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "Press 'q' to quit | 's' to snapshot",
            (15, frame.shape[0] - 15),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (220, 220, 220),
            1,
            cv2.LINE_AA,
        )

        cv2.imshow("HackCure - Webcam OpenCV Test", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):  # 'q' or ESC
            break
        elif key == ord('s'):
            filename = f"snapshot_{int(time.time())}.jpg"
            cv2.imwrite(filename, frame)
            print(f"[INFO] Snapshot saved as {filename}")

    cap.release()
    cv2.destroyAllWindows()
    print("[INFO] Webcam test closed successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test PC webcam with OpenCV")
    parser.add_argument("--camera", type=int, default=0, help="Webcam device index (default: 0)")
    parser.add_argument("--width", type=int, default=640, help="Frame width (default: 640)")
    parser.add_argument("--height", type=int, default=480, help="Frame height (default: 480)")
    args = parser.parse_args()

    test_webcam(camera_index=args.camera, width=args.width, height=args.height)
