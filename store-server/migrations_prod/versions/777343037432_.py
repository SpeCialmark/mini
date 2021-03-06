"""empty message

Revision ID: 777343037432
Revises: e32177d0fc2d
Create Date: 2019-01-02 10:55:01.142922

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '777343037432'
down_revision = 'e32177d0fc2d'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('customer', sa.Column('demand', sa.ARRAY(sa.String()), nullable=True))
    op.add_column('customer', sa.Column('training_note', sa.String(), nullable=True))
    op.add_column('plan', sa.Column('duration', sa.Integer(), nullable=True))
    op.add_column('plan', sa.Column('finished_at', sa.DateTime(), nullable=True))
    op.add_column('plan', sa.Column('purpose', sa.String(), nullable=True))
    op.add_column('plan', sa.Column('status', sa.Integer(), nullable=True))
    op.add_column('plan', sa.Column('title', sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('plan', 'title')
    op.drop_column('plan', 'status')
    op.drop_column('plan', 'purpose')
    op.drop_column('plan', 'finished_at')
    op.drop_column('plan', 'duration')
    op.drop_column('customer', 'training_note')
    op.drop_column('customer', 'demand')
    # ### end Alembic commands ###
