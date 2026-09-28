"""weekly availability, appointment duration and rescheduling queue

Revision ID: 20260909_0001
Revises: 20260608_0002
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa


revision = "20260909_0001"
down_revision = "20260608_0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("appointments") as batch:
        batch.add_column(sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"))
        batch.create_check_constraint("ck_appointment_duration", "duration_minutes IN (30, 60)")

    with op.batch_alter_table("schedule_blocks") as batch:
        batch.add_column(sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        batch.add_column(sa.Column("updated_by", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_schedule_blocks_created_by", "users", ["created_by"], ["id"])
        batch.create_foreign_key("fk_schedule_blocks_updated_by", "users", ["updated_by"], ["id"])
        batch.create_check_constraint("ck_schedule_block_interval", "end_time > start_time")
        batch.create_index("ix_schedule_blocks_doctor_interval", ["clinic_id", "doctor_profile_id", "start_time", "end_time"])

    op.create_table(
        "doctor_availabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("doctor_profile_id", sa.Integer(), sa.ForeignKey("doctor_profiles.id"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("weekday >= 1 AND weekday <= 7", name="ck_doctor_availability_weekday"),
        sa.CheckConstraint("end_time > start_time", name="ck_doctor_availability_interval"),
    )
    op.create_index("ix_doctor_availabilities_clinic_id", "doctor_availabilities", ["clinic_id"])
    op.create_index("ix_doctor_availabilities_doctor_profile_id", "doctor_availabilities", ["doctor_profile_id"])
    op.create_index("ix_doctor_availability_lookup", "doctor_availabilities", ["clinic_id", "doctor_profile_id", "weekday"])

    op.create_table(
        "reschedule_pendings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("open_appointment_id", sa.Integer(), sa.ForeignKey("appointments.id"), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "RESOLVED", name="reschedulependingstatus"), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("originated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("open_appointment_id", name="uq_reschedule_pendings_open_appointment_id"),
    )
    op.create_index("ix_reschedule_pendings_clinic_id", "reschedule_pendings", ["clinic_id"])
    op.create_index("ix_reschedule_pendings_appointment_id", "reschedule_pendings", ["appointment_id"])
    op.create_index("ix_reschedule_pendings_status", "reschedule_pendings", ["status"])
    op.create_index("ix_reschedule_pending_clinic_status", "reschedule_pendings", ["clinic_id", "status"])


def downgrade():
    op.drop_table("reschedule_pendings")
    op.drop_table("doctor_availabilities")
    with op.batch_alter_table("schedule_blocks") as batch:
        batch.drop_index("ix_schedule_blocks_doctor_interval")
        batch.drop_constraint("ck_schedule_block_interval", type_="check")
        batch.drop_column("updated_by")
        batch.drop_column("updated_at")
        batch.drop_column("created_by")
        batch.drop_column("all_day")
    with op.batch_alter_table("appointments") as batch:
        batch.drop_constraint("ck_appointment_duration", type_="check")
        batch.drop_column("duration_minutes")
