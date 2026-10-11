"""Add patient timezone for local schedule and day grouping.

Revision ID: 0002_patient_timezone
Revises: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_patient_timezone"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("patients")}
    # 0001 uses current ORM metadata; fresh installs may already have the new column.
    if "timezone" not in columns:
        op.add_column(
            "patients",
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Africa/Tunis"),
        )


def downgrade() -> None:
    # Keep this preference column on downgrade rather than deleting patient settings.
    pass
