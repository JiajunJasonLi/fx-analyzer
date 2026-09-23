"""Create the complete Phase 1 schema.

Revision ID: 20260920_0001
Revises:
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

from app.database.base import Base
from app.database import models  # noqa: F401

revision: str = "20260920_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tables contain named constraints and indexes, so creation is deterministic.
    # The two circular current-version constraints use ALTER TABLE and are
    # deferrable, allowing an observation and its first version in one transaction.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_constraint(
        "fk_fx_observation_current_version", "fx_observation", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_policy_observation_current_version",
        "policy_rate_observation",
        type_="foreignkey",
    )
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=bind, checkfirst=False)
