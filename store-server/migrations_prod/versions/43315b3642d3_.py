"""empty message

Revision ID: 43315b3642d3
Revises: 6da1cb6824b7
Create Date: 2018-09-03 09:05:06.800103

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '43315b3642d3'
down_revision = '6da1cb6824b7'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('reserve_email', 'email_address')
    op.add_column('store', sa.Column('emails', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('store', 'emails')
    op.add_column('reserve_email', sa.Column('email_address', sa.VARCHAR(), autoincrement=False, nullable=True))
    # ### end Alembic commands ###
