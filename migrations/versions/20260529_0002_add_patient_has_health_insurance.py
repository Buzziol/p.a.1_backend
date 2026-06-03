"""add patient has health insurance flag

Revision ID: 20260529_0002
Revises: 20260529_0001
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260529_0002"
down_revision = "20260529_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "patients",
        sa.Column(
            "has_health_insurance",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        """
        UPDATE patients
        SET has_health_insurance = 1
        WHERE COALESCE(health_insurance_name, '') <> ''
           OR COALESCE(health_insurance_plan, '') <> ''
           OR COALESCE(health_insurance_card_number, '') <> ''
           OR health_insurance_valid_until IS NOT NULL
           OR COALESCE(health_insurance_notes, '') <> ''
        """
    )


def downgrade():
    op.drop_column("patients", "has_health_insurance")
