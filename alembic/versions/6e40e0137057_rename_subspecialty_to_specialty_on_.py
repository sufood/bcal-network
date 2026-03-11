"""rename_subspecialty_to_specialty_on_master_clinicians

Revision ID: 6e40e0137057
Revises: 0258ed0ddb0b
Create Date: 2026-03-09 22:15:19.345468

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e40e0137057'
down_revision: Union[str, Sequence[str], None] = '0258ed0ddb0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('master_clinicians') as batch_op:
        batch_op.alter_column('subspecialty', new_column_name='specialty')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('master_clinicians') as batch_op:
        batch_op.alter_column('specialty', new_column_name='subspecialty')
