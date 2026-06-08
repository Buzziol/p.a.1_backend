"""add has specific dermatological lesion field

Revision ID: 20260608_0001
Revises: 20260602_0002
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260608_0001"
down_revision = "20260602_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "medical_records",
        sa.Column("has_specific_dermatological_lesion", sa.Boolean(), nullable=True),
    )


def downgrade():
    op.drop_column("medical_records", "has_specific_dermatological_lesion")
