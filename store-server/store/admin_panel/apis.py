from http import HTTPStatus
from typing import List
from flask import Blueprint, g, jsonify, request
from sqlalchemy import desc, asc, func, and_
import re
from store.domain.models import CheckIn, Customer, Store
from store.domain.middle import roles_required, permission_required
from store.domain.permission import ViewBizPermission
from datetime import datetime, timedelta, time
from store.database import db
from store.utils import time_processing as tp


blueprint = Blueprint('_admin_panel', __name__)


@blueprint.route('/check_in', methods=['GET'])
@permission_required(ViewBizPermission())
def get_check_in():
    """ 让所有身份的用户都能浏览  """
    biz_id = g.get('biz_id')

    start = request.args.get('start')
    end = request.args.get('end')

    start = datetime.strptime(start, '%Y.%m.%d')
    end = datetime.strptime(end, '%Y.%m.%d')

    # 查询
    if start == end:
        # 查询的是每日数据
        situation = get_day_situation(start, biz_id)
    else:
        situation = get_situation(start, end, biz_id)

    return jsonify(situation)


@blueprint.route('/check_in/ranking', methods=['GET'])
@permission_required(ViewBizPermission())
def get_check_in_ranking():
    # 获取排行榜
    biz_id = g.get('biz_id')
    start = request.args.get('start')
    end = request.args.get('end')

    page = request.args.get('page', 1, type=int)  # 页数

    start = datetime.strptime(start, '%Y.%m.%d')
    end = datetime.strptime(end, '%Y.%m.%d')

    if start == end:
        # 查询每日情况
        details = get_day_detail(start, biz_id, page)
    else:
        details = get_detail(start, end, biz_id, page)

    return jsonify(details)


@blueprint.route('/check_in/time_interval', methods=['GET'])
@permission_required(ViewBizPermission())
def get_check_in_time_interval():
    today = datetime.today()
    max_week = 9  # 最大周数 从0算起
    max_month = 2  # 最大月数 从0算起

    # 月初
    early_month = tp.get_early_month(today)

    first_month = tp.get_last_n_early_month(today, max_month)  # 获取最大区间的月初

    month_interval = []
    while early_month >= first_month:
        month_interval.append(get_month_time(early_month))  # 获取月份时间区间
        early_month = tp.get_last_early_month(early_month)

    # 获取当前周的周日
    sunday = tp.get_sunday(today)  # 6.13周三-->sunday = 6.10
    first_sunday = tp.get_last_n_sunday(sunday, max_week)  # 获取最大区间的周日

    week_interval = []
    while first_sunday < today:
        week_interval.append(get_week_time(first_sunday))
        first_sunday += timedelta(days=7)

    return jsonify({
        'week_interval': week_interval[::-1],
        'month_interval': month_interval
    })


def get_week_time(start):
    end = start + timedelta(days=6)
    return {
        'start': start.strftime("%Y.%m.%d"),
        'end': end.strftime("%Y.%m.%d")
    }


def get_month_time(early_month):
    # 月末
    end_month = tp.get_end_month(early_month)
    return {
        'start': early_month.strftime("%Y.%m.%d"),
        'end': end_month.strftime("%Y.%m.%d")
    }


def get_day_detail(start, biz_id, page):
    # 获取每日排行榜
    day_max = tp.get_day_max(start)

    check_ins: CheckIn = CheckIn.query.filter(
            CheckIn.biz_id == biz_id,
            CheckIn.check_in_date >= start,
            CheckIn.check_in_date <= day_max,
        ).order_by(asc(CheckIn.rank)).paginate(page=page, per_page=20, error_out=False)

    day_details = []
    for check_in in check_ins.items:
        checked_dict = get_checked_dict(check_in)
        day_details.append(checked_dict)

    return day_details


def get_detail(start_time, end_time, biz_id, page):
    # 分组查询
    check_ins = db.session.query(
        CheckIn.customer_id, func.count(CheckIn.check_in_date)
    ).filter(
        CheckIn.check_in_date >= start_time,
        CheckIn.check_in_date <= end_time,
        CheckIn.biz_id == biz_id
    ).order_by(
        desc(func.count(CheckIn.check_in_date)), asc(func.max(CheckIn.check_in_date))
    ).group_by(CheckIn.customer_id).paginate(page=page, per_page=20, error_out=False)
    # print(check_ins)  # [(3,3),(2,3)]

    check_in = CheckIn()  # 创建一个对象用于储存信息
    details = []
    for check in check_ins.items:
        check_in.customer_id = check[0]
        check_in.count_num = check[1]
        checked_dict = get_checked_dict(check_in)
        details.append(checked_dict)

    return details


def get_checked_dict(check_in):
    checked_dict = dict()
    checked_dict['customer'] = get_customer_data(check_in)
    if hasattr(check_in, 'check_in_date') and check_in.check_in_date is not None:
        checked_dict['check_times'] = check_in.check_in_date.strftime("%H:%M")
    else:
        checked_dict['count'] = check_in.count_num

    return checked_dict


def get_day_situation(start, biz_id):
    # 获取每日签到情况
    day_min = tp.get_day_min(start)
    day_max = tp.get_day_max(start)

    check_ins: List[CheckIn] = CheckIn.query.filter(
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= day_min,
        CheckIn.check_in_date <= day_max,
    ).order_by(asc(CheckIn.rank)).all()

    avatars = [get_customer_data(check_in).get('avatar') for check_in in check_ins]

    store: Store = Store.query.filter(Store.biz_id == biz_id).first()
    if not store:
        return jsonify(msg='商家不存在'), HTTPStatus.NOT_FOUND

    start_hhmm, end_hhmm = store.get_business_hours()
    start_time = int(start_hhmm / 60)
    end_time = int(end_hhmm / 60)
    hour_sum = []
    for i in range(start_time, end_time):
        hour_sum.append(get_hour_check_in(check_ins, start, start_hour=i))

    date = {
        "start_time": start_time,
        "end_time": end_time,
        "hour_sum": hour_sum,
        "avatars": avatars
    }

    return date


def get_situation(start, end, biz_id):
    # 获取周\月签到情况
    end = tp.get_day_max(end)
    check_ins: List[CheckIn] = CheckIn.query.filter(and_(
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= start,
        CheckIn.check_in_date <= end,
    )).order_by(desc(CheckIn.check_in_date)).all()

    day_min = tp.get_day_min(start)
    day_max = tp.get_day_max(start)
    checkin_sum = []
    date = []

    while day_min <= end:
        checkin_sum.append(get_day_check_in(day_min=day_min, day_max=day_max, check_ins=check_ins))
        date.append(day_min.strftime("%m月%d日"))
        day_min += timedelta(days=1)
        day_max += timedelta(days=1)

    check_ins = db.session.query(
        CheckIn.customer_id, func.count(CheckIn.check_in_date)) \
        .filter(CheckIn.check_in_date >= start,
                CheckIn.check_in_date <= end,
                CheckIn.biz_id == biz_id) \
        .order_by(desc(func.count(CheckIn.check_in_date))) \
        .group_by(CheckIn.customer_id).all()

    # print(check_ins)  # [(3,3),(2,3)]

    check_in = CheckIn()
    avatars = []
    for check in check_ins:
        check_in.customer_id = check[0]
        avatar = get_customer_data(check_in).get('avatar')
        avatars.append(avatar)

    return {
        "date": date,
        "checkin_sum": checkin_sum,
        "avatars": avatars
    }


def get_day_check_in(day_min, day_max, check_ins):
    week_sum = [check_in for check_in in check_ins if day_max >= check_in.check_in_date >= day_min]
    return len(week_sum)


def get_customer_data(check_in):
    customer: Customer = Customer.query.filter(Customer.id == check_in.customer_id).first()
    nick_name = customer.nick_name
    avatar = customer.avatar
    if not avatar:
        avatar = "https://oss.11train.com/user/avatar/defulate_avatar.png"
    if not nick_name:
        nick_name = "游客"
    return {
        'nick_name': nick_name,
        'avatar': avatar,
    }


def get_hour_check_in(check_ins, start, start_hour):
    # 获取每个时间段的打卡人数
    start_time = datetime(year=start.year, month=start.month, day=start.day, hour=start_hour)
    end_time = start_time + timedelta(hours=1)
    sum_list = [check_in for check_in in check_ins if start_time <= check_in.check_in_date <= end_time]
    return len(sum_list)
