"""empty message

Revision ID: 35198d2338d9
Revises: 9753703e8ddc
Create Date: 2018-11-22 17:28:19.717013

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '35198d2338d9'
down_revision = '9753703e8ddc'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('coach', sa.Column('avatar', sa.String(), nullable=True))
    op.add_column('coach', sa.Column('cover', sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('coach', 'cover')
    op.drop_column('coach', 'avatar')
    # ### end Alembic commands ###
