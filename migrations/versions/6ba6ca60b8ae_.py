"""empty message

Revision ID: 6ba6ca60b8ae
Revises: 8ee1ac29d5d8
Create Date: 2024-10-24 02:58:38.520095

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6ba6ca60b8ae'
down_revision = '8ee1ac29d5d8'
branch_labels = None
depends_on = None


def upgrade():
    # Dodaj kolumnę 'email' do tabeli 'user'
    pass

def downgrade():
    # Usuń kolumnę 'email' w razie rollbacku
    pass