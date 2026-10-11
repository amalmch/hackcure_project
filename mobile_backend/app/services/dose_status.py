"""Patient-local dose timing rules shared by dose lists and adherence counts."""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.models.dose import DoseStatus, MedicationDose
from app.schemas.dose import DoseResponse

DEFAULT_GRACE_PERIOD_MINUTES = 30
FORGOTTEN_AFTER_HOURS = 24
TAKEN_STATUSES = {DoseStatus.TAKEN_ON_TIME, DoseStatus.TAKEN_LATE}
PENDING_STATUSES = {DoseStatus.SCHEDULED, DoseStatus.DUE, DoseStatus.REMINDING}


def timezone_for_patient(patient: object | None = None) -> ZoneInfo:
    name = getattr(patient, "timezone", None) or settings.PATIENT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError):
        return ZoneInfo("Africa/Tunis")


def patient_now(patient: object | None = None, now: datetime | None = None) -> datetime:
    zone = timezone_for_patient(patient)
    if now is None:
        return datetime.now(timezone.utc).astimezone(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def patient_today(patient: object | None = None, now: datetime | None = None) -> date:
    return patient_now(patient, now).date()


def local_wall_time(value: datetime, patient: object | None = None) -> datetime:
    """Convert instants to patient wall time; legacy naive values are wall time."""
    zone = timezone_for_patient(patient)
    if value.tzinfo is None:
        return value
    return value.astimezone(zone).replace(tzinfo=None)


def scheduled_wall_time(dose: MedicationDose) -> datetime:
    scheduled_time = dose.scheduled_time
    if isinstance(scheduled_time, str):
        scheduled_time = time.fromisoformat(scheduled_time)
    return datetime.combine(dose.scheduled_date, scheduled_time)


def intake_status(
    dose: MedicationDose,
    patient: object | None = None,
    now: datetime | None = None,
) -> DoseStatus:
    """Resolve the persisted machine status to the status effective right now.

    A taken dose is on time inside the dose's ± grace window. A recorded dose
    outside that window is TAKEN_LATE because the API enum has no early category.
    Untaken doses remain pending through the forgotten threshold (24 hours).
    """
    status = dose.status if isinstance(dose.status, DoseStatus) else DoseStatus(dose.status)
    if status == DoseStatus.CANCELLED:
        return status

    scheduled = scheduled_wall_time(dose)
    grace = timedelta(minutes=dose.grace_period_minutes or DEFAULT_GRACE_PERIOD_MINUTES)
    if dose.taken_at is not None:
        taken = local_wall_time(dose.taken_at, patient)
        if abs(taken - scheduled) <= grace:
            return DoseStatus.TAKEN_ON_TIME
        return DoseStatus.TAKEN_LATE

    if status in TAKEN_STATUSES:
        # Repair stale machine status if an external updater forgot the timestamp.
        status = DoseStatus.SCHEDULED
    if status == DoseStatus.MISSED:
        return DoseStatus.MISSED

    current = patient_now(patient, now).replace(tzinfo=None)
    if current >= scheduled + timedelta(hours=FORGOTTEN_AFTER_HOURS):
        return DoseStatus.MISSED
    if current < scheduled - grace:
        return DoseStatus.SCHEDULED
    if current <= scheduled + grace:
        return DoseStatus.DUE
    return DoseStatus.REMINDING


def intake_counts(
    doses: Iterable[MedicationDose],
    patient: object | None = None,
    now: datetime | None = None,
) -> dict[str, int | float]:
    counts = {"total": 0, "taken_on_time": 0, "taken_late": 0, "missed": 0, "pending": 0}
    for dose in doses:
        status = intake_status(dose, patient, now)
        if status == DoseStatus.CANCELLED:
            continue
        counts["total"] += 1
        if status == DoseStatus.TAKEN_ON_TIME:
            counts["taken_on_time"] += 1
        elif status == DoseStatus.TAKEN_LATE:
            counts["taken_late"] += 1
        elif status == DoseStatus.MISSED:
            counts["missed"] += 1
        else:
            counts["pending"] += 1
    taken = int(counts["taken_on_time"]) + int(counts["taken_late"])
    counts["percentage"] = round(taken / int(counts["total"]) * 100, 1) if counts["total"] else 100.0
    return counts


def dose_response(
    dose: MedicationDose,
    patient: object | None = None,
    now: datetime | None = None,
) -> DoseResponse:
    response = DoseResponse.model_validate(dose)
    return response.model_copy(update={"status": intake_status(dose, patient, now).value})
