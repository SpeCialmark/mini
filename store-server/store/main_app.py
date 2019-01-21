from flask import Flask
import logging.config
from raven.contrib.flask import Sentry
from store.config import cfg
from store.database import db
from store import (store, user, courses, coaches, biz_user,
                   biz_list, codebase, group_course, check_in,
                   feed, admin_panel, coach, reservation, trainee, invitations, permissions, videos,
                   group_course_v2, places, salesmen, share, shake, agent, index, robot, registration, coupons,
                   statistics, activities, goods, posters, diaries, plans, exs, manager, work_reports, customers)
from flask_script import Manager
from flask_migrate import Migrate, MigrateCommand
from flask_cors import CORS


def create_main_app():
    app = Flask(__name__)
    set_config(app)
    # apm.init_app(app)
    register_extensions(app)
    register_blueprints(app)
    return app


def set_config(app):
    if 'sentry_dsn' in cfg:
        sentry = Sentry()
        sentry.init_app(app, dsn=cfg['sentry_dsn'])
    # logging.config.dictConfig(cfg['logging_conf'])
    logging.getLogger('flask_cors').level = logging.DEBUG

    app.config['SECRET_KEY'] = cfg['SECRET_KEY']
    app.config['SQLALCHEMY_DATABASE_URI'] = cfg['postgresql']
    app.config['SQLALCHEMY_ECHO'] = True
    # app.config['ELASTIC_APM'] = cfg['STORE_ELASTIC_APM']


def register_extensions(app):
    """Register Flask extensions."""
    db.init_app(app)
    # migrate 没有输出, 暂时不好用, 故注释掉
    migrate = Migrate()
    migrate.init_app(app, db)
    script_manager = Manager(app)
    script_manager.add_command('db', MigrateCommand)


def register_blueprints(app):
    CORS(app)  # 设置跨域
    app.register_blueprint(store.apis.blueprint, url_prefix='/api/v1/store')
    app.register_blueprint(user.apis.blueprint, url_prefix='/api/v1/user')
    app.register_blueprint(courses.apis.blueprint, url_prefix='/api/v1/courses')
    app.register_blueprint(coaches.apis.blueprint, url_prefix='/api/v1/coaches')
    app.register_blueprint(biz_user.apis.blueprint, url_prefix='/api/v1/biz_user')
    # app.register_blueprint(group_course.apis.blueprint, url_prefix='/api/v1/group_courses')
    app.register_blueprint(group_course_v2.apis.blueprint, url_prefix='/api/v1/group_courses')
    app.register_blueprint(biz_list.apis.blueprint, url_prefix='/api/v1/biz_list')
    app.register_blueprint(codebase.apis.blueprint, url_prefix='/api/v1/codebase')
    app.register_blueprint(check_in.apis.blueprint, url_prefix='/api/v1/check_in')
    app.register_blueprint(feed.apis.blueprint, url_prefix='/api/v1/feed')
    app.register_blueprint(admin_panel.apis.blueprint, url_prefix='/api/v1/admin_panel')
    app.register_blueprint(coach.apis.blueprint, url_prefix='/api/v1/coach')
    app.register_blueprint(reservation.apis.blueprint, url_prefix='/api/v1/reservations')
    app.register_blueprint(invitations.apis.blueprint, url_prefix='/api/v1/invitations')
    app.register_blueprint(trainee.apis.blueprint, url_prefix='/api/v1/trainees')
    app.register_blueprint(permissions.apis.blueprint, url_prefix='/api/v1/permissions')
    app.register_blueprint(videos.apis.blueprint, url_prefix='/api/v1/videos')
    app.register_blueprint(places.apis.blueprint, url_prefix='/api/v1/places')
    app.register_blueprint(salesmen.apis.blueprint, url_prefix='/api/v1/salesmen')
    app.register_blueprint(share.apis.blueprint, url_prefix='/api/v1/share')
    app.register_blueprint(shake.apis.blueprint, url_prefix='/api/v1/shake')
    app.register_blueprint(agent.apis.blueprint, url_prefix='/api/v1/agent')
    app.register_blueprint(index.apis.blueprint, url_prefix='/api/v1/index')
    app.register_blueprint(robot.apis.blueprint, url_prefix='/api/v1/robot')
    app.register_blueprint(registration.apis.blueprint, url_prefix='/api/v1/registration')
    app.register_blueprint(coupons.apis.blueprint, url_prefix='/api/v1/coupons')
    app.register_blueprint(statistics.apis.blueprint, url_prefix='/api/v1/statistics')
    app.register_blueprint(goods.apis.blueprint, url_prefix='/api/v1/goods')
    app.register_blueprint(activities.apis.blueprint, url_prefix='/api/v1/activities')
    app.register_blueprint(posters.apis.blueprint, url_prefix='/api/v1/posters')
    app.register_blueprint(diaries.apis.blueprint, url_prefix='/api/v1/diaries')
    app.register_blueprint(plans.apis.blueprint, url_prefix='/api/v1/plans')
    app.register_blueprint(exs.apis.blueprint, url_prefix='/api/v1/exercises')
    app.register_blueprint(manager.apis.blueprint, url_prefix='/api/v1/manager')
    app.register_blueprint(work_reports.apis.blueprint, url_prefix='/api/v1/work_reports')
    app.register_blueprint(customers.apis.blueprint, url_prefix='/api/v1/customers')


def register_shellcontext(app):
    def shell_context():
        """Shell context objects."""
        return {
            'db': db
        }

    app.shell_context_processor(shell_context)

