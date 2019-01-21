"""empty message

Revision ID: 9e4ae3a4fd38
Revises: 09e6bcbca830
Create Date: 2018-09-29 20:49:27.415504

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9e4ae3a4fd38'
down_revision = '09e6bcbca830'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('video', sa.Column('sd_url', sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('video', 'sd_url')
    # ### end Alembic commands ###
