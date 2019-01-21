import time

import re
from datetime import datetime
from typing import List

from flask import Blueprint
from flask import jsonify, request, g
from http import HTTPStatus

from sqlalchemy import or_, and_, asc, true, desc

from store.database import db
from store.domain.cache import SalesmanCache, StoreBizCache, AppCache, SeatCheckCache, SeatCodeCache, CoachCache
from store.domain.middle import roles_required, permission_required
from store.domain.models import Registration, Salesman, Customer, WxOpenUser, Store, StoreBiz, Seat, Trainee, \
    Beneficiary, ContractContent, SeatCheckLog
from store.domain.wx_push import queue_and_send_seat_check_message
from store.notice import send_salesmen_email
from store.registration.utils import get_seat_course_name
from store.utils.pc_push import push_registration_message
from store.domain.permission import ManageRegistrationPermission
from store.domain.role import CustomerRole
from store.utils import time_processing as tp
from store.utils.sms import verify_sms_code
from store.utils.WXBizDataCrypt import WXBizDataCrypt
from store.utils.time_formatter import yymmdd_to_datetime

blueprint = Blueprint('_registration', __name__)


@blueprint.route('', methods=['GET'])
@permission_required(ManageRegistrationPermission())
def get_registrations():
    """ 获取到店预约列表 """
    biz_id = g.get('biz_id')
    today = tp.get_day_min(datetime.today())
    r_date_str = request.args.get('date', default=today.strftime('%Y.%m.%d'), type=str)
    r_date = datetime.strptime(r_date_str, '%Y.%m.%d')
    r_date_max = tp.get_day_max(r_date)
    r_date_min = tp.get_day_min(r_date)

    rs: List[Registration] = Registration.query.filter(
        Registration.biz_id == biz_id,
        or_(
            and_(
                Registration.reservation_date >= r_date_min,
                Registration.reservation_date <= r_date_max,
            ),
            and_(
                Registration.arrived_at >= r_date_min,
                Registration.arrived_at <= r_date_max,
            )
        )
    ).all()

    not_arrived = []
    arrived = []
    for r in rs:
        brief = r.get_brief()
        brief.update({'mini_salesman_name': get_mini_salesman(r)})
        if r.is_arrived is False:
            not_arrived.append(brief)
        else:
            arrived.append(brief)

    not_arrived.sort(key=lambda x: (x['reservation_time']))  # 未到店的按照预约时间从早到晚排序
    arrived.sort(key=lambda x: (x['arrived_at']))  # 已到店的按照到店时间从早到晚排序
    return jsonify({
        'not_arrived': not_arrived,
        'arrived': arrived,
        'is_today': bool(r_date_min == today),
    })


@blueprint.route('', methods=['POST'])
@permission_required(ManageRegistrationPermission())
def post_registration():
    """ 前台手动新增到店登记 """
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    phone_number = json_data.get('phone_number')
    belong_salesman_id = json_data.get('belong_salesman_id')
    note = json_data.get('note')

    if not all([name, phone_number, belong_salesman_id]):
        return jsonify(msg='请将信息填写完整'), HTTPStatus.BAD_REQUEST

    if not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号有误'), HTTPStatus.BAD_REQUEST

    salesman: Salesman = Salesman.find(belong_salesman_id)
    if not salesman:
        return jsonify(msg='该会籍不存在'), HTTPStatus.NOT_FOUND
    now = datetime.now()
    r = Registration(
        biz_id=biz_id,
        name=name,
        phone_number=phone_number,
        belong_salesman_id=salesman.id,
        is_arrived=True,
        arrived_at=now,
        created_at=now,
    )
    if note and note != "":
        r.note = note

    db.session.add(r)
    db.session.commit()
    if salesman.email:
        # 有邮箱才发邮件
        email = [salesman.email]
        send_email(email, r)

    return jsonify(msg='添加成功')


@blueprint.route('/<string:r_id>', methods=['PUT'])
@permission_required(ManageRegistrationPermission())
def put_registration(r_id):
    r: Registration = Registration.find(r_id)
    if not r:
        return jsonify(msg='错误的记录'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    new_belong_sid = json_data.get('belong_salesman_id')
    note = json_data.get('note')
    new_salesman: Salesman = Salesman.find(new_belong_sid)
    if not new_salesman:
        return jsonify(msg='该会籍不存在'), HTTPStatus.NOT_FOUND

    if name:
        r.name = name
    if note:
        r.note = note

    old_belong_sid = r.belong_salesman_id
    if new_salesman.id != old_belong_sid:
        r.belong_salesman_id = new_salesman.id
        s_cache = SalesmanCache(new_salesman.id)
        if s_cache.get('email'):
            # 有邮箱才发邮件
            email = [s_cache.get('email')]
            send_email(email, r)

    db.session.commit()
    return jsonify(msg='修改成功')


@blueprint.route('/<r_id>/arrived', methods=['POST'])
@permission_required(ManageRegistrationPermission())
def post_arrived(r_id):
    # 前台点击分配会籍
    r: Registration = Registration.find(r_id)
    if not r:
        return jsonify(msg='错误的记录'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    belong_salesman_id = json_data.get('belong_salesman_id')
    if not belong_salesman_id:
        return jsonify(msg='请为会员安排一位接待会籍'), HTTPStatus.BAD_REQUEST
    salesman: Salesman = Salesman.find(belong_salesman_id)
    if not salesman:
        return jsonify(msg='该会籍不存在'), HTTPStatus.NOT_FOUND

    now = datetime.now()
    r.belong_salesman_id = salesman.id
    r.is_arrived = True
    r.arrived_at = now
    r.modified_at = now

    db.session.commit()

    if salesman.email:
        # 有邮箱才发邮件
        email = [salesman.email]
        send_email(email, r)
    return jsonify(msg='成功到店')


@blueprint.route('/<string:r_id>/undo_arrived', methods=['POST'])
@permission_required(ManageRegistrationPermission())
def post_undo_arrived(r_id):
    """ 防止前台确认失误,允许其将已到店的状态撤回 """
    r: Registration = Registration.find(r_id)
    if not r:
        return jsonify(msg='错误的记录'), HTTPStatus.NOT_FOUND

    if not r.is_arrived:
        return jsonify(msg='状态错误'), HTTPStatus.BAD_REQUEST

    now = datetime.now()
    r.is_arrived = False
    r.arrived_at = None
    r.belong_salesman_id = None
    r.modified_at = now

    db.session.commit()
    db.session.refresh(r)

    return jsonify(msg='设置成功')


@blueprint.route('/salesmen', methods=['GET'])
@permission_required(ManageRegistrationPermission())
def get_salesmen():
    """ 用于前台录入时提供备选会籍 """
    biz_id = g.get('biz_id')
    salesmen: List[Salesman] = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.is_official == true()
    ).all()
    res = [{"id": s.get_hash_id(), "name": s.name} for s in salesmen]
    return jsonify({
        'salesmen': res
    })


@blueprint.route('/first_date', methods=['GET'])
@permission_required(ManageRegistrationPermission())
def get_first_date():
    """ 前台获取最早的日期 """
    biz_id = g.get('biz_id')
    r: Registration = Registration.query.filter(
        Registration.biz_id == biz_id
    ).order_by(asc(Registration.created_at)).first()
    if not r:
        first_date = datetime.today()
    else:
        first_date = r.created_at
    first_date_min = tp.get_day_min(first_date)
    t = time.mktime(first_date_min.timetuple())

    return jsonify({
        'first_date': first_date.strftime('%Y.%m.%d'),
        'time_int': t
    })


@blueprint.route('/customer/arrived', methods=['GET'])
@roles_required()
def customer_get_arrived():
    """ 获取扫码页面的信息 """
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    if not store:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND
    store_cache = StoreBizCache(biz_id)
    customer_app_id = store_cache.get('customer_app_id')
    if not customer_app_id:
        return jsonify(msg='客户端小程序不存在'), HTTPStatus.NOT_FOUND
    app_cache = AppCache(customer_app_id)
    name = app_cache.get('nick_name')
    banner = store.cards[0].get('images')[0]
    return jsonify({
        'banner': banner if banner else '',
        'name': name
    })


@blueprint.route('/customer/arrived', methods=['POST'])
@roles_required(CustomerRole())
def customer_post_arrived():
    """ 客户扫码到店 """
    biz_id = g.get('biz_id')
    # 登记类型(快捷登记或手动登记)
    arrived_type = request.args.get('arrived_type', default=ArrivedType.Fast, type=str)
    if arrived_type == ArrivedType.Fast:
        # 快捷登记
        # 获取用户的绑定手机号码
        json_data = request.get_json()
        if not json_data:
            return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

        phone_number = json_data.get('phone_number')
        if not phone_number or not re.match('^\d{11}$', phone_number):
            return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    elif arrived_type == ArrivedType.Manual:
        json_data = request.get_json()
        if not json_data:
            return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

        phone_number = json_data.get('phone_number')
        if not phone_number or not re.match('^\d{11}$', phone_number):
            return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

        sms_code = json_data.get('sms_code')
        if not sms_code:
            return jsonify(msg='验证码缺失'), HTTPStatus.BAD_REQUEST

        verified, msg = verify_sms_code(phone_number=phone_number, sms_code=sms_code)
        if not verified:
            return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    else:
        return jsonify(msg='类别错误'), HTTPStatus.BAD_REQUEST

    now = datetime.now()
    today_min = tp.get_day_min(now)
    today_max = tp.get_day_max(now)

    old_r: Registration = Registration.query.filter(
        Registration.biz_id == biz_id,
        Registration.phone_number == phone_number,
        Registration.arrived_at >= today_min,
        Registration.arrived_at <= today_max
    ).first()

    if old_r:
        return jsonify(msg='您今天已经登记过了,无需重复登记'), HTTPStatus.BAD_REQUEST

    customer_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    salesman_id = customer.belong_salesman_id if customer.belong_salesman_id and customer.belong_salesman_id != 0 else customer.salesman_id
    r = Registration(
        biz_id=biz_id,
        name=customer.nick_name,
        phone_number=phone_number,
        arrived_at=now,
        created_at=now,
        is_arrived=True,
        mini_salesman_id=salesman_id
    )
    db.session.add(r)
    db.session.commit()
    db.session.refresh(r)

    brief = r.get_brief()
    brief.update({'mini_salesman_name': get_mini_salesman(r)})
    push_registration_message(brief, StoreBiz.encode_id(biz_id))
    return jsonify(msg='成功到店!')


@blueprint.route('/customer/phone_number', methods=['POST'])
@roles_required(CustomerRole())
def get_customer_phone_number():
    """ 获取用户的绑定手机号码 """
    w_id = g.get('w_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    encrypted_data = json_data.get('encryptedData')
    iv = json_data.get('iv')
    if not all([encrypted_data, iv]):
        return jsonify(msg='数据不全'), HTTPStatus.BAD_REQUEST

    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.id == w_id
    ).first()
    if not wx_open_user:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

    pc = WXBizDataCrypt(wx_open_user.app_id, wx_open_user.session_key)
    res = pc.decrypt(encrypted_data, iv)
    return jsonify({
        'res': res
    })


@blueprint.route('/<string:r_id>/note', methods=['PUT'])
@permission_required(ManageRegistrationPermission())
def put_note(r_id):
    r: Registration = Registration.find(r_id)
    if not r:
        return jsonify(msg='无效的记录'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify()

    note = json_data.get('note')
    if note and note != '':
        r.note = note

    db.session.commit()
    return jsonify(msg='修改成功')


@blueprint.route('/salesman/customers', methods=['GET'])
@roles_required()
def get_customers():
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    res = []
    if w_id:
        wx_user: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.id == w_id
        ).first()
        if not wx_user:
            return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

        customer_id = wx_user.customer_id
        customer: Customer = Customer.query.filter(
            Customer.id == customer_id,
        ).first()
        if not customer:
            return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

        salesman: Salesman = Salesman.query.filter(
            Salesman.biz_id == biz_id,
            Salesman.phone_number == customer.phone_number
        ).first()
        if not salesman:
            return jsonify(res)
    # PC
    else:
        salesman_hid = request.args.get('salesman_id')
        salesman: Salesman = Salesman.find(salesman_hid)
        if not salesman:
            return jsonify(msg='会籍不存在'), HTTPStatus.NOT_FOUND

    registrations: List[Registration] = Registration.query.filter(
        Registration.biz_id == biz_id,
        Registration.belong_salesman_id == salesman.id,
        Registration.is_arrived == true()
    ).order_by(desc(Registration.arrived_at)).all()
    for r in registrations:
        brief = {
            'name': r.name,
            'phone_number': r.phone_number
        }
        if brief not in res:
            res.append(brief)

    return jsonify(res)


@blueprint.route('/seat/<string:code>', methods=['GET'])
@permission_required(ManageRegistrationPermission())
def get_seat(code):
    """ 通过课程码获取需要销课的课程信息 """
    code_cache = SeatCodeCache(code)
    seat_id = code_cache.get('seat_id')
    seat: Seat = Seat.query.filter(
        Seat.id == seat_id
    ).first()
    if not seat:
        return jsonify(msg='课程码有误'), HTTPStatus.NOT_FOUND
    if seat.is_check:
        return jsonify(msg='该课程码已核销'), HTTPStatus.BAD_REQUEST

    c_cache = CoachCache(seat.coach_id)
    c_brief = c_cache.get('brief')

    trainee: Trainee = Trainee.query.filter(
        Trainee.coach_id == seat.coach_id,
        Trainee.customer_id == seat.customer_id,
    ).first()

    if not trainee:
        return jsonify(msg='课程码有误'), HTTPStatus.NOT_FOUND
    course_name = get_seat_course_name(seat)

    return jsonify({
        "time": "{start_time}-{end_time}".format(
            start_time=seat.start_time.strftime("%H:%M"), end_time=seat.end_time.strftime("%H:%M")
        ),
        "coach": c_brief.get('name'),
        "trainee": trainee.name,
        "date": yymmdd_to_datetime(seat.yymmdd).strftime("%Y年%m月%d日"),
        "course_name": course_name
    })


@blueprint.route('/seat', methods=['POST'])
@permission_required(ManageRegistrationPermission())
def check_seat():
    """ 前台使用课程码销课 """
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing code'), HTTPStatus.BAD_REQUEST
    code = json_data.get('code')
    code_cache = SeatCodeCache(code)
    seat_id = code_cache.get('seat_id')
    seat: Seat = Seat.query.filter(
        Seat.id == seat_id
    ).first()
    if not seat:
        return jsonify(msg='课程码有误'), HTTPStatus.NOT_FOUND

    contract_content: ContractContent = ContractContent.query.filter(
        ContractContent.course_id == seat.course_id,
        ContractContent.is_group == seat.is_group,
        ContractContent.is_valid == true(),
        ContractContent.total > ContractContent.attended,
    ).order_by(asc(ContractContent.created_at)).first()
    if not contract_content:
        return jsonify(msg='所剩课时不足'), HTTPStatus.NOT_FOUND
    beneficiary: Beneficiary = Beneficiary.query.filter(
        Beneficiary.contract_id == contract_content.contract_id,
        Beneficiary.customer_id == seat.customer_id
    ).first()
    try:
        seat.is_check = True
        seat.checked_at = datetime.now()
        # 扣除课时 新版本中不再自动扣除课时 而是通过销课来进行扣除
        contract_content.attended += 1
        check_log = SeatCheckLog(
            biz_id=biz_id,
            seat_id=seat.id,
            name=beneficiary.name,
            phone_number=beneficiary.phone_number,
            checked_at=datetime.now()
        )
        db.session.add(check_log)
        db.session.commit()
        # 将两份缓存删除
        code_cache.delete()
        SeatCheckCache(seat_id).delete()
    except Exception as e:
        db.session.rollback()
        raise e
    # send message
    date = {"seat": seat}
    queue_and_send_seat_check_message(date)
    queue_and_send_seat_check_message(date, 'coach')
    return jsonify(msg='核销成功')


@blueprint.route('/seats', methods=['GET'])
@permission_required(ManageRegistrationPermission())
def get_seats():
    """ 前台查看销课记录 """
    biz_id = g.get('biz_id')
    date_str = request.args.get('date', default=None, type=str)
    if not date_str:
        today = datetime.today()
        date_min = tp.get_day_min(today)
        date_max = tp.get_day_max(today)
    else:
        date = datetime.strptime(date_str, "%Y.%m.%d")
        date_min = tp.get_day_min(date)
        date_max = tp.get_day_max(date)

    check_logs: List[SeatCheckLog] = SeatCheckLog.query.filter(
        SeatCheckLog.biz_id == biz_id,
        SeatCheckLog.checked_at >= date_min,
        SeatCheckLog.checked_at <= date_max
    ).all()

    res = []
    for log in check_logs:
        s: Seat = Seat.query.filter(
            Seat.id == log.seat_id
        ).first()
        coach_cache = CoachCache(s.coach_id)
        c_brief = coach_cache.get('brief')
        coach_name = c_brief.get('name')
        course_name = get_seat_course_name(s)
        seat_time = "{start_time}-{end_time}".format(
            start_time=s.start_time.strftime("%Y-%m-%d %H:%M"), end_time=s.end_time.strftime("%H:%M")
        )
        res.append({
            "phone_number": log.phone_number,
            "time": seat_time,
            "coach_name": coach_name,
            "checked_at": s.checked_at.strftime("%H:%M"),
            "course_name": course_name,
            "name": log.name
        })

    return jsonify({
        "seats": res
    })


def get_mini_salesman(registration) -> str:
    if not registration.mini_salesman_id:
        return '无'
    s_cache = SalesmanCache(registration.mini_salesman_id)
    name = s_cache.get('name')
    return name


def send_email(email, r: Registration):
    content = '您有新的到店客户:\n姓名{name},电话号码{phone_number}'.format(name=r.name, phone_number=r.phone_number)
    notice_title = '您有新的到店客户'
    send_salesmen_email(subject=notice_title, text=content, recipient=email)
    return


class ArrivedType:
    Fast = 'fast_arrived'  # 快捷登记
    Manual = 'manual_arrived'  # 手动登记
