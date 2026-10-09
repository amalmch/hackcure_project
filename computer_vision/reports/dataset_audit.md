# Dataset Audit Report

Generated automatically by the dataset audit pipeline.

## TCC-Person-Fall-2024

- **Path**: `C:\Users\bousl\Desktop\hackcure_project\datasets\TCC-Person-Fall-2024.v6i.yolov8`
- **Annotation Format**: `yolov8_segment`

### Summary

| Metric | Count |
|--------|-------|
| Total Images | 1201 |
| Total Labels | 1201 |
| Total Bounding Boxes | 1217 |
| Missing Labels | 0 |
| Missing Images | 0 |
| Empty Labels | 6 |
| Malformed Labels | 0 |
| Duplicate Images | 0 |
| Class Imbalance Ratio | 1.63 |

### Classes

| ID | Name |
|----|------|
| 0 | person-fall |
| 1 | person-in-bed |
| 2 | person-moving-out |
| 3 | person-near-fall |
| 4 | person-out |

### Class Distribution

| Class ID | Class Name | Count |
|----------|-----------|-------|
| 0 | person-fall | 236 |
| 1 | person-in-bed | 322 |
| 2 | person-moving-out | 248 |
| 3 | person-near-fall | 213 |
| 4 | person-out | 198 |

### Per-Split Details

#### train
- Images: 841
- Labels: 841
- Bboxes: 850
- Missing labels: 0
- Empty labels: 3

#### val
- Images: 240
- Labels: 240
- Bboxes: 244
- Missing labels: 0
- Empty labels: 3

#### test
- Images: 120
- Labels: 120
- Bboxes: 123
- Missing labels: 0
- Empty labels: 0

### Image Resolutions

| Resolution | Count |
|-----------|-------|
| 640x640 | 150 |

---

## Human-Fall-Dataset-v2

- **Path**: `C:\Users\bousl\Desktop\hackcure_project\datasets\Human Fall.v2i.yolov8`
- **Annotation Format**: `yolov8_detect`

### Summary

| Metric | Count |
|--------|-------|
| Total Images | 618 |
| Total Labels | 618 |
| Total Bounding Boxes | 641 |
| Missing Labels | 0 |
| Missing Images | 0 |
| Empty Labels | 0 |
| Malformed Labels | 0 |
| Duplicate Images | 0 |
| Class Imbalance Ratio | 86.86 |

### Classes

| ID | Name |
|----|------|
| 0 | Human Falling |
| 1 | nopain |
| 2 | sitting |

### Class Distribution

| Class ID | Class Name | Count |
|----------|-----------|-------|
| 0 | Human Falling | 608 |
| 1 | nopain | 26 |
| 2 | sitting | 7 |

### Per-Split Details

#### train
- Images: 582
- Labels: 582
- Bboxes: 603
- Missing labels: 0
- Empty labels: 0

#### val
- Images: 27
- Labels: 27
- Bboxes: 28
- Missing labels: 0
- Empty labels: 0

#### test
- Images: 9
- Labels: 9
- Bboxes: 10
- Missing labels: 0
- Empty labels: 0

### Image Resolutions

| Resolution | Count |
|-----------|-------|
| 640x640 | 86 |

---

## GMDCSA-24

- **Path**: `C:\Users\bousl\Desktop\hackcure_project\datasets\GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-v2.1\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-5abac76`
- **Annotation Format**: `video_csv`

- **Subjects**: 4
- **Total Videos**: 160
- **ADL Videos**: 81
- **Fall Videos**: 79

### Temporal Classes Found

- Drinking
- Eating
- Exercising
- Fall (FW)
- Falling (BW
- Falling (BW)
- Falling (FW)
- Falling (SW)
- Reading
- Sitting
- Sleeping
- Standing
- Walking
- Writing

> **Note**: Video-only dataset with temporal CSV annotations. No YOLO bounding-box labels available. Not directly usable for YOLO training without manual annotation.

#### Subject 1
- ADL videos: 16
- Fall videos: 16
- Classes: Falling (BW), Falling (FW), Falling (SW), Reading, Sitting, Sleeping, Standing, Walking

#### Subject 2
- ADL videos: 23
- Fall videos: 25
- Classes: Drinking, Eating, Exercising, Falling (BW, Falling (BW), Falling (FW), Falling (SW), Reading, Sitting, Sleeping, Standing, Walking, Writing

#### Subject 3
- ADL videos: 22
- Fall videos: 21
- Classes: Drinking, Eating, Exercising, Fall (FW), Falling (BW), Falling (FW), Falling (SW), Reading, Sitting, Sleeping, Standing, Walking, Writing

#### Subject 4
- ADL videos: 20
- Fall videos: 17
- Classes: Drinking, Eating, Exercising, Falling (BW), Falling (FW), Falling (SW), Reading, Sitting, Sleeping, Standing, Walking, Writing

---

## Canonical Class Mapping

| Source Dataset | Source Class | Source ID | Canonical Class | Action | Reason |
|---------------|------------|-----------|----------------|--------|--------|