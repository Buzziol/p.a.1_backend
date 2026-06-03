"""add dermatology medical record fields

Revision ID: 20260602_0002
Revises: 20260602_0001
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260602_0002"
down_revision = "20260602_0001"
branch_labels = None
depends_on = None


FIELDS = [
    sa.Column("attendance_datetime", sa.DateTime(), nullable=True),
    sa.Column("doctor_name", sa.String(length=255), nullable=True),
    sa.Column("doctor_crm", sa.String(length=32), nullable=True),
    sa.Column("consultation_type", sa.String(length=64), nullable=True),
    sa.Column("consultation_type_other", sa.String(length=255), nullable=True),
    sa.Column("chief_complaint", sa.Text(), nullable=True),
    sa.Column("problem_onset", sa.String(length=255), nullable=True),
    sa.Column("clinical_evolution", sa.Text(), nullable=True),
    sa.Column("associated_symptoms", sa.JSON(), nullable=True),
    sa.Column("symptom_other", sa.String(length=255), nullable=True),
    sa.Column("had_previous_treatment", sa.Boolean(), nullable=True),
    sa.Column("previous_treatments", sa.Text(), nullable=True),
    sa.Column("has_skin_cancer_history", sa.Boolean(), nullable=True),
    sa.Column("skin_cancer_history_description", sa.Text(), nullable=True),
    sa.Column("frequent_sun_exposure", sa.Boolean(), nullable=True),
    sa.Column("sunscreen_use", sa.String(length=64), nullable=True),
    sa.Column("skin_phototype", sa.String(length=64), nullable=True),
    sa.Column("lesion_location", sa.Text(), nullable=True),
    sa.Column("lesion_description", sa.Text(), nullable=True),
    sa.Column("has_measurable_lesion", sa.Boolean(), nullable=True),
    sa.Column("lesion_size", sa.String(length=64), nullable=True),
    sa.Column("lesion_size_unit", sa.String(length=16), nullable=True),
    sa.Column("lesion_color", sa.String(length=64), nullable=True),
    sa.Column("lesion_color_other", sa.String(length=255), nullable=True),
    sa.Column("lesion_borders", sa.String(length=64), nullable=True),
    sa.Column("lesion_symptoms", sa.JSON(), nullable=True),
    sa.Column("wants_image_attachment", sa.Boolean(), nullable=True),
    sa.Column("image_attachment_notes", sa.Text(), nullable=True),
    sa.Column("has_suspicious_lesion", sa.Boolean(), nullable=True),
    sa.Column("asymmetry", sa.Boolean(), nullable=True),
    sa.Column("irregular_borders", sa.Boolean(), nullable=True),
    sa.Column("varied_color", sa.Boolean(), nullable=True),
    sa.Column("diameter_greater_than_6mm", sa.Boolean(), nullable=True),
    sa.Column("recent_evolution_change", sa.Boolean(), nullable=True),
    sa.Column("suspicion_level", sa.String(length=64), nullable=True),
    sa.Column("has_requested_exams", sa.Boolean(), nullable=True),
    sa.Column("has_prescription", sa.Boolean(), nullable=True),
    sa.Column("needs_follow_up", sa.Boolean(), nullable=True),
    sa.Column("suggested_return_date", sa.Date(), nullable=True),
    sa.Column("return_guidance", sa.Text(), nullable=True),
    sa.Column("has_referral", sa.Boolean(), nullable=True),
    sa.Column("referral_target", sa.String(length=255), nullable=True),
    sa.Column("referral_reason", sa.Text(), nullable=True),
    sa.Column("general_observations", sa.Text(), nullable=True),
    sa.Column("doctor_signature", sa.String(length=255), nullable=True),
    sa.Column("record_datetime", sa.DateTime(), nullable=True),
]


def upgrade():
    for column in FIELDS:
        op.add_column("medical_records", column)


def downgrade():
    for column in reversed(FIELDS):
        op.drop_column("medical_records", column.name)
