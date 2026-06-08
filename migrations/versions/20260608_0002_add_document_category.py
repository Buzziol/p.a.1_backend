"""add document category

Revision ID: 20260608_0002
Revises: 20260608_0001
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260608_0002"
down_revision = "20260608_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "documents",
        sa.Column(
            "document_category",
            sa.String(length=32),
            nullable=False,
            server_default="OTHER_DOCUMENT",
        ),
    )


def downgrade():
    op.drop_column("documents", "document_category")
