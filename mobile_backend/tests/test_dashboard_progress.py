from types import SimpleNamespace
from datetime import datetime

from app.api.patients import dashboard_progress
from app.schemas.dose import DoseResponse
from app.models.sport import ActivityStatus


def dose(status: str) -> DoseResponse:
    return DoseResponse(
        id="4a799778-b746-4a68-9317-5d9e5cf9c113",
        prescription_item_id="c2456da4-bf25-4c40-912c-8ad748887c57",
        patient_id="38d56a8b-33a7-4f23-9061-3e740115a962",
        scheduled_date="2026-10-11",
        scheduled_time="09:00:00",
        status=status,
        grace_period_minutes=30,
        reminder_count=0,
        max_reminders=3,
        reminder_interval_minutes=60,
        synced=True,
        created_at=datetime(2026, 10, 11, 9, 0),
    )


def test_dashboard_progress_counts_saved_medication_and_activity_statuses():
    medication, sport = dashboard_progress(
        [dose("TAKEN_ON_TIME"), dose("TAKEN_LATE"), dose("MISSED"), dose("DUE")],
        [SimpleNamespace(status=ActivityStatus.COMPLETED), SimpleNamespace(status=ActivityStatus.SCHEDULED)],
    )
    assert medication == {"total": 4, "taken": 2, "missed": 1, "pending": 1, "percentage": 50.0}
    assert sport == {"total": 2, "completed": 1, "percentage": 50.0}


def test_dashboard_progress_is_zero_when_there_are_no_planned_items():
    assert dashboard_progress([], []) == (
        {"total": 0, "taken": 0, "missed": 0, "pending": 0, "percentage": 0},
        {"total": 0, "completed": 0, "percentage": 0},
    )
