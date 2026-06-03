"""add patient health insurance fields

Revision ID: 20260529_0001
Revises:
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260529_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("patients", sa.Column("health_insurance_name", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("health_insurance_plan", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("health_insurance_card_number", sa.String(length=64), nullable=True))
    op.add_column("patients", sa.Column("health_insurance_valid_until", sa.Date(), nullable=True))
    op.add_column("patients", sa.Column("health_insurance_notes", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("patients", "health_insurance_notes")
    op.drop_column("patients", "health_insurance_valid_until")
    op.drop_column("patients", "health_insurance_card_number")
    op.drop_column("patients", "health_insurance_plan")
    op.drop_column("patients", "health_insurance_name")
