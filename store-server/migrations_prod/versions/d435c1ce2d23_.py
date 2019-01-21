"""empty message

Revision ID: d435c1ce2d23
Revises: e3655be33fba
Create Date: 2018-11-12 12:07:08.696940

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'd435c1ce2d23'
down_revision = 'e3655be33fba'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('activity',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('start_date', sa.DateTime(), nullable=False),
    sa.Column('end_date', sa.DateTime(), nullable=True),
    sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('join_price', sa.Float(), nullable=True),
    sa.Column('status', sa.Integer(), nullable=True),
    sa.Column('cover_image', sa.String(), nullable=True),
    sa.Column('event_type', sa.String(), nullable=False),
    sa.Column('private_parameter', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activity_biz_id'), 'activity', ['biz_id'], unique=False)
    op.create_index(op.f('ix_activity_event_type'), 'activity', ['event_type'], unique=False)
    op.create_table('goods',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('price', sa.Float(), nullable=True),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('images', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('stock', sa.Integer(), nullable=True),
    sa.Column('is_shelf', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_goods_biz_id'), 'goods', ['biz_id'], unique=False)
    op.create_table('order',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('flow_code', sa.String(), nullable=False),
    sa.Column('status', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('goods_price', sa.Float(), nullable=True),
    sa.Column('goods_id', sa.Integer(), nullable=True),
    sa.Column('amount', sa.Float(), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_order_biz_id'), 'order', ['biz_id'], unique=False)
    op.create_index(op.f('ix_order_customer_id'), 'order', ['customer_id'], unique=False)
    op.create_index(op.f('ix_order_flow_code'), 'order', ['flow_code'], unique=False)
    op.create_index(op.f('ix_order_goods_id'), 'order', ['goods_id'], unique=False)
    op.create_index(op.f('ix_order_status'), 'order', ['status'], unique=False)
    op.create_table('group_report',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('leader_cid', sa.Integer(), nullable=True),
    sa.Column('activity_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.Integer(), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=False),
    sa.Column('success_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activity.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_group_report_activity_id'), 'group_report', ['activity_id'], unique=False)
    op.create_index(op.f('ix_group_report_biz_id'), 'group_report', ['biz_id'], unique=False)
    op.create_index(op.f('ix_group_report_leader_cid'), 'group_report', ['leader_cid'], unique=False)
    op.create_table('group_member',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('group_report_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['group_report_id'], ['group_report.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_group_member_biz_id'), 'group_member', ['biz_id'], unique=False)
    op.create_index(op.f('ix_group_member_customer_id'), 'group_member', ['customer_id'], unique=False)
    op.create_index(op.f('ix_group_member_group_report_id'), 'group_member', ['group_report_id'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_group_member_group_report_id'), table_name='group_member')
    op.drop_index(op.f('ix_group_member_customer_id'), table_name='group_member')
    op.drop_index(op.f('ix_group_member_biz_id'), table_name='group_member')
    op.drop_table('group_member')
    op.drop_index(op.f('ix_group_report_leader_cid'), table_name='group_report')
    op.drop_index(op.f('ix_group_report_biz_id'), table_name='group_report')
    op.drop_index(op.f('ix_group_report_activity_id'), table_name='group_report')
    op.drop_table('group_report')
    op.drop_index(op.f('ix_order_status'), table_name='order')
    op.drop_index(op.f('ix_order_goods_id'), table_name='order')
    op.drop_index(op.f('ix_order_flow_code'), table_name='order')
    op.drop_index(op.f('ix_order_customer_id'), table_name='order')
    op.drop_index(op.f('ix_order_biz_id'), table_name='order')
    op.drop_table('order')
    op.drop_index(op.f('ix_goods_biz_id'), table_name='goods')
    op.drop_table('goods')
    op.drop_index(op.f('ix_activity_event_type'), table_name='activity')
    op.drop_index(op.f('ix_activity_biz_id'), table_name='activity')
    op.drop_table('activity')
    # ### end Alembic commands ###
