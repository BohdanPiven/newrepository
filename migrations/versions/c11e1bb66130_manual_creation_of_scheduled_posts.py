"""
Manual creation of scheduled_posts

Revision ID: c11e1bb66130
Revises: 4d7b51b85b1b
Create Date: 2025-04-05 12:53:07.278068
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c11e1bb66130'
down_revision = '4d7b51b85b1b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'scheduled_posts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('time', sa.Time(), nullable=False),
        sa.Column('topic', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        # Jeśli chcesz mieć ForeignKey z user_id -> user.id:
        sa.ForeignKeyConstraint(['user_id'], ['user.id'])
    )


def downgrade():
    op.drop_table('scheduled_posts')
