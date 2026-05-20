"""complete ai analysis audit fields

Revision ID: 2b7d4e8a1c90
Revises: 80f5a6eb7367
Create Date: 2026-05-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "2b7d4e8a1c90"
down_revision = "80f5a6eb7367"
branch_labels = None
depends_on = None


DISCLAIMER = (
    "Este resultado e apenas uma sugestao baseada em inteligencia artificial "
    "e nao substitui avaliacao medica profissional."
)


def upgrade():
    with op.batch_alter_table("ai_analyses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("disclaimer", sa.Text(), nullable=False, server_default=DISCLAIMER))
        batch_op.add_column(sa.Column("validated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
            )
        )


def downgrade():
    with op.batch_alter_table("ai_analyses", schema=None) as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("validated_at")
        batch_op.drop_column("disclaimer")
