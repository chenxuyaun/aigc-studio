"""add asset_quark_backups table"""
from alembic import op
import sqlalchemy as sa

revision = "add_quark_backups_001"
down_revision = None

def upgrade():
    op.create_table(
        "asset_quark_backups",
        sa.Column("asset_id", sa.String(36), primary_key=True),
        sa.Column("quark_path", sa.String(500), nullable=False),
        sa.Column("uploaded_bytes", sa.Integer, nullable=False, default=0),
        sa.Column("uploaded_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_aqb_uploaded_at", "asset_quark_backups", ["uploaded_at"])

def downgrade():
    op.drop_index("ix_aqb_uploaded_at", "asset_quark_backups")
    op.drop_table("asset_quark_backups")
