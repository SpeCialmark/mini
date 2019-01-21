import celery
import raven
from raven.contrib.celery import register_signal, register_logger_signal
from datetime import datetime

from store.activities.tasks import refresh_group_status, refresh_activity_status
from store.coupons.tasks import set_expired_flag, turn_off_coupons
from store.plans.tasks import finish_plan
from store.reservation.tasks import set_attend_flag, automatic_reservation
from store.videos.tasks import pull_event
from flask import Flask, Response
from store.config import cfg, _env
from store.database import db
from celery.schedules import crontab

# 构建个最小化的flask
app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = cfg['postgresql']
app.config['SQLALCHEMY_ECHO'] = True

db.init_app(app)


class Celery(celery.Celery):
    def on_configure(self):
        if 'celery_sentry_dsn' not in cfg:
            return
        client = raven.Client(cfg['celery_sentry_dsn'])
        # register a custom filter to filter out duplicate logs
        register_logger_signal(client)
        # hook into the Celery error handler
        register_signal(client)


def create_celery(app):
    celery = Celery('store_celery',
                    broker=cfg['celery_broker'])
    celery.conf.update(
        result_backend=None,
        task_ignore_result=True,
        task_store_errors_even_if_ignored=True,
        timezone='Asia/Shanghai'
    )
    TaskBase = celery.Task

    class ContextTask(TaskBase):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)
    celery.Task = ContextTask
    return celery


celery = create_celery(app)


@celery.task()
def set_attend_flag_task():
    print('**set_attend_flag_task**', datetime.now().strftime('%H:%M:%S'))
    set_attend_flag()


@celery.task()
def seat_trigger_task():
    print('**seat_trigger_task**', datetime.now().strftime('%H:%M:%S'))
    automatic_reservation()


@celery.task()
def pull_event_task():
    # 拉取消息队列(主要用于获取视频转码结果)
    print('**pull_event_task**', datetime.now().strftime('%H:%M:%S'))
    pull_event()


@celery.task()
def set_coupon_expired_task():
    # 将过期的优惠券设置为过期
    print('**set_coupon_expired_task**', datetime.now().strftime('%H:%M:%S'))
    set_expired_flag()


@celery.task()
def set_coupon_switch_task():
    print('**set_coupon_switch_task**', datetime.now().strftime('%H:%M:%S'))
    turn_off_coupons()


@celery.task()
def refresh_group_status_task():
    # 每10分钟刷新一次即将到达成团期限的拼团状态(主要用于发送拼团失败通知)
    print('**refresh_group_status_second_task**', datetime.now().strftime('%H:%M:%S'))
    refresh_group_status()


@celery.task()
def refresh_activity_status_task():
    # 每日刷新活动的状态
    print('**refresh_activity_status_task**', datetime.now().strftime('%H:%M:%S'))
    refresh_activity_status()


@celery.task()
def finish_plan_task():
    print("**finish_plan_task**", datetime.now().strftime('%H:%M:%S'))
    finish_plan()


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(60, set_attend_flag_task, name='set_attend_flag_task')
    sender.add_periodic_task(crontab(minute='30,40,50', hour='23'), seat_trigger_task, name='seat_trigger_task')
    if _env != 'dev':
        sender.add_periodic_task(15, pull_event_task, name='pull_event_task')
        sender.add_periodic_task(crontab(minute=0, hour=0), set_coupon_expired_task, name='set_coupon_expired_task')
        sender.add_periodic_task(crontab(minute=5, hour=0), set_coupon_switch_task, name='set_coupon_switch_task')
        sender.add_periodic_task(crontab(minute=10, hour=0), refresh_activity_status_task, name='refresh_activity_status_task')
        sender.add_periodic_task(600, refresh_group_status_task, name='refresh_group_status_task')
        sender.add_periodic_task(crontab(minute=15, hour=0), finish_plan_task, name='finish_plan_task')
