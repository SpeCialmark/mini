import time
from datetime import datetime

from store.database import db
from store.domain.cache import GroupReportsCache
from store.domain.models import EventType, CommodityType, Goods, Course, GroupStatus, GroupReport
from store.domain.wx_push import queue_and_send_group_success_message, queue_and_send_group_fail_message
from store.utils import time_processing as tp


def check_private_parameter(event_type, private_parameter):
    if event_type == EventType.Group:
        g_type = private_parameter.get('type')
        hid = private_parameter.get('id')
        min_size = private_parameter.get('min_size')
        max_size = private_parameter.get('max_size')
        # 校验id
        is_ok = check_id(g_type, hid)
        if not is_ok:
            return False, None, "商品不存在"
        # 校验参团人数
        is_ok, msg = check_size(min_size, max_size)
        if not is_ok:
            return False, None, msg

        return True, private_parameter, ""

    return False, None, ""


def check_rules(rules):
    if not rules:
        return False, ''
    for rule in rules:
        people = rule.get('people')
        prize = rule.get('prize')
        if not people or not prize:
            return False, rules
    return True, rules


def check_id(g_type, hid):
    if g_type == CommodityType.Goods:
        goods: Goods = Goods.find(hid)
        if not goods:
            return False
        return True
    elif g_type == CommodityType.Course:
        course: Course = Course.find(hid)
        if not course:
            return False
        return True
    else:
        return False


def check_size(min_size, max_size):
    min_size = int(min_size)
    max_size = int(max_size)
    if not min_size or not max_size:
        return False, "请输入参团人数"
    if min_size < 2:
        return False, "最小参团人数不能小于2人"
    if min_size > max_size:
        return False, "最大参团人数不能小于最小参团人数"

    return True, None


def check_lesson_time(start_time, end_time):
    if not start_time or not end_time:
        return False
    today_min = tp.get_day_min(datetime.today())
    if start_time < today_min:
        return False
    if end_time < start_time:
        return False
    return True


def update_group_report_status(group_report: GroupReport):
    size = group_report.activity.get_size()
    old_status = group_report.status
    # 人数达标时将状态改为成团成功
    if size.get('max_size') > group_report.members_count >= size.get('min_size'):
        group_report.status = GroupStatus.SUCCESS.value
        group_report.success_at = datetime.now()
        db.session.commit()
        db.session.refresh(group_report)
        # send template message
        if old_status != GroupStatus.SUCCESS.value:
            # 只在成团的时候发送一次成团成功的模板消息,成团后再拉人不继续发送
            queue_and_send_group_success_message(group_report)

    elif group_report.members_count == size.get('max_size'):
        # 人数达到团上限时,该团状态直接变为完结
        group_report.status = GroupStatus.COMPLETED.value
        group_report.closed_at = datetime.now()
        db.session.commit()

    group_report_cache = GroupReportsCache(group_report.biz_id, group_report.activity_id)
    group_report_cache.reload()
    return


def refresh_group_reports_redis(reports_cache):
    # reports_cache可以是group_report_cache也可以是user_group_report_cache
    group_reports = reports_cache.get('group_reports')
    # 这里的列表时从redis中读取的,内部不是数据库对象而是字典
    flag = 0
    for group_report in group_reports:
        now = time.time() * 1000
        closed_at = group_report.get('closed_at')
        status = group_report.get('status')
        r_id = GroupReport.decode_id(group_report.get('id'))
        # 服务器时间有可能发生偏移,会导致获取的时间与现实时间不一致
        # 若出现时间偏移的问题则需要手动校准服务器时间: sudo ntpdate pool.ntp.org
        if closed_at <= now:
            if status == GroupStatus.STANDBY.value:
                gr: GroupReport = GroupReport.query.filter(
                    GroupReport.id == r_id
                ).first()
                gr.status = GroupStatus.FAIL.value
                db.session.commit()
                flag += 1

            elif status == GroupStatus.SUCCESS.value:
                GroupReport.query.filter(GroupReport.id == r_id).update({
                    'status': GroupStatus.COMPLETED.value,
                    'closed_at': datetime.now()
                })
                db.session.commit()
                flag += 1

    if flag == 0:
        # 没有任何修改 直接返回缓存中的数据
        return group_reports
    reports_cache.reload()
    return reports_cache.get('group_reports')
