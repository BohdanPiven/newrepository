"""Add email column to User model

Revision ID: 4891ba3f0e99
Revises: 3904b5944784
Create Date: 2024-10-24 17:23:56.130073

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4891ba3f0e99'
down_revision = '3904b5944784'
branch_labels = None
depends_on = None


def upgrade():
    # Dodanie kolumny 'email' do tabeli 'user'
    op.add_column('user', sa.Column('email', sa.String(length=120), nullable=False))

def downgrade():
    # Usunięcie kolumny 'email' z tabeli 'user'
    op.drop_column('user', 'email')