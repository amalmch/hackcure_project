from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

from app.models.dose import DoseStatus
from app.services.dose_status import intake_counts, intake_status, patient_today


def dose(day: date, at: time, status=DoseStatus.SCHEDULED, taken_at=None, grace=30):
    return SimpleNamespace(
        scheduled_date=day,
        scheduled_time=at,
        status=status,
        taken_at=taken_at,
        grace_period_minutes=grace,
    )


def test_taken_dose_grace_boundaries_and_late_classification():
    patient = SimpleNamespace(timezone="Africa/Tunis")
    scheduled = datetime(2026, 10, 11, 12, 0)
    assert intake_status(dose(scheduled.date(), scheduled.time(), taken_at=scheduled.replace(minute=30)), patient) == DoseStatus.TAKEN_ON_TIME
    assert intake_status(dose(scheduled.date(), scheduled.time(), taken_at=scheduled.replace(minute=30, second=1)), patient) == DoseStatus.TAKEN_LATE
    assert intake_status(dose(scheduled.date(), scheduled.time(), taken_at=scheduled.replace(minute=29)), patient) == DoseStatus.TAKEN_ON_TIME
    assert intake_status(dose(scheduled.date(), scheduled.time(), taken_at=scheduled - timedelta(minutes=30)), patient) == DoseStatus.TAKEN_ON_TIME
    assert intake_status(dose(scheduled.date(), scheduled.time(), taken_at=scheduled - timedelta(minutes=30, seconds=1)), patient) == DoseStatus.TAKEN_LATE


def test_pending_reminding_missed_boundaries():
    patient = SimpleNamespace(timezone="Africa/Tunis")
    scheduled = datetime(2026, 10, 11, 12, 0)
    item = dose(scheduled.date(), scheduled.time())
    assert intake_status(item, patient, scheduled - timedelta(minutes=31)) == DoseStatus.SCHEDULED
    assert intake_status(item, patient, scheduled.replace(minute=30)) == DoseStatus.DUE
    assert intake_status(item, patient, scheduled.replace(minute=31)) == DoseStatus.REMINDING
    assert intake_status(item, patient, scheduled + timedelta(hours=24)) == DoseStatus.MISSED


def test_tunis_local_day_boundary_and_offset_conversion():
    patient = SimpleNamespace(timezone="Africa/Tunis")
    now_utc = datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc)
    assert patient_today(patient, now_utc) == date(2026, 10, 11)
    item = dose(date(2026, 10, 11), time(0, 15))
    assert intake_status(item, patient, now_utc) == DoseStatus.DUE


def test_daily_counts_match_list_statuses_and_skip_cancelled():
    patient = SimpleNamespace(timezone="Africa/Tunis")
    now = datetime(2026, 10, 11, 14, 0)
    items = [
        dose(date(2026, 10, 11), time(13, 40), taken_at=datetime(2026, 10, 11, 14, 0)),
        dose(date(2026, 10, 11), time(12, 0), taken_at=datetime(2026, 10, 11, 12, 45)),
        dose(date(2026, 10, 11), time(7, 0)),
        dose(date(2026, 10, 11), time(18, 0)),
        dose(date(2026, 10, 11), time(9, 0), status=DoseStatus.CANCELLED),
    ]
    statuses = [intake_status(item, patient, now) for item in items]
    counts = intake_counts(items, patient, now)
    assert counts["total"] == len([status for status in statuses if status != DoseStatus.CANCELLED])
    assert counts["taken_on_time"] == statuses.count(DoseStatus.TAKEN_ON_TIME)
    assert counts["taken_late"] == statuses.count(DoseStatus.TAKEN_LATE)
    assert counts["missed"] == statuses.count(DoseStatus.MISSED)
    assert counts["pending"] == sum(status in {DoseStatus.SCHEDULED, DoseStatus.DUE, DoseStatus.REMINDING} for status in statuses)
    assert sum(int(counts[key]) for key in ("taken_on_time", "taken_late", "missed", "pending")) == counts["total"]


def test_unknown_patient_timezone_uses_configured_default():
    patient = SimpleNamespace(timezone="invalid/zone")
    assert patient_today(patient, datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc)) == date(2026, 10, 11)
