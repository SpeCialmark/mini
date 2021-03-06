"""empty message

Revision ID: a392281d3567
Revises: 35198d2338d9
Create Date: 2018-12-01 16:08:35.047513

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a392281d3567'
down_revision = '35198d2338d9'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('body_data',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('record_type', sa.String(), nullable=True),
    sa.Column('data', sa.String(), nullable=True),
    sa.Column('recorded_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_body_data_biz_id'), 'body_data', ['biz_id'], unique=False)
    op.create_index(op.f('ix_body_data_customer_id'), 'body_data', ['customer_id'], unique=False)
    op.create_table('diary',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('recorded_at', sa.DateTime(), nullable=True),
    sa.Column('coach_note', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('customer_note', sa.String(), nullable=True),
    sa.Column('check_in_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('images', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('body_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('primary_mg', sa.ARRAY(sa.String()), nullable=True),
    sa.Column('secondary_mg', sa.ARRAY(sa.String()), nullable=True),
    sa.Column('training_type', sa.ARRAY(sa.String()), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_diary_biz_id'), 'diary', ['biz_id'], unique=False)
    op.create_index(op.f('ix_diary_customer_id'), 'diary', ['customer_id'], unique=False)
    op.create_table('diary_image',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('image', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_diary_image_customer_id'), 'diary_image', ['customer_id'], unique=False)
    op.create_table('plan',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('demand', sa.ARRAY(sa.String()), nullable=True),
    sa.Column('key_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('suggestion', sa.String(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('effective_at', sa.DateTime(), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('modified_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_plan_biz_id'), 'plan', ['biz_id'], unique=False)
    op.create_index(op.f('ix_plan_customer_id'), 'plan', ['customer_id'], unique=False)
    op.drop_column('customer', 'bust')
    op.drop_column('customer', 'arm_circumference')
    op.drop_column('customer', 'waistline')
    op.drop_column('customer', 'bfp')
    op.drop_column('customer', 'weight')
    op.drop_column('customer', 'bmi')
    op.drop_column('customer', 'calf_circumference')
    op.drop_column('customer', 'hip_circumference')
    op.drop_column('customer', 'thigh_circumference')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('customer', sa.Column('thigh_circumference', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.add_column('customer', sa.Column('hip_circumference', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.add_column('customer', sa.Column('calf_circumference', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.add_column('customer', sa.Column('bmi', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.add_column('customer', sa.Column('weight', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.add_column('customer', sa.Column('bfp', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.add_column('customer', sa.Column('waistline', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.add_column('customer', sa.Column('arm_circumference', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.add_column('customer', sa.Column('bust', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.drop_index(op.f('ix_plan_customer_id'), table_name='plan')
    op.drop_index(op.f('ix_plan_biz_id'), table_name='plan')
    op.drop_table('plan')
    op.drop_index(op.f('ix_diary_image_customer_id'), table_name='diary_image')
    op.drop_table('diary_image')
    op.drop_index(op.f('ix_diary_customer_id'), table_name='diary')
    op.drop_index(op.f('ix_diary_biz_id'), table_name='diary')
    op.drop_table('diary')
    op.drop_index(op.f('ix_body_data_customer_id'), table_name='body_data')
    op.drop_index(op.f('ix_body_data_biz_id'), table_name='body_data')
    op.drop_table('body_data')
    # ### end Alembic commands ###
