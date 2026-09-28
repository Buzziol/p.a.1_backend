"""identify the originating entity of rescheduling pendings

Revision ID: 20260910_0002
Revises: 20260909_0001
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa


revision = "20260910_0002"
down_revision = "20260909_0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reschedule_pendings") as batch:
        batch.add_column(sa.Column("source_entity_type", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("source_entity_id", sa.Integer(), nullable=True))
        batch.create_index("ix_reschedule_pendings_source_entity", ["source_entity_type", "source_entity_id"])


def downgrade():
    with op.batch_alter_table("reschedule_pendings") as batch:
        batch.drop_index("ix_reschedule_pendings_source_entity")
        batch.drop_column("source_entity_id")
        batch.drop_column("source_entity_type")
