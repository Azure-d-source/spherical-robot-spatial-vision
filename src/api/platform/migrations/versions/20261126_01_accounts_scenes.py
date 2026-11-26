"""Create team accounts, sessions and scenes."""

import sqlalchemy as sa
from alembic import op

revision = "20261126_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("team_id", sa.String(32), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
    )
    op.create_table(
        "accounts",
        sa.Column("account_id", sa.String(32), primary_key=True),
        sa.Column("team_id", sa.String(32), sa.ForeignKey("teams.team_id"), nullable=False),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.CheckConstraint("role IN ('member', 'admin')", name="ck_accounts_role"),
        sa.UniqueConstraint("team_id", "account_id", name="uq_accounts_team_account"),
    )
    op.create_table(
        "login_sessions",
        sa.Column("session_hash", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(32), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_sessions_account_id", "login_sessions", ["account_id"])
    op.create_table(
        "scenes",
        sa.Column("scene_id", sa.String(32), primary_key=True),
        sa.Column("team_id", sa.String(32), sa.ForeignKey("teams.team_id"), nullable=False),
        sa.Column("owner_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("target", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('sample', 'robot', 'simulation')", name="ck_scenes_source"),
        sa.ForeignKeyConstraint(["team_id", "owner_id"], ["accounts.team_id", "accounts.account_id"],
                                name="fk_scenes_team_owner"),
    )
    op.create_index("ix_scenes_team_created", "scenes", ["team_id", "created_at", "scene_id"])


def downgrade() -> None:
    op.drop_table("scenes")
    op.drop_table("login_sessions")
    op.drop_table("accounts")
    op.drop_table("teams")
