"""add indexeszx

Revision ID: 000d3da2c8d3
Revises: 7c3852a59b34
Create Date: 2025-04-14 10:34:20.910019

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "000d3da2c8d3"
down_revision: Union[str, None] = "7c3852a59b34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("idx_apikey_slug", "monitor", ["api_key", "slug"])
    op.create_index("idx_expires_at", "monitor", ["expires_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_apikey_slug")
    op.drop_index("idx_expires_at")
