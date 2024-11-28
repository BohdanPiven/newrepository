"""empty message

Revision ID: 3904b5944784
Revises: 6ba6ca60b8ae
Create Date: 2024-10-24 03:01:11.606068

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3904b5944784'
down_revision = '6ba6ca60b8ae'
branch_labels = None
depends_on = None


def upgrade():
    # Dodaj kolumnę 'email' do tabeli 'user'
    pass

def downgrade():
    # Usuń kolumnę 'email' w razie rollbacku
    pass
