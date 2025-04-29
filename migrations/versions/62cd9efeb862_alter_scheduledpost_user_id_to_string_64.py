"""Alter ScheduledPost.user_id to String(64)

Revision ID: 62cd9efeb862
Revises: c11e1bb66130
Create Date: 2025-04-29 18:03:45.090683
"""
from alembic import op
import sqlalchemy as sa

revision = '62cd9efeb862'
down_revision = 'c11e1bb66130'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('scheduled_posts') as batch_op:
        # 1) usuń istniejący FK po nazwie
        batch_op.drop_constraint(
            'scheduled_posts_user_id_fkey',
            type_='foreignkey'
        )
        # 2) zmień typ kolumny user_id na VARCHAR(64)
        batch_op.alter_column(
            'user_id',
            existing_type=sa.INTEGER(),
            type_=sa.String(length=64),
            existing_nullable=False
        )

def downgrade():
    with op.batch_alter_table('scheduled_posts') as batch_op:
        # przywróć INTEGER i FK
        batch_op.alter_column(
            'user_id',
            existing_type=sa.String(length=64),
            type_=sa.INTEGER(),
            existing_nullable=False
        )
        batch_op.create_foreign_key(
            'scheduled_posts_user_id_fkey',
            'user',
            ['user_id'],
            ['id']
        )
