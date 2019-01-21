"""empty message

Revision ID: 746cfc934ca7
Revises: 596e3f3dfa4d
Create Date: 2018-07-17 11:52:07.553927

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '746cfc934ca7'
down_revision = '596e3f3dfa4d'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('client_info',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('phone_number', sa.String(), nullable=True),
    sa.Column('address', sa.String(), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.alter_column('check_in', 'biz_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.alter_column('check_in', 'customer_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.add_column('lesson_record', sa.Column('seat_id', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('lesson_record', 'seat_id')
    op.alter_column('check_in', 'customer_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('check_in', 'biz_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.drop_table('client_info')
    # ### end Alembic commands ###
