"""Create the application schema, including patient companion tables.

Revision ID: 0001_initial_schema
Revises:
"""
from alembic import op

from app.database import Base
import app.models

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # Preserve pre-existing application data/tables on downgrade.
    for name in ("safety_events", "mood_entries", "companion_consents", "companion_messages", "companion_conversations"):
        Base.metadata.tables[name].drop(bind=op.get_bind(), checkfirst=True)
