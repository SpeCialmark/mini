"""empty message

Revision ID: 6da1cb6824b7
Revises: 9a48397db36d
Create Date: 2018-08-30 20:06:29.316810

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6da1cb6824b7'
down_revision = '9a48397db36d'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('salesman',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('phone_number', sa.String(), nullable=True),
    sa.Column('wechat', sa.String(), nullable=True),
    sa.Column('avatar', sa.String(), nullable=True),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_salesman_biz_id'), 'salesman', ['biz_id'], unique=False)
    op.create_table('share',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.Integer(), nullable=True),
    sa.Column('path', sa.String(), nullable=True),
    sa.Column('params', sa.String(), nullable=True),
    sa.Column('page', sa.String(), nullable=True),
    sa.Column('shared_customer_id', sa.Integer(), nullable=True),
    sa.Column('shared_coach_id', sa.Integer(), nullable=True),
    sa.Column('shared_salesman_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_share_biz_id'), 'share', ['biz_id'], unique=False)
    op.create_table('share_visit',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('share_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_share_visit_share_id'), 'share_visit', ['share_id'], unique=False)
    op.create_table('share_visitor',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('share_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('is_new_comer', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_share_visitor_share_id'), 'share_visitor', ['share_id'], unique=False)
    op.add_column('customer', sa.Column('salesman_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_customer_salesman_id'), 'customer', ['salesman_id'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_customer_salesman_id'), table_name='customer')
    op.drop_column('customer', 'salesman_id')
    op.drop_index(op.f('ix_share_visitor_share_id'), table_name='share_visitor')
    op.drop_table('share_visitor')
    op.drop_index(op.f('ix_share_visit_share_id'), table_name='share_visit')
    op.drop_table('share_visit')
    op.drop_index(op.f('ix_share_biz_id'), table_name='share')
    op.drop_table('share')
    op.drop_index(op.f('ix_salesman_biz_id'), table_name='salesman')
    op.drop_table('salesman')
    # ### end Alembic commands ###
