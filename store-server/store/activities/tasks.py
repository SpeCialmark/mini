from datetime import datetime, timedelta
from typing import List

from store.database import db
from store.domain.models import GroupReport, GroupStatus, Activity, ActivityStatus
from store.domain.wx_push import queue_and_send_group_fail_message
from store.utils import time_processing as tp


def refresh_group_status():
    # 每10分钟执行一次的任务(主要用于刷新即将达到成团期限的团的状态)
    now = datetime.now()
    nearly_time = now - timedelta(minutes=1)
    group_reports: List[GroupReport] = GroupReport.query.filter(
        GroupReport.status == GroupStatus.STANDBY.value,
        GroupReport.closed_at >= nearly_time,
        GroupReport.closed_at <= now,
    ).all()
    if not group_reports:
        return
    for group_report in group_reports:
        size = group_report.activity.get_size()
        # 若成团期限已到
        if group_report.closed_at - now <= timedelta(seconds=1):  # 预留1秒执行任务
            # 校验团队人数
            if size.get('max_size') >= group_report.members_count >= size.get('min_size'):
                # 达标
                group_report.status = GroupStatus.COMPLETED.value
                group_report.success_at = now
                db.session.commit()
            elif group_report.members_count <= size.get('min_size'):
                # 未达标
                group_report.status = GroupStatus.FAIL.value
                db.session.commit()
                queue_and_send_group_fail_message(group_report)

    return


def refresh_activity_status():
    today_min = tp.get_day_min(datetime.today())
    # 查询已经到达结束日期状态仍为进行中的活动
    activities: List[Activity] = Activity.query.filter(
        Activity.end_date < today_min,
        Activity.status == ActivityStatus.ACTION.value
    ).all()

    for activity in activities:
        activity.status = ActivityStatus.END.value
        activity.modified_at = datetime.now()
    db.session.commit()
    return
