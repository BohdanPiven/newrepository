"""Increase length of app_password_hash

Revision ID: 4d7b51b85b1b
Revises: c0dfd68d7bd9
Create Date: 2025-01-24 00:56:37.730489

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4d7b51b85b1b'
down_revision = 'c0dfd68d7bd9'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('app_password_hash',
               existing_type=sa.VARCHAR(length=128),
               type_=sa.Text(),
               existing_nullable=False)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('app_password_hash',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=128),
               existing_nullable=False)

    # ### end Alembic commands ###
