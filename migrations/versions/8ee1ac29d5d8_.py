"""empty message

Revision ID: 8ee1ac29d5d8
Revises: 559da3609a8a
Create Date: 2024-10-24 02:53:02.155107

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8ee1ac29d5d8'
down_revision = '559da3609a8a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=120), nullable=False))
        batch_op.create_unique_constraint('uq_user_email', ['email'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='unique')
        batch_op.drop_column('email')

    # ### end Alembic commands ###
