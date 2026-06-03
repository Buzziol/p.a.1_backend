"""add patient registration fields

Revision ID: 20260602_0001
Revises: 20260529_0002
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260602_0001"
down_revision = "20260529_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("patients", sa.Column("sex", sa.String(length=32), nullable=True))
    op.add_column("patients", sa.Column("mother_name", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("birthplace", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("street", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("address_number", sa.String(length=32), nullable=True))
    op.add_column("patients", sa.Column("address_complement", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("neighborhood", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("city", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("state", sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column("patients", "state")
    op.drop_column("patients", "city")
    op.drop_column("patients", "neighborhood")
    op.drop_column("patients", "address_complement")
    op.drop_column("patients", "address_number")
    op.drop_column("patients", "street")
    op.drop_column("patients", "birthplace")
    op.drop_column("patients", "mother_name")
    op.drop_column("patients", "sex")
