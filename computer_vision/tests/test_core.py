"""
Unit Tests for Computer Vision Module
======================================
Tests core functionality: harmonization, position, movement, fall detection.
"""

import sys
from pathlib import Path

import pytest

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))


# ---------- Harmonization Tests ----------

class TestHarmonization:
    """Tests for the harmonization module."""

    def test_polygon_to_bbox(self):
        from src.datasets.harmonize import polygon_to_bbox
        # Simple square polygon: (0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)
        values = [0.1, 0.1, 0.3, 0.1, 0.3, 0.3, 0.1, 0.3]
        x_c, y_c, w, h = polygon_to_bbox(values)
        assert abs(x_c - 0.2) < 1e-6
        assert abs(y_c - 0.2) < 1e-6
        assert abs(w - 0.2) < 1e-6
        assert abs(h - 0.2) < 1e-6

    def test_harmonize_detect_line(self):
        from src.datasets.harmonize import harmonize_label_line
        remap = {
            0: {
                "action": "REMAP",
                "canonical_class": "patient_fallen",
                "canonical_class_id": 0,
                "reason": "",
            }
        }
        line = "0 0.5 0.5 0.3 0.4"
        result, info = harmonize_label_line(line, remap, "yolov8_detect")
        assert result is not None
        assert "0 0.500000 0.500000 0.300000 0.400000" == result
        assert info["canonical_class_id"] == 0

    def test_harmonize_exclude(self):
        from src.datasets.harmonize import harmonize_label_line
        remap = {
            1: {
                "action": "EXCLUDE",
                "canonical_class": None,
                "canonical_class_id": None,
                "reason": "Not useful",
            }
        }
        line = "1 0.5 0.5 0.3 0.4"
        result, info = harmonize_label_line(line, remap, "yolov8_detect")
        assert result is None
        assert info["action"] == "EXCLUDE"

    def test_harmonize_malformed(self):
        from src.datasets.harmonize import harmonize_label_line
        remap = {}
        line = "abc 0.5"
        result, info = harmonize_label_line(line, remap, "yolov8_detect")
        assert result is None


# ---------- Position Tests ----------

class TestPosition:
    """Tests for the spatial position module."""

    def test_compute_position(self):
        from src.spatial.position import compute_position
        pos = compute_position(
            bbox=[100, 200, 300, 400],
            image_width=640,
            image_height=480,
        )
        assert abs(pos.x_center - 200 / 640) < 1e-4
        assert abs(pos.y_center - 300 / 480) < 1e-4
        assert abs(pos.bottom_x - 200 / 640) < 1e-4
        assert abs(pos.bottom_y - 400 / 480) < 1e-4
        assert pos.area_norm > 0

    def test_empty_bbox(self):
        from src.spatial.position import compute_position
        pos = compute_position(bbox=[], image_width=640, image_height=480)
        assert pos.x_center == 0.0


# ---------- Movement Analyzer Tests ----------

class TestMovementAnalyzer:
    """Tests for the movement analyzer."""

    def test_stationary(self):
        from src.temporal.movement_analyzer import MovementAnalyzer
        from collections import deque
        analyzer = MovementAnalyzer(stationary_threshold=0.005)

        # Same position across frames
        history = deque([(320.0, 240.0), (320.0, 240.0)], maxlen=30)
        state = analyzer.update(
            track_id=1,
            center=(320.0, 240.0),
            image_width=640,
            image_height=480,
            frame_idx=1,
            center_history=history,
        )
        assert state.state == "stationary"

    def test_movement(self):
        from src.temporal.movement_analyzer import MovementAnalyzer
        from collections import deque
        analyzer = MovementAnalyzer(stationary_threshold=0.001)

        history = deque([(100.0, 100.0), (200.0, 100.0)], maxlen=30)
        state = analyzer.update(
            track_id=1,
            center=(200.0, 100.0),
            image_width=640,
            image_height=480,
            frame_idx=1,
            center_history=history,
        )
        assert state.velocity > 0
        assert state.state != "stationary"


# ---------- Fall Detector Tests ----------

class TestFallDetector:
    """Tests for the temporal fall detector."""

    def test_no_fall_single_frame(self):
        from src.temporal.fall_detector import FallDetector
        detector = FallDetector(min_fallen_frames=3)

        event = detector.update(
            track_id=1,
            class_name="patient_fallen",
            confidence=0.9,
            movement_state="stationary",
            velocity=0.0,
            frame_idx=1,
        )
        # Should NOT be confirmed after just 1 frame
        assert not event.detected

    def test_fall_after_persistence(self):
        from src.temporal.fall_detector import FallDetector
        detector = FallDetector(
            min_fallen_frames=3,
            min_fallen_confidence=0.3,
            min_fall_event_confidence=0.3,
        )

        # Simulate multiple frames of fallen state
        for i in range(10):
            event = detector.update(
                track_id=1,
                class_name="patient_fallen",
                confidence=0.8,
                movement_state="stationary",
                velocity=0.0,
                frame_idx=i,
            )
        # Should be confirmed after sustained fallen state
        assert event.detected

    def test_no_fall_upright(self):
        from src.temporal.fall_detector import FallDetector
        detector = FallDetector()

        for i in range(20):
            event = detector.update(
                track_id=1,
                class_name="patient_sitting",
                confidence=0.9,
                movement_state="stationary",
                velocity=0.0,
                frame_idx=i,
            )
        assert not event.detected


# ---------- Discomfort Tests ----------

class TestDiscomfort:
    """Tests for discomfort association."""

    def test_association(self):
        from src.face.discomfort import DiscomfortAssociator
        assoc = DiscomfortAssociator(max_distance=0.5)

        detections = [{
            "bbox": [100, 100, 200, 200],
            "class_name": "possible_discomfort",
            "confidence": 0.8,
        }]
        patients = [{
            "track_id": 1,
            "bbox": [50, 50, 300, 300],
        }]

        results = assoc.associate(detections, patients, 640, 480)
        assert results[1]["detected"] is True

    def test_no_discomfort(self):
        from src.face.discomfort import DiscomfortAssociator
        assoc = DiscomfortAssociator()

        detections = [{
            "bbox": [100, 100, 200, 200],
            "class_name": "patient_sitting",
            "confidence": 0.8,
        }]
        patients = [{"track_id": 1, "bbox": [50, 50, 300, 300]}]

        results = assoc.associate(detections, patients, 640, 480)
        assert results[1]["detected"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
