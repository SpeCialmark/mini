"""empty message

Revision ID: 0f4021c7ef76
Revises: 24e920e9fe52
Create Date: 2018-12-15 18:29:56.561002

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0f4021c7ef76'
down_revision = '24e920e9fe52'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('department',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('leader_sid', sa.Integer(), nullable=True),
    sa.Column('members', sa.ARRAY(sa.Integer()), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_department_biz_id'), 'department', ['biz_id'], unique=False)
    op.create_index(op.f('ix_department_leader_sid'), 'department', ['leader_sid'], unique=False)
    op.create_table('work_report',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('staff_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('departments', sa.ARRAY(sa.Integer()), nullable=True),
    sa.Column('submitted_at', sa.DateTime(), nullable=True),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('viewers', sa.ARRAY(sa.Integer()), nullable=True),
    sa.Column('yymmdd', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'staff_id', 'customer_id', 'yymmdd', name='_wr_id_s_id_cs_id_ymd')
    )
    op.create_index(op.f('ix_work_report_biz_id'), 'work_report', ['biz_id'], unique=False)
    op.create_index(op.f('ix_work_report_customer_id'), 'work_report', ['customer_id'], unique=False)
    op.create_index(op.f('ix_work_report_staff_id'), 'work_report', ['staff_id'], unique=False)
    op.add_column('diary_image', sa.Column('diary_id', sa.Integer(), nullable=True))
    op.create_unique_constraint('_image_id_diary_id', 'diary_image', ['id', 'diary_id'])
    op.create_index(op.f('ix_diary_image_diary_id'), 'diary_image', ['diary_id'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_diary_image_diary_id'), table_name='diary_image')
    op.drop_constraint('_image_id_diary_id', 'diary_image', type_='unique')
    op.drop_column('diary_image', 'diary_id')
    op.drop_index(op.f('ix_work_report_staff_id'), table_name='work_report')
    op.drop_index(op.f('ix_work_report_customer_id'), table_name='work_report')
    op.drop_index(op.f('ix_work_report_biz_id'), table_name='work_report')
    op.drop_table('work_report')
    op.drop_index(op.f('ix_department_leader_sid'), table_name='department')
    op.drop_index(op.f('ix_department_biz_id'), table_name='department')
    op.drop_table('department')
    # ### end Alembic commands ###
