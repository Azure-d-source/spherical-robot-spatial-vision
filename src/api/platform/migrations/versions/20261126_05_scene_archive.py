"""Add scene archive state and actor."""

import sqlalchemy as sa
from alembic import op

revision = "20261126_05"
down_revision = "20261126_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenes", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scenes", sa.Column("archived_by", sa.String(32), nullable=True))
    op.create_foreign_key("fk_scenes_archived_by", "scenes", "accounts", ["archived_by"], ["account_id"])
    op.create_check_constraint("ck_scenes_archive", "scenes", "(archived_at IS NULL) = (archived_by IS NULL)")


def downgrade() -> None:
    op.drop_constraint("ck_scenes_archive", "scenes", type_="check")
    op.drop_constraint("fk_scenes_archived_by", "scenes", type_="foreignkey")
    op.drop_column("scenes", "archived_by")
    op.drop_column("scenes", "archived_at")
