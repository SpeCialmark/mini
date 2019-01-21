"""empty message

Revision ID: 16aa0b032130
Revises: 1cb6cc297ff7
Create Date: 2018-08-11 10:52:09.932424

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '16aa0b032130'
down_revision = '1cb6cc297ff7'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('qrcode', sa.Column('app_head_img', sa.String(), nullable=True))
    op.add_column('qrcode', sa.Column('app_nick_name', sa.String(), nullable=True))
    op.add_column('store_biz', sa.Column('settings', sa.JSON(), nullable=True))
    op.drop_column('wx_authorizer', 'setting')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('wx_authorizer', sa.Column('setting', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.drop_column('store_biz', 'settings')
    op.drop_column('qrcode', 'app_nick_name')
    op.drop_column('qrcode', 'app_head_img')
    # ### end Alembic commands ###
