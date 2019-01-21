"""empty message

Revision ID: a44ce1603f96
Revises: 0f281678f466
Create Date: 2018-12-24 20:34:46.816001

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a44ce1603f96'
down_revision = '0f281678f466'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_unique_constraint('_lesson_trainee_id_course_id', 'lesson', ['trainee_id', 'course_id'])
    op.drop_constraint('_lesson_trainee_id_course_name', 'lesson', type_='unique')
    op.drop_column('lesson', 'course_name')
    op.drop_column('seat', 'course_name')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('seat', sa.Column('course_name', sa.VARCHAR(), autoincrement=False, nullable=True))
    op.add_column('lesson', sa.Column('course_name', sa.VARCHAR(), autoincrement=False, nullable=True))
    op.create_unique_constraint('_lesson_trainee_id_course_name', 'lesson', ['trainee_id', 'course_name'])
    op.drop_constraint('_lesson_trainee_id_course_id', 'lesson', type_='unique')
    # ### end Alembic commands ###