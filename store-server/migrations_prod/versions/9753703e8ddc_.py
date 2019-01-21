"""empty message

Revision ID: 9753703e8ddc
Revises: d337417e0829
Create Date: 2018-11-17 18:09:46.113544

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '9753703e8ddc'
down_revision = 'd337417e0829'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('check_in', sa.Column('image', sa.String(), nullable=True))
    op.add_column('customer', sa.Column('arm_circumference', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('bfp', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('birthday', sa.Integer(), nullable=True))
    op.add_column('customer', sa.Column('bmi', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('bust', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('calf_circumference', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('gender', sa.Integer(), nullable=True))
    op.add_column('customer', sa.Column('height', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('hip_circumference', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('step_count', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('thigh_circumference', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('waistline', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('customer', sa.Column('weight', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('customer', 'weight')
    op.drop_column('customer', 'waistline')
    op.drop_column('customer', 'thigh_circumference')
    op.drop_column('customer', 'step_count')
    op.drop_column('customer', 'hip_circumference')
    op.drop_column('customer', 'height')
    op.drop_column('customer', 'gender')
    op.drop_column('customer', 'calf_circumference')
    op.drop_column('customer', 'bust')
    op.drop_column('customer', 'bmi')
    op.drop_column('customer', 'birthday')
    op.drop_column('customer', 'bfp')
    op.drop_column('customer', 'arm_circumference')
    op.drop_column('check_in', 'image')
    # ### end Alembic commands ###
