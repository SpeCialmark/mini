import time
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import List

from flask import Blueprint
from flask import jsonify, request, g
from sqlalchemy import true, false, desc, or_, asc, func

from store.database import db
from store.domain.cache import GroupReportsCache, UserGroupReportsCache, CustomerCache
from store.domain.middle import roles_required, permission_required
from store.domain.models import Customer, Salesman, WxOpenUser, Activity, Goods, Course, \
    ActivityStatus, GroupReport, GroupStatus, GroupMember, EventType
from store.domain.permission import ManageSalesmanPermission, ViewBizPermission
from store.domain.role import CustomerRole
from store.activities.utils import check_rules, check_private_parameter, update_group_report_status, \
    refresh_group_reports_redis
from store.notice import send_salesmen_email
from store.utils import time_processing as tp

blueprint = Blueprint('_activities', __name__)


# TODO 目前的活动只有拼团一种类别,之后的版本根据用户的需求来进行添加


@blueprint.route('/goods', methods=['GET'])
@permission_required(ManageSalesmanPermission())
def get_goods_list():
    biz_id = g.get('biz_id')
    goods: List[Goods] = Goods.query.filter(
        Goods.biz_id == biz_id,
        Goods.is_shelf == true()
    ).all()
    courses: List[Course] = Course.query.filter(
        Course.biz_id == biz_id,
        Course.course_type == 'public'
    ).all()

    goods_list = [{"id": gs.get_hash_id(), "name": gs.name, "price": gs.price} for gs in goods]
    courses_list = [{"id": c.get_hash_id(), "name": c.title} for c in courses]
    return jsonify({
        "goods": goods_list,
        "courses": courses_list
    })


@blueprint.route('/available', methods=['GET'])
@roles_required(CustomerRole())
def get_available_activity():
    """ 移动端首页显示可参与的活动(开了团的活动) """
    biz_id = g.get('biz_id')
    group_reports: List[GroupReport] = GroupReport.query.filter(
        GroupReport.biz_id == biz_id,
        or_(
            GroupReport.status == GroupStatus.STANDBY.value,
            GroupReport.status == GroupStatus.SUCCESS.value,
        )
    ).all()
    res = [group_report.activity.get_mini_brief() for group_report in group_reports]
    res.sort(key=lambda x: (x['end_date']))
    return jsonify({
        "activities": res
    })


@blueprint.route('', methods=['GET'])
@permission_required(ViewBizPermission())
def get_activities():
    """ 获取所有活动列表(我的页面) """
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    res = []
    if w_id:
        # 只显示已经有团的活动,没有开团的活动不显示(由于目前只有会籍能够开团,为了避免用户看到活动后想发起拼团却发现不能发起)
        group_reports: List[GroupReport] = GroupReport.query.filter(
            GroupReport.biz_id == biz_id,
            GroupReport.status >= GroupStatus.STANDBY.value,
            GroupReport.status <= GroupStatus.SUCCESS.value,
        ).order_by(desc(GroupReport.created_at)).all()
        # 只展示可以参团的活动
        for group_report in group_reports:
            brief = group_report.activity.get_mini_brief()
            if brief not in res:
                res.append(brief)
    # PC
    else:
        activities: List[Activity] = Activity.query.filter(
            Activity.biz_id == biz_id,
        ).order_by(desc(Activity.status), desc(Activity.created_at)).all()
        for activity in activities:
            res.append(activity.get_brief())

    return jsonify({
        "activities": res
    })


@blueprint.route('/<string:a_id>', methods=['GET'])
@roles_required()
def get_activity(a_id):
    """ 获取活动详情 """
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    activity: Activity = Activity.find(a_id)
    if not activity:
        return jsonify(msg='该活动不存在'), HTTPStatus.NOT_FOUND
    brief = activity.get_brief()
    if w_id:
        wx_user: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.id == w_id
        ).first()
        if not wx_user:
            return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

        customer_id = wx_user.customer_id
        customer: Customer = Customer.query.filter(
            Customer.id == customer_id,
            Customer.biz_id == biz_id
        ).first()
        if not customer:
            return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

        mini_brief = activity.get_mini_brief()
        group_reports_cache = GroupReportsCache(biz_id, activity.id)
        group_reports = refresh_group_reports_redis(group_reports_cache)
        # 只显示未成团的
        reports = [group_report for group_report in group_reports if
                   group_report.get('status') == GroupStatus.STANDBY.value]
        group_reports.sort(key=lambda x: (x['lack_count'], -x['closed_at']))

        return jsonify({
            'activity': mini_brief,
            'group_reports': reports
        })

    return jsonify({
        'activity': brief,
    })


@blueprint.route('/group', methods=['POST'])
@permission_required(ManageSalesmanPermission())
def post_group_activity():
    """ 新增拼团活动 """
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    event_type = json_data.get('event_type')
    if event_type not in EventType.All:
        return jsonify(msg='类别错误'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    start_date_str = json_data.get('start_date')
    end_date_str = json_data.get('end_date')
    rules = json_data.get('rules')
    join_price = json_data.get('join_price')
    cover_image = json_data.get('cover_image')
    private_parameter = json_data.get('private_parameter')

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")

    if start_date <= tp.get_day_min(datetime.today()) <= end_date:
        status = ActivityStatus.ACTION.value
    elif start_date > tp.get_day_min(datetime.today()):
        status = ActivityStatus.READY.value
    else:
        return jsonify(msg='请选择正确的开始或结束时间'), HTTPStatus.BAD_REQUEST

    old_activity: Activity = Activity.query.filter(
        Activity.biz_id == biz_id,
        Activity.name == name,
        Activity.event_type == event_type
    ).first()
    if old_activity:
        return jsonify(msg='该活动已存在'), HTTPStatus.BAD_REQUEST

    is_ok, rules = check_rules(rules)
    if not is_ok:
        return jsonify(msg='规则有误,请重新设定规则'), HTTPStatus.BAD_REQUEST
    is_ok, private_parameter, msg = check_private_parameter(event_type, private_parameter)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    new_activity = Activity(
        biz_id=biz_id,
        name=name,
        start_date=start_date,
        end_date=end_date,
        join_price=join_price or 0,
        cover_image=cover_image,
        event_type=event_type,
        rules=rules,
        private_parameter=private_parameter,
        status=status,
        created_at=datetime.now()
    )
    db.session.add(new_activity)
    db.session.commit()
    return jsonify(msg='添加拼团活动成功')


@blueprint.route('/<string:a_id>', methods=['PUT'])
@permission_required(ManageSalesmanPermission())
def put_group_activity(a_id):
    """ 修改拼团活动 """
    biz_id = g.get('biz_id')
    activity: Activity = Activity.find(a_id)
    if not activity:
        return jsonify(msg='该活动不存在'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    if activity.event_type == EventType.Group:
        group_report: GroupReport = GroupReport.query.filter(
            GroupReport.biz_id == biz_id,
            GroupReport.activity_id == activity.id,
            or_(
                GroupReport.status == GroupStatus.STANDBY.value,
                GroupReport.status == GroupStatus.SUCCESS.value,
            )
        ).first()
        if group_report:
            return jsonify(msg='该活动还有用于正在参与,无法修改'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    start_date_str = json_data.get('start_date')
    end_date_str = json_data.get('end_date')
    cover_image = json_data.get('cover_image')
    rules = json_data.get('rules')
    join_price = json_data.get('join_price')
    private_parameter = json_data.get('private_parameter')

    is_ok, rules = check_rules(rules)
    if not is_ok:
        return jsonify(msg='规则设置有误, 请重新设定规则'), HTTPStatus.BAD_REQUEST
    is_ok, private_parameter, msg = check_private_parameter(activity.event_type, private_parameter)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")

    if start_date <= tp.get_day_min(datetime.today()) <= end_date:
        status = ActivityStatus.ACTION.value
    elif start_date > tp.get_day_min(datetime.today()):
        status = ActivityStatus.READY.value
    else:
        return jsonify(msg='请选择正确的开始或结束时间'), HTTPStatus.BAD_REQUEST

    if name and name != "":
        activity.name = name
    if join_price and join_price != "":
        activity.join_price = join_price
    if rules and rules != []:
        activity.rules = rules
    if cover_image and cover_image != "":
        activity.cover_image = cover_image

    activity.status = status
    activity.start_date = start_date
    activity.end_date = end_date
    activity.private_parameter = private_parameter

    activity.modified_at = datetime.now()
    db.session.commit()

    return jsonify(msg='修改成功')


@blueprint.route('/<string:a_id>', methods=['DELETE'])
@permission_required(ManageSalesmanPermission())
def close_group_active(a_id):
    """ 商家手动关闭活动 """
    activity: Activity = Activity.find(a_id)
    if not activity or activity.status == ActivityStatus.CLOSE.value:
        return jsonify(msg='该拼团活动不存在或已结束'), HTTPStatus.NOT_FOUND

    activity.status = ActivityStatus.CLOSE.value
    db.session.commit()
    return jsonify(msg='修改成功')


@blueprint.route('/<string:a_id>/group_report', methods=['POST'])
@roles_required(CustomerRole())
def post_group_report(a_id):
    """ 开团 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND
    salesman: Salesman = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.phone_number == customer.phone_number
    ).first()
    if not salesman:
        return jsonify(msg='很抱歉,您暂无开团权限'), HTTPStatus.BAD_REQUEST

    activity: Activity = Activity.find(a_id)
    if not activity or activity.status < ActivityStatus.READY.value:
        return jsonify(msg='该拼团活动不存在或已结束'), HTTPStatus.NOT_FOUND

    old_group_report: GroupReport = GroupReport.query.filter(
        GroupReport.biz_id == biz_id,
        GroupReport.leader_cid == c_id,
        GroupReport.activity_id == activity.id,
        or_(
            GroupReport.status == GroupStatus.SUCCESS.value,
            GroupReport.status == GroupStatus.STANDBY.value
        )
    ).first()

    if old_group_report:
        return jsonify(msg='您还有尚未结束的同类拼团,请勿重复开团'), HTTPStatus.BAD_REQUEST
    limit_time = int(activity.private_parameter.get('limit_time'))
    try:
        group_report = GroupReport(
            biz_id=biz_id,
            leader_cid=c_id,
            activity_id=activity.id,
            closed_at=datetime.now() + timedelta(minutes=limit_time),
            created_at=datetime.now()
        )
        db.session.add(group_report)
        db.session.flush()
        db.session.refresh(group_report)
        # 开团后团长也算是一位团员
        group_member = GroupMember(
            biz_id=biz_id,
            customer_id=c_id,
            group_report_id=group_report.id,
            created_at=datetime.now()
        )
        db.session.add(group_member)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e

    # 更新两份缓存
    group_report_cache = GroupReportsCache(biz_id, activity.id)
    group_report_cache.reload()
    user_group_report_cache = UserGroupReportsCache(c_id)
    user_group_report_cache.reload()
    return jsonify({
        'msg': '开团成功',
        'id': group_report.get_hash_id()
    })


@blueprint.route('group_reports/<string:r_id>/member', methods=['POST'])
@roles_required(CustomerRole())
def post_join(r_id):
    """ 参团 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    phone_number = json_data.get('phone_number')

    group_report: GroupReport = GroupReport.find(r_id)
    if not group_report or group_report.status == GroupStatus.COMPLETED.value:
        return jsonify(msg='拼团不存在或已结束')

    activity_id = group_report.activity_id

    old_group_member: GroupMember = GroupMember.query.filter(
        GroupMember.biz_id == biz_id,
        GroupMember.customer_id == c_id,
        GroupReport.status >= GroupStatus.STANDBY.value,  # GroupReport是外键连接的对象
        GroupReport.status <= GroupStatus.SUCCESS.value,
    ).first()

    if old_group_member and old_group_member.group_report.activity_id == activity_id:
        return jsonify(msg='您已经参加了该拼团活动,请勿重复参团'), HTTPStatus.BAD_REQUEST

    size = group_report.activity.get_size()
    if group_report.members_count >= size.get('max_size'):
        return jsonify(msg='该团人数已满'), HTTPStatus.BAD_REQUEST

    group_member = GroupMember(
        biz_id=biz_id,
        customer_id=c_id,
        group_report_id=group_report.id,
        created_at=datetime.now()
    )

    if not customer.phone_number:
        customer.phone_number = phone_number
        customer_cache = CustomerCache(customer.id)
        customer_cache.set({'phone_number': phone_number})

    db.session.add(group_member)
    db.session.commit()
    db.session.refresh(group_member)

    # 更新团状态(已经成团的时候不需要更新状态)
    update_group_report_status(group_report)

    # send email
    leader: Customer = Customer.query.filter(
        Customer.id == group_report.leader_cid
    ).first()
    salesman: Salesman = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.phone_number == leader.phone_number,
        Salesman.is_official == true()
    ).first()
    if salesman and salesman.email:
        # 有邮箱才发邮件
        email = [salesman.email]
        content = '有新的客户参与了您的拼团活动:\n姓名{name},电话号码{phone_number}'.format(
            name=customer.nick_name, phone_number=customer.phone_number
        )
        notice_title = '您有新的拼团客户'
        send_salesmen_email(subject=notice_title, text=content, recipient=email)

    user_group_report_cache = UserGroupReportsCache(c_id)
    user_group_report_cache.reload()
    return jsonify(msg='参团成功')


@blueprint.route('/group_reports/<string:r_id>', methods=['GET'])
@roles_required(CustomerRole())
def get_group_report(r_id):
    """ 获取拼团信息详情 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND
    group_report: GroupReport = GroupReport.find(r_id)
    if not group_report:
        return jsonify(msg='该拼团不存在'), HTTPStatus.NOT_FOUND
    now = time.time()
    brief = group_report.get_brief()
    # 服务器时间有可能发生偏移,会导致获取的时间与现实时间不一致
    # 若出现时间偏移的问题则需要手动校准服务器时间: sudo ntpdate pool.ntp.org
    if now * 1000 >= brief.get('closed_at'):
        if group_report.status == GroupStatus.STANDBY.value:
            brief.update({'status': GroupStatus.FAIL.value})
            group_report.status = GroupStatus.FAIL.value
            db.session.commit()
        elif group_report.status == GroupStatus.SUCCESS.value:
            brief.update({'status': GroupStatus.COMPLETED.value})
            group_report.status = GroupStatus.COMPLETED.value
            db.session.commit()

    brief.update({'created_at': group_report.created_at.strftime("%Y-%m-%d %H:%M"),
                  'end_date': group_report.activity.end_date.strftime('%Y-%m-%d')})
    group_member: GroupMember = GroupMember.query.filter(
        GroupMember.biz_id == biz_id,
        GroupMember.group_report_id == group_report.id,
        GroupMember.customer_id == customer.id
    ).first()
    brief.update({
        'is_join': bool(group_member),
        'a_id': group_report.activity.get_hash_id()
    })
    return jsonify({
        'group_report': brief
    })
