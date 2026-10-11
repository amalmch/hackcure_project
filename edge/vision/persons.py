"""
Comptage des personnes et identification du patient (section 6.3) :
`persons > 1` ⇒ les pistes autres que `patientTrackId` sont du personnel ; le patient est la piste
dans la zone `bed` au démarrage (réassignable) ; passage de `persons > 1` à `persons == 1` ⇒ `staff_leave` avec durée.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from .zones import point_in_polygon


@dataclass
class Track:
    track_id: int
    bbox: tuple[float, float, float, float]  # x1,y1,x2,y2 en pixels
    cls: Optional[str]
    conf: float
    keypoints: Optional[dict[str, tuple[float, float]]] = None

    def bottom_center(self, w: int, h: int) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2 / w, self.bbox[3] / h)

    def hips(self, w: int, h: int) -> Optional[tuple[float, float]]:
        if not self.keypoints:
            return None
        pts = [self.keypoints.get("left_hip"), self.keypoints.get("right_hip")]
        pts = [p for p in pts if p]
        if not pts:
            return None
        return (sum(p[0] for p in pts) / len(pts) / w, sum(p[1] for p in pts) / len(pts) / h)


@dataclass
class StaffEvent:
    event: str  # staff_enter | staff_leave
    persons: int
    duration_s: Optional[float] = None


class PersonTracker:
    def __init__(self, bed_polygon: list[tuple[float, float]], min_persist_frames: int = 3):
        self.bed = [tuple(p) for p in bed_polygon]
        self.patient_id: Optional[int] = None
        self.persons = 0
        self._count_streak = 0
        self._pending_count = 0
        self.min_persist = min_persist_frames
        self.staff_since: Optional[float] = None
        self.last_patient_seen: float = 0.0

    def assign_patient(self, tracks: list[Track], w: int, h: int) -> Optional[int]:
        """Le patient = la piste dans le lit ; sinon la plus grande boîte si aucune encore assignée."""
        for t in tracks:
            if point_in_polygon(t.bottom_center(w, h), self.bed) or (t.hips(w, h) and point_in_polygon(t.hips(w, h), self.bed)):
                self.patient_id = t.track_id
                return t.track_id
        if self.patient_id is None and tracks:
            self.patient_id = max(tracks, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1])).track_id
        return self.patient_id

    def patient_track(self, tracks: list[Track], w: int, h: int) -> Optional[Track]:
        ids = {t.track_id: t for t in tracks}
        if self.patient_id in ids:
            self.last_patient_seen = time.time()
            return ids[self.patient_id]
        # réassignation : une piste dans le lit devient le patient
        for t in tracks:
            if point_in_polygon(t.bottom_center(w, h), self.bed):
                self.patient_id = t.track_id
                self.last_patient_seen = time.time()
                return t
        return None

    def update(self, tracks: list[Track], w: int, h: int, now: Optional[float] = None) -> list[StaffEvent]:
        """Met à jour le compte de personnes (avec persistance anti-clignotement) et renvoie les événements staff."""
        now = time.time() if now is None else now
        if self.patient_id is None:
            self.assign_patient(tracks, w, h)
        raw = len(tracks)
        if raw == self._pending_count:
            self._count_streak += 1
        else:
            self._pending_count, self._count_streak = raw, 1
        events: list[StaffEvent] = []
        if self._count_streak >= self.min_persist and raw != self.persons:
            prev = self.persons
            self.persons = raw
            if prev <= 1 and raw > 1:
                self.staff_since = now
                events.append(StaffEvent("staff_enter", raw))
            elif prev > 1 and raw <= 1:
                dur = now - (self.staff_since or now)
                self.staff_since = None
                events.append(StaffEvent("staff_leave", raw, round(dur, 1)))
        return events

    def staff_tracks(self, tracks: list[Track]) -> list[Track]:
        return [t for t in tracks if t.track_id != self.patient_id]
