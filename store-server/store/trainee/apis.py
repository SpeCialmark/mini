from http import HTTPStatus
from typing import List

import copy
from flask import Blueprint
from sqlalchemy import and_, desc, asc, func, true, or_, null

from store.config import get_res
from store.database import db
from store.diaries.apis import find_or_create
from store.domain.cache import TraineeCache, CustomerCache, StoreBizCache, DiaryUnreadCache, CoachCache, BizStaffCache, \
    CourseCache
from store.domain.key_data import get_nearest_record, get_base_data, get_circumference, get_physical_performance, \
    check_key_data, sort_key_data
from store.domain.models import Coach, Customer, Trainee, Seat, SeatStatus, LessonRecord, LessonRecordStatus, \
    SeatTrigger, SeatPriority, Plan, Diary, DiaryImage, BodyData, WorkReport, Contract, Beneficiary, ContractContent
from flask import jsonify, request, g
from datetime import datetime, timedelta
from store.group_course.apis import formatting_time
from store.domain.middle import roles_required, coach_id_require
from store.domain.role import CoachRole
from store.manager.apis import from_coach_get_staff
from store.registration.utils import get_seat_course_name
from store.reservation.apis import SeatWrap, SeatOneDay
from store.trainee.utils import get_lesson_profile, get_seat_profile, get_diary_profile, get_trainee_lesson
from store.utils.logs import post_log
from store.utils.time_formatter import get_yymmddhhmm, get_yymmdd, yymmdd_to_datetime, get_hhmm
from store.utils import time_processing as tp
from store.utils.time_processing import transform_timestr, transform_week_to_date
from store.diaries.utils import post_diary_image, get_nearest_seat, update_diary_body_data, delete_diary_image, \
    get_coach_notes

blueprint = Blueprint('_trainees', __name__)


@blueprint.route('', methods=['GET'])
@coach_id_require()
def get_trainees():
    coach_id = g.get('coach_id')
    if not coach_id:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    trainees: List[Trainee] = Trainee.query.filter(
        Trainee.coach_id == coach_id,
    ).all()

    trainees_list = classify_trainees(trainees, coach_id)
    c_cache = CoachCache(coach_id)
    unread_trainee = c_cache.get_unread()

    # 比对每个学员(添加红点)
    for tl in trainees_list:
        for t in tl.get('trainees'):
            if Customer.decode_id(t.get('customer_id')) in unread_trainee:
                t.update({
                    'unread': True
                })
            else:
                t.update({
                    'unread': False
                })
    return jsonify(trainees_list)


@blueprint.route('/<string:t_id>/profile', methods=["GET"])
@coach_id_require()
def get_profile(t_id):
    biz_id = g.get('biz_id')
    seat_hid = request.args.get('seat_id', default=None)
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND

    detail = trainee.get_detail()
    t_type = []
    if trainee.is_bind:
        t_type.append("私教")
    if trainee.is_exp:
        t_type.append("体验")
    if trainee.is_measurements:
        t_type.append("体测")

    diary_profile = get_diary_profile(trainee)
    profile = {
        "detail": detail,
        "diary": diary_profile,
        # 会员类别
        "type": t_type
    }

    customer: Customer = Customer.query.filter(
        Customer.id == trainee.customer_id
    ).first()
    avatar = "https://oss.11train.com/user/avatar/defulate_avatar.png"
    nick_name = "暂未获取"
    if customer:
        # boss端通过合同直接绑定上的暂时没有customer_id
        avatar = customer.avatar
        nick_name = customer.nick_name
        # 课时详情(课时分学员, 同一个用户对于不同的教练来说是不同的学员, 因此不同教练进入学员详情中的课时详情会不同)
        lesson_profile = get_lesson_profile(customer)
        profile.update({"lesson": lesson_profile})

    detail.update({
        "avatar": avatar,
        "nickName": nick_name,
        "phone_number": trainee.phone_number or "",
        "is_bind": trainee.is_bind,
    })

    if seat_hid:
        seat_profile = get_seat_profile(seat_hid)
        if seat_profile:
            profile.update({"seat": seat_profile})

    return jsonify(profile)


@blueprint.route('/<string:t_id>/course_names', methods=['GET'])
@roles_required(CoachRole())
def get_course_name(t_id):
    """ 教练端帮学员预约时获取课程名称 """
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    customer: Customer = Customer.query.filter(
        Customer.id == trainee.customer_id
    ).first()
    if not customer:
        return jsonify(msg='该会员尚未登录过'), HTTPStatus.BAD_REQUEST
    lesson_profile = get_lesson_profile(customer)
    return jsonify({
        "course_names": lesson_profile
    })


@blueprint.route('/<string:t_id>/contracts', methods=['GET'])
@roles_required(CoachRole())
def get_contracts(t_id):
    """ 教练端查看会员合同列表 """
    biz_id = g.get('biz_id')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND

    contract_ids = Beneficiary.get_contract_ids(biz_id, trainee.customer_id, trainee.phone_number)
    contracts: List[Contract] = Contract.query.filter(
        Contract.id.in_(contract_ids)
    ).order_by(desc(Contract.signed_at)).all()
    res = []
    for c in contracts:
        course_ids = c.get_courses()
        res.append({
            "id": c.get_hash_id(),
            "signed_at": c.signed_at.strftime("%m月%d日"),
            "course_names": [CourseCache(course_id).get('brief').get('title') for course_id in course_ids],
            "is_valid": c.is_valid,
            "is_group": c.is_group
        })

    return jsonify({
        "contracts": res
    })


@blueprint.route('/<string:t_id>/contracts/<string:c_id>', methods=['GET'])
@roles_required(CoachRole())
def get_contract(t_id, c_id):
    """ 教练端查看会员合同详情 """
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    contract: Contract = Contract.find(c_id)
    if not contract:
        return jsonify(msg='合同不存在'), HTTPStatus.NOT_FOUND

    page = contract.get_page()
    content: List[ContractContent] = ContractContent.query.filter(
        ContractContent.contract_id == contract.id
    ).all()
    for c in content:
        coach_cache = CoachCache(c.coach_id)
        course_cache = CourseCache(c.course_id)
        coach_brief = coach_cache.get('brief')
        course_brief = course_cache.get('brief')
        coach_name = coach_brief.get('name')
        course_name = course_brief.get('title')
        brief = {
            "coach_name": coach_name,
            "course_name": course_name,
            "total": c.total,
            "attended": c.attended,
            "price": c.price,
        }
        if brief not in page['content']:
            page['content'].append(brief)

    return jsonify({
        "contract": page
    })


@blueprint.route('/<string:t_id>/profile', methods=['PUT'])
@roles_required(CoachRole())
def put_trainee(t_id):
    trainee: Trainee = Trainee.find(t_id)
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json_data'), HTTPStatus.BAD_REQUEST

    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND

    detail = json_data.get('detail')
    if not detail:
        return jsonify(msg='missing detail'), HTTPStatus.BAD_REQUEST

    name = detail.get('name')
    age = detail.get('age')
    gender = detail.get('gender')
    tags = detail.get('tags')
    note = detail.get('note')
    phone_number = detail.get('phone_number')

    if name:
        trainee.name = name
    if age:
        trainee.age = age
    if gender:
        trainee.gender = gender
    if tags or tags == []:
        trainee.tags = tags
    if note or note == "":
        trainee.note = note
    if phone_number or phone_number == "":
        trainee.phone_number = phone_number

    db.session.commit()
    trainee_cache = TraineeCache(coach_id=trainee.coach_id, customer_id=trainee.customer_id)
    trainee_cache.reload()
    return jsonify(msg='修改成功')


@blueprint.route('/<string:t_id>', methods=['DELETE'])
@roles_required(CoachRole())
def delete_trainee(t_id):
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND

    # 解除绑定不删除数据
    trainee.is_bind = False
    trainee.unbind_at = datetime.now()
    trainee.modified_at = datetime.now()

    seat_triggers: List[SeatTrigger] = SeatTrigger.query.filter(and_(
        SeatTrigger.biz_id == biz_id,
        SeatTrigger.customer_id == trainee.customer_id,
        SeatTrigger.coach_id == coach_id
    )).all()
    for seat_trigger in seat_triggers:
        # 删除重复预约数据
        # delete reservation seat
        cancel_seat(seat_trigger)
        db.session.delete(seat_trigger)

    db.session.commit()
    trainee_cache = TraineeCache(coach_id=trainee.coach_id, customer_id=trainee.customer_id)
    trainee_cache.reload()
    # 刷新教练学员数量缓存
    coach_id = CoachRole(biz_id).get_id(g.role)
    c_cache = CoachCache(coach_id)
    c_cache.reload()
    return jsonify(msg='解除绑定成功')


@blueprint.route('/<string:t_id>/lesson_records', methods=['GET'])
@coach_id_require()
def get_lesson_records(t_id):
    coach_id = g.get('coach_id')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND

    lesson_records: List[LessonRecord] = LessonRecord.query.filter(and_(
        LessonRecord.customer_id == trainee.customer_id,
        LessonRecord.coach_id == coach_id,
    )).order_by(desc(LessonRecord.executed_at)).all()

    records = classify_records(lesson_records)

    return jsonify(records)


@blueprint.route('/<string:t_id>/lesson', methods=['GET'])
@coach_id_require()
def get_lesson(t_id):
    """ 销课记录 """
    coach_id = g.get('coach_id')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND

    seats: List[Seat] = Seat.query.filter(
        Seat.customer_id == trainee.customer_id,
        Seat.coach_id == coach_id,
        Seat.is_check == true()
    ).order_by(desc(Seat.checked_at)).all()

    res = []
    last_date = ''
    records = []
    for s in seats:
        date = yymmdd_to_datetime(s.yymmdd)
        month = date.strftime("%Y年%m月")
        if month != last_date:
            last_date = month
            res.append({
                "month": month,
                "records": records,
                "date": date.strftime("%Y%m%d")  # 排序用
            })
        records.append({
            "name": get_seat_course_name(s),
            "date": date.strftime("%m.%d"),
            "seat_time": "{start_time}-{end_time}".format(
                start_time=s.start_time.strftime("%H:%M"),
                end_time=s.end_time.strftime("%H:%M"),
            ),
            "check_time": s.checked_at.strftime("%m月%d日 %H:%M")
        })
    res.sort(key=lambda x: (x['date']), reverse=True)
    return jsonify(res)


@blueprint.route('/<string:t_id>/brief', methods=['GET'])
@coach_id_require()
def get_trainee_brief(t_id):
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    customer: Customer = Customer.query.filter(
        Customer.id == trainee.customer_id
    ).first()
    return jsonify({
        'name': trainee.name,
        'nick_name': customer.nick_name,
        'avatar': customer.avatar,
    })


@blueprint.route('/<string:t_id>/lessons', methods=['PUT'])
@roles_required(CoachRole())
def put_lessons(t_id):
    trainee: Trainee = Trainee.find(t_id)
    json_data = request.get_json()
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    if not json_data:
        return jsonify(msg='missing json_data'), HTTPStatus.BAD_REQUEST

    status = json_data.get('status')
    charge = json_data.get('charge')

    if not status:
        return jsonify(msg='请选择类别'), HTTPStatus.BAD_REQUEST

    if not charge:
        return jsonify(msg='请输入课时'), HTTPStatus.BAD_REQUEST

    if status == "plus":
        is_ok, msg = recharge_lesson(trainee, int(charge))
    elif status == "minus":
        is_ok, msg = deduction_lesson(trainee, int(charge))
    else:
        return jsonify(msg='类别错误'), HTTPStatus.BAD_REQUEST

    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    return jsonify({
        'remained': trainee.remained_lesson
    })


# @blueprint.route('/<string:t_id>/remained', methods=["GET"])
# @coach_id_require()
# def get_remained(t_id):
#     trainee: Trainee = Trainee.find(t_id)
#     if not trainee:
#         return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
#
#     return jsonify({
#         'remained': trainee.remained_lesson
#     })


@blueprint.route('/<string:t_id>/bind', methods=['POST'])
@roles_required(CoachRole())
def update_trainee(t_id):
    biz_id = g.get('biz_id')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND

    if trainee.is_bind:
        return jsonify(msg='该学员已经是你的私教会员了'), HTTPStatus.BAD_REQUEST
    now = datetime.now()
    trainee.bind_at = now
    trainee.is_bind = True
    trainee.is_exp = False
    trainee.unbind_at = None

    db.session.commit()
    db.session.refresh(trainee)
    # 成为私教后该会员直接从所有教练的体测会员列表中消失
    other_trainees: List[Trainee] = Trainee.query.filter(
        Trainee.customer_id == trainee.customer_id,
        Trainee.is_measurements == true(),
    ).all()
    for t in other_trainees:
        t.is_measurements = False
    db.session.commit()
    # 刷新教练学员数量缓存
    coach_id = CoachRole(biz_id).get_id(g.role)
    c_cache = CoachCache(coach_id)
    c_cache.reload()

    return jsonify(msg='绑定成功')


@blueprint.route('/<string:t_id>/seat_triggers', methods=['GET'])
@coach_id_require()
def get_seat_triggers(t_id):
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    trainee: Trainee = Trainee.find(t_id)

    if not trainee:
        return jsonify(msg='该学员不存在'), HTTPStatus.NOT_FOUND

    seat_triggers: List[SeatTrigger] = SeatTrigger.query.filter(and_(
        SeatTrigger.biz_id == biz_id,
        SeatTrigger.customer_id == trainee.customer_id,
        SeatTrigger.coach_id == coach_id,
    )).order_by(asc(SeatTrigger.week), asc(SeatTrigger.start)).all()

    seat_triggers_brief = [seat_trigger.get_brief() for seat_trigger in seat_triggers]

    return jsonify(seat_triggers_brief)


@blueprint.route('/seat_triggers/<string:s_id>', methods=['GET'])
@coach_id_require()
def get_seat_trigger(s_id):
    seat_trigger: SeatTrigger = SeatTrigger.find(s_id)
    if not seat_trigger:
        return jsonify(msg="该触发器不存在"), HTTPStatus.NOT_FOUND

    start = seat_trigger.start
    start_hh = int(start / 60)
    start_mm = start - start_hh * 60
    end = seat_trigger.end
    end_hh = int(end / 60)
    end_mm = end - end_hh * 60

    return jsonify({
        'start': "{:02d}:{:02d}".format(start_hh, start_mm),
        'end': "{:02d}:{:02d}".format(end_hh, end_mm),
        'week': seat_trigger.get_week_str()
    })


@blueprint.route('/seat_triggers/times', methods=['GET'])
@coach_id_require()
def get_seat_triggers_times():
    biz_id = g.get('biz_id')
    store_cache = StoreBizCache(biz_id)
    begin, end = store_cache.get('business_hours_begin', 'business_hours_end')

    times = []
    while begin <= end:
        hh = int(begin / 60)
        mm = begin - hh * 60
        start = "{:02d}:{:02d}".format(hh, mm)
        times.append(start)
        begin += 30

    return jsonify(times)


@blueprint.route('/<string:t_id>/seat_triggers', methods=['POST'])
@roles_required(CoachRole())
def post_seat_trigger(t_id):
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    json_data = request.get_json()

    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='该学员不存在'), HTTPStatus.NOT_FOUND
    if not json_data:
        return jsonify(msg='missing json_data'), HTTPStatus.BAD_REQUEST
    start = json_data.get('start')
    end = json_data.get('end')
    if not (start or end):
        return jsonify(msg='开始或结束时间缺失'), HTTPStatus.BAD_REQUEST

    start = transform_timestr(start)
    end = transform_timestr(end)

    if end <= start:
        return jsonify(msg='结束时间小于开始时间'), HTTPStatus.BAD_REQUEST

    week_str = json_data.get('week')
    week = tp.transform_weekstr(week_str)
    # 查询是否有冲突的触发器
    is_ok = get_conflict_trigger(json_data, biz_id, coach_id)
    if not is_ok:
        return jsonify(msg='您已经在该时间段为别的学员设置了重复预约'), HTTPStatus.BAD_REQUEST
    # 添加触发器
    set_seat_trigger(biz_id, trainee, week, start, end)

    next_date = transform_week_to_date(week)
    today = tp.get_day_min(datetime.today())
    now = datetime.now()
    now_int = now.hour * 60 + now.minute
    if next_date != today:
        post_reservation(trainee, next_date, start, end)
    else:
        if start > now_int:
            post_reservation(trainee, today, start, end)
        else:
            post_reservation(trainee, today+timedelta(days=7), start, end)

    return jsonify(msg='系统将会帮您的学员自动预约每周同一时间段的课程(以预约列表为准)')


@blueprint.route('/<string:t_id>/seat_triggers/<string:s_id>', methods=['PUT'])
@roles_required(CoachRole())
def put_seat_trigger(t_id, s_id):
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    json_data = request.get_json()
    seat_trigger = SeatTrigger.find(s_id)
    trainee: Trainee = Trainee.find(t_id)

    if not trainee:
        return jsonify(msg='该学员不存在'), HTTPStatus.NOT_FOUND

    if not seat_trigger:
        return jsonify(msg='seat_trigger not found'), HTTPStatus.NOT_FOUND

    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    # 查询是否有冲突
    is_ok = get_conflict_trigger(json_data, biz_id, coach_id)
    if not is_ok:
        return jsonify(msg='您已经在该时间段为别的学员设置了重复预约'), HTTPStatus.BAD_REQUEST
    # 修改触发器
    start = json_data.get('start')
    end = json_data.get('end')
    if not (start or end):
        return jsonify(msg='开始或结束时间缺失'), HTTPStatus.BAD_REQUEST
    start = transform_timestr(start)
    end = transform_timestr(end)
    if end <= start:
        return jsonify(msg='结束时间小于开始时间'), HTTPStatus.BAD_REQUEST
    week_str = json_data.get('week')
    week = tp.transform_weekstr(week_str)
    # 将已经预约好的课程取消
    cancel_seat(seat_trigger)
    seat_trigger.start = start
    seat_trigger.end = end
    seat_trigger.week = week
    db.session.commit()

    next_date = transform_week_to_date(week)
    today = tp.get_day_min(datetime.today())
    now = datetime.now()
    now_int = now.hour * 60 + now.minute
    if next_date != today:
        post_reservation(trainee, next_date, start, end)
    else:
        if start > now_int:
            post_reservation(trainee, today, start, end)
        else:
            post_reservation(trainee, today+timedelta(days=7), start, end)
    return jsonify(msg='系统将会帮您的学员自动预约每周同一时间段的课程(以预约列表为准)')


@blueprint.route('/<string:t_id>/seat_triggers/<string:s_id>', methods=['DELETE'])
@roles_required(CoachRole())
def delete_seat_trigger(t_id, s_id):
    seat_trigger: SeatTrigger = SeatTrigger.find(s_id)
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='该学员不存在'), HTTPStatus.NOT_FOUND
    if not seat_trigger:
        return jsonify(msg='seat_trigger not found'), HTTPStatus.NOT_FOUND

    # 将已经预约好的课程取消
    cancel_seat(seat_trigger)
    db.session.delete(seat_trigger)
    db.session.commit()

    return jsonify(msg='删除成功')


@blueprint.route('/<string:t_id>/plans', methods=['POST'])
@roles_required(CoachRole())
def post_trainee_plan(t_id):
    """ 教练给学员添加健身计划 """
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    plan_data = request.get_json()
    if not plan_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    title = plan_data.get('title')  # 阶段名称
    duration = plan_data.get('duration')  # 计划时长
    purpose = plan_data.get('purpose')  # 目的
    suggestion = plan_data.get('suggestion')  # 训练建议
    key_data = plan_data.get('key_data')  # 关键指标
    if not all([title, duration, purpose]):
        return jsonify(msg='请将计划填写完整'), HTTPStatus.BAD_REQUEST

    # 校验关键指标
    is_ok, msg, key_data = check_key_data(key_data)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST
    today = datetime.today()

    plan = Plan(
        biz_id=biz_id,
        customer_id=trainee.customer_id,
        title=title,
        purpose=purpose,
        duration=duration,
        key_data=key_data,
        created_at=today
    )
    db.session.add(plan)
    db.session.flush()
    if suggestion:
        plan.suggestion = suggestion

    db.session.commit()
    db.session.refresh(plan)
    DiaryUnreadCache(trainee.customer_id).modified(m_type='plan')
    post_log(
        biz_id=biz_id, operator_id=w_id, operation="新增",
        operating_object_id=trainee.customer_id,
        content="健身计划"
    )
    return jsonify()


@blueprint.route('/<string:t_id>/diaries', methods=['GET'])
@coach_id_require()
def get_trainee_diaries(t_id):
    """ 教练查看学员日记 """
    coach_id = g.get('coach_id')
    trainee: Trainee = Trainee.find(t_id)
    coach: Coach = Coach.query.filter(
        Coach.id == coach_id
    ).first()
    if not coach:
        return jsonify(msg='查看的教练不存在'), HTTPStatus.NOT_FOUND
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND

    c_staff = from_coach_get_staff(coach)
    if not c_staff:
        return jsonify(msg='员工不存在'), HTTPStatus.NOT_FOUND

    customer_id = trainee.customer_id
    diaries: List[Diary] = Diary.query.filter(
        Diary.customer_id == customer_id
    ).order_by(asc(Diary.recorded_at)).all()

    customer_cache = CustomerCache(customer_id)
    avatar = customer_cache.get('avatar')
    today = tp.get_day_min(datetime.today())
    seat_data = get_nearest_seat(today, customer_id)
    plan = Plan.get_effective_plan(customer_id)
    if not diaries:
        diary = {
                'id': 0,
                'customer_note': '',
                'coach_note': [],
                'check_in_data': None,
                'images': [],
                'primary_mg': [],
                'training_type': [],
                'body_data': get_nearest_record(trainee.customer_id, plan),
                'date': today.strftime('%m.%d'),
                'is_today': True,
                'workout': {'cards': []},
            }
        if seat_data:
            diary.update({'seat_data': seat_data})
        return jsonify({
            'diaries': [diary],
            'avatar': avatar
        })

    res = []
    for d in diaries:
        yymmdd = get_yymmdd(d.recorded_at)
        brief = d.get_brief(trainee.id)  # 传入id是为了获取教练端的蓝色icon
        brief.update({'is_today': bool(d.recorded_at == today)})
        brief.update({'coach_note': get_coach_notes(d.coach_note)})
        brief.update({'body_data': sort_key_data(d.body_data)})  # 将体测数据进度条按照选择页面的顺序排序
        brief.update({'workout': d.workout if d.workout else {'cards': []}})
        viewer = WorkReport.get_viewer(c_staff.id, customer_id, yymmdd)
        viewers = []
        for v in viewer:
            v_cache = BizStaffCache(v)
            viewers.append({
                "name": v_cache.get("name"),
                "avatar": v_cache.get("avatar")
            })
        brief.update({'viewers': viewers})
        res.append(brief)
    # 查看今日是否有日记
    if diaries[-1].recorded_at != today:
        # 虚拟今日日记
        res.append({
            'id': 0,
            'customer_note': '',
            'coach_note': [],
            'check_in_data': None,
            'images': [],
            'primary_mg': [],
            'training_type': [],
            'body_data': get_nearest_record(trainee.customer_id, plan),
            'date': today.strftime('%m.%d'),
            'is_today': True,
            'workout': {'cards': []},
        })
    # 已阅(消除红点)
    CoachCache(coach_id).is_read(trainee.customer_id)
    res[-1].update({
        'is_report': bool(WorkReport.query.filter(
            WorkReport.staff_id == c_staff.id,
            WorkReport.customer_id == trainee.customer_id,
            WorkReport.yymmdd == get_yymmdd(datetime.today())
        ).first())
    })
    # 若没有课则直接返回日记列表
    if not seat_data:
        return jsonify({
            'diaries': res,
            'avatar': avatar
        })

    # 在日记中添加上课提醒
    res[-1].update({
        'seat': seat_data
    })
    return jsonify({
        'diaries': res,
        'avatar': avatar

    })


@blueprint.route('/<string:t_id>/diaries/<string:d_id>/note', methods=['GET'])
@roles_required(CoachRole())
def get_trainee_diary_note(t_id, d_id):
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id).get_id(g.role)
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    diary: Diary = Diary.find(d_id)
    if not diary:
        return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
    if diary.customer_id != trainee.customer_id:
        return jsonify(msg='您无权查看其他学员的日记'), HTTPStatus.BAD_REQUEST
    # 同一个会员可以有多个教练的留言
    coach_notes = get_coach_notes(diary.coach_note)

    return jsonify({
        "coach_notes": coach_notes,
        "self_note": diary.get_coach_note(coach_id)
    })


@blueprint.route('/<string:t_id>/diaries/<string:d_id>/note', methods=['PUT'])
@roles_required(CoachRole())
def put_trainee_diary_note(t_id, d_id):
    """ 教练给学员日记留言 """
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    coach_id = CoachRole(biz_id).get_id(g.role)
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    note = json_data.get('note')

    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    try:
        diary, is_new = find_or_create(d_id, trainee.customer_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND

        if diary.customer_id != trainee.customer_id:
            # 非法操作时拒绝访问,但是由于教练端403会跳转到登陆页,因此使用400
            return jsonify(msg='非法操作'), HTTPStatus.BAD_REQUEST

        d_coach_notes = copy.deepcopy(diary.coach_note) or []
        if d_coach_notes:
            coach_ids = [n.get("coach_id") for n in d_coach_notes]
            if coach_id not in coach_ids:
                d_coach_notes.append({
                    'coach_id': coach_id,
                    'note': note
                })
            else:
                for coach_note in d_coach_notes:
                    if coach_note.get('coach_id') == coach_id:
                        coach_note.update({'note': note})
                        break

        else:
            d_coach_notes.append({
                'coach_id': coach_id,
                'note': note
            })
        diary.coach_note = d_coach_notes
        diary.modified_at = datetime.now()
        db.session.commit()
        post_log(
            biz_id=biz_id, operator_id=w_id, operation="修改",
            operating_object_id=trainee.customer_id,
            content="健身日记中的教练留言"
        )
    except Exception as e:
        db.session.rollback()
        raise e
    DiaryUnreadCache(trainee.customer_id).modified(m_type='note', note_msg=note)
    return jsonify(msg='修改成功')


@blueprint.route('/<string:t_id>/images', methods=['GET'])
@coach_id_require()
def get_trainee_images(t_id):
    """ 教练端获取学员健身相册 """
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    images: List[DiaryImage] = DiaryImage.query.filter(
        DiaryImage.customer_id == trainee.customer_id
    ).order_by(desc(DiaryImage.created_at)).all()
    res = []
    if not images:
        res.append({
            'd_id': 0,
            'date': datetime.today().strftime("%Y年%m月%d日"),
            'images': [],

        })
        return jsonify(res)
    last_date = ""
    for i in images:
        date = i.created_at.strftime('%Y年%m月%d日')
        if date != last_date:
            last_date = date
            diary: Diary = Diary.query.filter(
                Diary.customer_id == trainee.customer_id,
                Diary.recorded_at == tp.get_day_min(i.created_at)
            ).first()
            res.append({
                'd_id': diary.get_hash_id() if diary else 0,
                'date': date,
                'images': []
            })
        res[-1]['images'].append({
            'id': i.get_hash_id(),
            'image': i.image
        })

    if res[0].get('date') != datetime.today().strftime('%Y年%m月%d日'):
        res.insert(0, {
            'd_id': 0,
            'date': datetime.today().strftime('%Y年%m月%d日'),
            'images': []
        })
    return jsonify(res)


@blueprint.route('/<string:t_id>/diaries/<string:d_id>/images', methods=['POST'])
@roles_required(CoachRole())
def post_trainee_diary_image(t_id, d_id):
    """ 教练给学员上传健身相册 """
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    trainee: Trainee = Trainee.find(t_id)
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    image = json_data.get('image')
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    try:
        diary, is_new = find_or_create(d_id, trainee.customer_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
        msg = post_diary_image(diary, image)
        post_log(
            biz_id=biz_id, operator_id=w_id, operation="上传",
            operating_object_id=trainee.customer_id,
            content="健身照片"
        )
    except Exception as e:
        db.session.rollback()
        raise e
    DiaryUnreadCache(trainee.customer_id).modified(m_type='images')
    return jsonify({
        "d_id": diary.get_hash_id(),
        "msg": msg
    })


@blueprint.route('/<string:t_id>/diaries/<string:d_id>/images/<string:i_id>', methods=['DELETE'])
@roles_required(CoachRole())
def delete_image(t_id, d_id, i_id):
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    diary: Diary = Diary.find(d_id)
    if not diary:
        return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
    if diary.customer_id != trainee.customer_id:
        return jsonify(msg='您无权修改他人的日记'), HTTPStatus.FORBIDDEN

    msg = delete_diary_image(diary, i_id)
    DiaryUnreadCache(trainee.customer_id).modified(m_type='images')
    post_log(
        biz_id=biz_id, operator_id=w_id, operation="删除",
        operating_object_id=trainee.customer_id,
        content="健身照片"
    )
    return jsonify(msg=msg)


@blueprint.route('/<string:t_id>/diaries/<string:d_id>/training_type', methods=['GET'])
@roles_required(CoachRole())
def get_training_type(t_id, d_id):
    training_type = get_res(directory='training_type', file_name='training_type.yml').get('c_training_type')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    diary: Diary = Diary.find(d_id)
    if not diary:
        return jsonify({
            'all_type': training_type,
            'chose_type': []
        })
    if diary.customer_id != trainee.customer_id:
        return jsonify({
            'all_type': training_type,
            'chose_type': []
        })
    return jsonify({
        'all_type': training_type,
        'chose_type': diary.training_type or []
    })


@blueprint.route('/<string:t_id>/diaries/<string:d_id>/training_type', methods=['PUT'])
@roles_required(CoachRole())
def put_training_type(t_id, d_id):
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    training_type = json_data.get('training_type')

    try:
        diary, is_new = find_or_create(d_id, trainee.customer_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
        if diary.customer_id != trainee.customer_id:
            return jsonify(msg='您无权修改他人的日记'), HTTPStatus.FORBIDDEN

        diary.training_type = training_type
        diary.modified_at = datetime.now()
        db.session.commit()
        post_log(
            biz_id=biz_id, operator_id=w_id, operation="修改",
            operating_object_id=trainee.customer_id,
            content="训练类型"
        )
    except Exception as e:
        db.session.rollback()
        raise e
    DiaryUnreadCache(trainee.customer_id).modified(m_type='training')
    return jsonify(msg='修改成功')


@blueprint.route('/<string:t_id>/diaries/<string:d_id>/muscle_group', methods=['GET'])
@roles_required(CoachRole())
def get_muscle_group(t_id, d_id):
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    diary: Diary = Diary.find(d_id)
    if not diary:
        return jsonify({
            'primary_mg': [],
            'secondary_mg': []
        })
    if diary.customer_id != trainee.customer_id:
        return jsonify(msg='您无权查看他人的日记'), HTTPStatus.FORBIDDEN
    return jsonify({
        'primary_mg': diary.primary_mg or [],
        # 'secondary_mg': diary.secondary_mg
    })


@blueprint.route('/<string:t_id>/diaries/<string:d_id>/muscle_group', methods=['PUT'])
@roles_required(CoachRole())
def put_muscle_group(t_id, d_id):
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    primary_mg = json_data.get('primary_mg')
    # secondary_mg = json_data.get('secondary_mg')
    try:
        diary, is_new = find_or_create(d_id, trainee.customer_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
        if diary.customer_id != trainee.customer_id:
            return jsonify(msg='您无权修改他人的日记'), HTTPStatus.FORBIDDEN

        diary.primary_mg = primary_mg
        diary.modified_at = datetime.now()
        # diary.secondary_mg = secondary_mg
        db.session.commit()
        post_log(
            biz_id=biz_id, operator_id=w_id, operation="修改",
            operating_object_id=trainee.customer_id,
            content="训练部位"
        )
    except Exception as e:
        db.session.rollback()
        raise e
    DiaryUnreadCache(trainee.customer_id).modified(m_type='record')
    return jsonify(msg='修改成功')


@blueprint.route('/<string:t_id>/diaries/record', methods=['GET'])
@roles_required(CoachRole())
def get_trainee_record(t_id):
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    base_data = get_base_data()
    circumference = get_circumference()
    physical_performance = get_physical_performance()

    res = []
    b_res = []
    c_res = []
    p_res = []
    s_res = []

    plan = Plan.get_effective_plan(trainee.customer_id)
    nearest_record = get_nearest_record(trainee.customer_id, plan)
    for r in nearest_record:
        if r.get('name') in base_data.get('names'):
            b_res.append(r)
        elif r.get('name') in circumference.get('names'):
            c_res.append(r)
        elif r.get('name') in physical_performance.get('names'):
            p_res.append(r)
        else:
            s_res.append(r)

    res.append({
        'type': '基础数据',
        'res': b_res
    })
    res.append({
        'type': '围度',
        'res': c_res
    })
    res.append({
        'type': '体能成绩',
        'res': p_res
    })
    res.append({
        'type': '自定义指标',
        'res': s_res
    })
    return jsonify(res)


@blueprint.route('/<string:t_id>/diaries/<string:d_id>/record', methods=['PUT'])
@roles_required(CoachRole())
def put_trainee_record(t_id, d_id):
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    record = request.get_json()
    if not record:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    try:
        diary, is_new = find_or_create(d_id, trainee.customer_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
        today = datetime.today()
        records = request.get_json()  # [{'data': 45.5, 'name': '体重'}]
        for record in records:
            record_type = record.get('name')
            data = record.get('data')
            body_data = BodyData(
                biz_id=biz_id,
                customer_id=trainee.customer_id,
                record_type=record_type,
                data=data,
                recorded_at=today
            )
            db.session.add(body_data)
            db.session.commit()

        diary: Diary = Diary.query.filter(
            Diary.customer_id == trainee.customer_id,
            Diary.recorded_at == tp.get_day_min(today),
        ).first()
        if not diary:
            diary = Diary(
                biz_id=biz_id,
                customer_id=trainee.customer_id,
                recorded_at=tp.get_day_min(today),
                created_at=datetime.now()
            )
            db.session.add(diary)
            db.session.flush()
            db.session.refresh(diary)
        # 更新日记中的体测数据
        update_diary_body_data(diary, records)
        post_log(
            biz_id=biz_id, operator_id=w_id, operation="修改",
            operating_object_id=trainee.customer_id,
            content="体测数据"
        )
    except Exception as e:
        db.session.rollback()
        raise e

    customer_cache = CustomerCache(trainee.customer_id)
    customer_cache.reload()
    DiaryUnreadCache(trainee.customer_id).modified(m_type='record')
    return jsonify()


@blueprint.route('/unread', methods=['GET'])
@roles_required(CoachRole())
def get_diaries_unread():
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id).get_id(g.role)
    c_cache = CoachCache(coach_id)
    unread_trainee = c_cache.get_unread()
    return jsonify({
        'unread': bool(unread_trainee)
    })


def post_reservation(trainee, date, start, end):
    if trainee.is_bind:
        priority = SeatPriority.PRIVATE.value
    else:
        priority = SeatPriority.EXPERIENCE.value
    yymmdd = get_yymmdd(date)
    the_seat = SeatWrap(yymmdd=yymmdd, start=start, end=end, priority=priority)
    one_day = SeatOneDay(coach_id=trainee.coach_id, yymmdd=yymmdd)
    rs_is_ok, msg, _ = one_day.add_reserve_seat(
        the_seat, customer_id=trainee.customer_id, status=SeatStatus.CONFIRMED.value)  # 直接设置为已确认

    if not rs_is_ok:
        yymmdd = get_yymmdd(date+timedelta(days=7))
        the_seat = SeatWrap(yymmdd=yymmdd, start=start, end=end, priority=priority)
        one_day = SeatOneDay(coach_id=trainee.coach_id, yymmdd=yymmdd)
        rs_is_ok, msg, _ = one_day.add_reserve_seat(
            the_seat, customer_id=trainee.customer_id, status=SeatStatus.CONFIRMED.value)  # 直接设置为已确认
    return


def set_seat_trigger(biz_id, trainee, week, start, end):
    now = datetime.now()
    # 添加触发器
    seat_trigger = SeatTrigger(
        biz_id=biz_id,
        coach_id=trainee.coach_id,
        customer_id=trainee.customer_id,
        week=week,
        start=start,
        end=end,
        created_at=now,
    )
    db.session.add(seat_trigger)
    db.session.commit()
    return


def cancel_seat(seat_trigger):
    next_date = transform_week_to_date(seat_trigger.week)
    yymmdd = get_yymmdd(next_date)
    seat: Seat = Seat.query.filter(and_(
        Seat.coach_id == seat_trigger.coach_id,
        Seat.customer_id == seat_trigger.customer_id,
        Seat.yymmdd == yymmdd,
        Seat.is_valid == true(),
        Seat.start == seat_trigger.start,
        Seat.end == seat_trigger.end
    )).first()
    if seat:
        SeatOneDay.cancel(seat)
    return


def get_conflict_trigger(json_data, biz_id, coach_id):
    start = json_data.get('start')
    end = json_data.get('end')

    start = transform_timestr(start)
    end = transform_timestr(end)

    week_str = json_data.get('week')
    week = tp.transform_weekstr(week_str)

    seat_triggers: List[SeatTrigger] = SeatTrigger.query.filter(and_(
        SeatTrigger.biz_id == biz_id,
        SeatTrigger.coach_id == coach_id,
        SeatTrigger.week == week,
    )).all()

    slices = set(range(start, end, 5))
    sets = [set(range(seat_trigger.start, seat_trigger.end, 5)) for seat_trigger in seat_triggers]
    for s in sets:
        if s & slices:
            return False
    else:
        return True


def recharge_lesson(trainee, charge):
    """ 续课 """
    now = datetime.now()
    # 记录
    lesson_record = LessonRecord(
        created_at=now,
        executed_at=now,
        customer_id=trainee.customer_id,
        coach_id=trainee.coach_id,
        status=LessonRecordStatus.RECHARGE.value,
        charge=charge
    )
    # 续课
    trainee.total_lessons += charge
    db.session.add(lesson_record)
    db.session.commit()
    return True, ""


def deduction_lesson(trainee, charge):
    """ 减少课时 """
    now = datetime.now()
    # 记录
    lesson_record = LessonRecord(
        created_at=now,
        executed_at=now,
        customer_id=trainee.customer_id,
        coach_id=trainee.coach_id,
        status=LessonRecordStatus.DEDUCTION.value,
        charge=-charge
    )
    # 减少课时
    trainee.total_lessons -= charge
    db.session.add(lesson_record)
    db.session.commit()
    return True, ""


def classify_records(lesson_records):
    records = []
    early_months = []
    for lesson_record in lesson_records:
        # 获取所有的月份
        date = lesson_record.executed_at
        early_month = tp.get_early_month(date)
        if early_month not in early_months:
            early_months.append(early_month)

    for early_month in early_months:
        end_month = tp.get_end_month(early_month)
        record = get_month_records(early_month, end_month, lesson_records)
        records.append(record)

    return records


def get_month_records(early_month, end_month, lesson_records):
    records = []
    records_dict = {}
    for lesson_record in lesson_records:
        if early_month <= lesson_record.executed_at <= end_month:
            date = lesson_record.executed_at.strftime("%Y年%m月")
            record = get_record(lesson_record)
            records.append(record)
            records_dict['month'] = date
    records_dict['records'] = records
    return records_dict


def get_record(lesson_record):
    if lesson_record.status == LessonRecordStatus.RECHARGE.value:
        status = "续课"
    elif lesson_record.status == LessonRecordStatus.ATTENDED.value:
        status = "已上课"
    elif lesson_record.status == LessonRecordStatus.DEDUCTION.value:
        status = "减少课时"
    elif lesson_record.status == LessonRecordStatus.CANCEL.value:
        status = "取消上课"
    else:
        status = ""
    seat_time = ""
    if lesson_record.seat_id:
        seat: Seat = Seat.query.filter(Seat.id == lesson_record.seat_id).first()
        seat_date = yymmdd_to_datetime(seat.yymmdd)
        start, end = get_hhmm(seat.start, seat.end)
        seat_time = '({date} {start}-{end})'.format(date=seat_date.strftime("%m月%d日"), start=start, end=end)
    return {
        "status": status,
        "time": lesson_record.executed_at.strftime("%m月%d日 %H:%M"),
        "charge": lesson_record.charge,
        "seat_time": seat_time
    }


def classify_trainees(trainees, coach_id):
    all_trainees = []
    # 将学员分类
    newly = {
        "category": 'newly',
        "trainees": []
    }
    confirmed = {
        "category": 'confirmed',
        "trainees": []
    }
    attended = {
        "category": 'attended',
        "trainees": []
    }  # 过去15天上过课
    others = {
        "category": 'others',
        "trainees": []
    }
    experience = {
        "category": 'experience',
        "trainees": []
    }
    measurements = {
        "category": 'measurements',
        "trainees": []
    }
    un_bind = {
        "category": 'un_bind',
        "trainees": []
    }

    today = tp.get_day_min(datetime.today())

    for t in trainees:
        # 查询课时记录
        lesson_brief = get_trainee_lesson(t)
        if t.is_bind:
            t_type, trainee = get_trainee(t, coach_id, today)
            if t_type == 'new' and trainee:
                trainee.update(lesson_brief)
                newly['trainees'].append(trainee)
            elif t_type == 'confirmed' and trainee:
                trainee.update(lesson_brief)
                confirmed['trainees'].append(trainee)
            elif t_type == 'attended' and trainee:
                trainee.update(lesson_brief)
                attended['trainees'].append(trainee)
                attended['trainees'].sort(key=lambda x: (x['days']))  # 按照days的升序排序
            elif t_type == 'other' and trainee:
                trainee.update(lesson_brief)
                others['trainees'].append(trainee)
                others['trainees'].sort(key=lambda x: (x['days']))  # 按照days的升序排序

        if t.is_measurements:
            measurements['trainees'].append({
                "id": t.get_hash_id(),
                "avatar": CustomerCache(t.customer_id).get('avatar'),
                "name": t.name,
                "accepted_at": t.accepted_at.strftime("%Y年%m月%d日"),
                "customer_id": Customer.encode_id(t.customer_id),
                "phone_number": t.phone_number
            })

        if t.is_exp:
            experience['trainees'].append(get_experience(t))

        if t.unbind_at:
            un_bind['trainees'].append({
                "id": t.get_hash_id(),
                "avatar": CustomerCache(t.customer_id).get('avatar'),
                "name": t.name,
                "unbind_at": t.unbind_at.strftime("%Y年%m月%d日"),
                "customer_id": Customer.encode_id(t.customer_id),
                "phone_number": t.phone_number
            })

    all_trainees.append(newly)
    all_trainees.append(confirmed)
    all_trainees.append(attended)
    all_trainees.append(others)
    all_trainees.append(un_bind)
    all_trainees.append(experience)
    all_trainees.append(measurements)
    return all_trainees


def get_experience(trainee):
    seat: Seat = Seat.query.filter(and_(
        Seat.customer_id == trainee.customer_id,
        Seat.coach_id == trainee.coach_id,
        Seat.is_valid == true(),
        Seat.priority == SeatPriority.EXPERIENCE.value
    )).order_by(desc(Seat.yymmdd)).first()
    c_cache = CustomerCache(customer_id=trainee.customer_id)

    trainee_dict = {
        "id": trainee.get_hash_id(),
        "customer_id": Customer.encode_id(trainee.customer_id),  # 教练帮会员预约时需要
        "avatar": c_cache.get('avatar'),
        "name": trainee.name,
        "phone_number": trainee.phone_number
    }

    if seat:
        date, hhmm = get_day_hhmm(yymmdd=seat.yymmdd, start=seat.start, end=seat.end)
        if seat.status == SeatStatus.CONFIRM_REQUIRED:
            status = "待确认"
        elif seat.status == SeatStatus.CONFIRMED:
            status = "待上课"
        elif seat.status == SeatStatus.ATTENDED:
            status = "已上课"
        elif seat.status == SeatStatus.CONFIRM_EXPIRED:
            status = "未上课"
        else:
            status = ''
        trainee_dict.update({
            "date": date,
            "lesson_time": hhmm,
            "submitted_at": seat.reserved_at.strftime("%m月%d日 %H:%M")  # 提交时间
        })
    else:
        status = "未上课"

    trainee_dict.update({'status': status})

    return trainee_dict


def get_trainee(trainee, coach_id, today):
    # 查看最近一节课
    hh = int(datetime.now().strftime("%H")) * 60
    today = int(today.strftime("%Y%m%d"))  # 20180709
    now_int = get_yymmddhhmm(yymmdd=today, start=hh)  # 201807091530
    # 最近一节课
    # 查询今天之后有没有课
    next_seat: Seat = Seat.query.filter(and_(
        Seat.customer_id == trainee.customer_id,
        Seat.coach_id == coach_id,
        Seat.yymmdd >= today,
        Seat.status == SeatStatus.CONFIRMED.value,  # 只有教练确认了预约会员才会出现在'预约中'
        Seat.is_valid == true(),
    )).order_by(asc(Seat.yymmdd), asc(Seat.start)).first()

    # 查询今天之前有没有课
    last_seat: Seat = Seat.query.filter(and_(
        Seat.customer_id == trainee.customer_id,
        Seat.coach_id == coach_id,
        Seat.yymmdd < today,
        Seat.is_valid == true(),
    )).order_by(desc(Seat.yymmdd)).first()

    if next_seat:
        # 今天之后有课
        # 预约中
        trainee_profile = get_confirmed(trainee)
        return 'confirmed', trainee_profile
    elif last_seat:
        c_cache = CustomerCache(customer_id=trainee.customer_id)
        # 今天之前有课
        then = get_yymmddhhmm(yymmdd=last_seat.yymmdd, start=last_seat.start)  # 201807061630
        days = get_days(then=then, now=now_int)
        name = trainee.name

        trainee_profile = {
            "id": trainee.get_hash_id(),
            "customer_id": Customer.encode_id(trainee.customer_id),  # 教练帮会员预约时需要
            "avatar": c_cache.get('avatar'),
            "name": name,
            "days": days,
            "phone_number": trainee.phone_number
        }
        if days < 15:
            # 最新的一节课在今天之前15天以内
            # 15天内上课
            return 'attended', trainee_profile
        else:
            # 最新的一节课在今天之前15天以外
            # 不活跃会员
            return 'other', trainee_profile
    else:
        # 无课
        # 新会员
        trainee_profile = get_newly(trainee)
        return 'new', trainee_profile


def get_days(then, now):
    then = datetime.strptime(str(then)[:8], '%Y%m%d')
    now = datetime.strptime(str(now)[:8], '%Y%m%d')
    days = (now - then).days
    return days


def get_newly(trainee):
    avatar = "https://oss.11train.com/user/avatar/defulate_avatar.png"
    customer_id = None
    if trainee.customer_id:
        c_cache = CustomerCache(customer_id=trainee.customer_id)
        avatar = c_cache.get('avatar')
        customer_id = Customer.encode_id(trainee.customer_id)
    return {
        "id": trainee.get_hash_id(),
        "customer_id": customer_id,
        "avatar": avatar,
        "name": trainee.name,
        "phone_number": trainee.phone_number
    }


def get_confirmed(trainee):
    today_int = int(datetime.now().strftime("%Y%m%d"))
    customer_id = trainee.customer_id
    coach_id = trainee.coach_id
    customer_cache = CustomerCache(customer_id=trainee.customer_id)

    # 查询该会员在今天及今天之后的所有预约课程
    seats: List[Seat] = Seat.query.filter(and_(
        Seat.coach_id == coach_id,
        Seat.customer_id == customer_id,
        Seat.status >= SeatStatus.CONFIRM_REQUIRED.value,
        Seat.yymmdd >= today_int,
        Seat.is_valid == true(),
    )).order_by(asc(Seat.yymmdd)).all()

    if seats:
        # 时间在今天及之后
        # 显示距离现在最近的一条
        days = seats[0].yymmdd
        start = seats[0].start
        end = seats[0].end
        time = get_time(date=days, start=start, end=end)
        confirmed = {
            "id": trainee.get_hash_id(),
            "customer_id": Customer.encode_id(customer_id),  # 教练帮会员预约时需要
            "avatar": customer_cache.get('avatar'),
            "name": trainee.name,
            "time": time,
            "lessons": len(seats),
            "phone_number": trainee.phone_number
        }
    else:
        # 时间在今天之前
        confirmed = None

    return confirmed


def get_time(date, start, end):
    year = str(date)[:4]
    month = str(date)[4:6]
    day = str(date)[6:]

    then = tp.get_day_min(datetime(int(year), int(month), int(day)))
    now = tp.get_day_min(datetime.today())

    day = (then - now).days
    if day == 0:
        time = "今天"
    elif day == 1:
        time = "明天"
    elif day == 2:
        time = "后天"
    else:
        time = "%d天后" % day

    start_time, end_time = formatting_time(start, end)

    return time + ' ' + start_time + '-' + end_time


def get_date(yymmdd, start, end):
    now = datetime.now()
    year = int(yymmdd / 10000)
    month = int((yymmdd - year * 10000) / 100)
    day = yymmdd - year * 10000 - month * 100
    then = datetime(year=year, month=month, day=day)
    delta = then.date() - now.date()
    if delta.days == 0:
        time_str = '今天'
    elif delta.days == 1:
        time_str = '明天'
    elif delta.days == 2:
        time_str = '后天'
    else:
        time_str = then.strftime('%-m月%-d日')

    start_hh = int(start / 60)
    start_mm = start - start_hh * 60
    end_hh = int(end / 60)
    end_mm = end - end_hh * 60
    hhmm = '{}:{:02d}-{}:{:02d}'.format(start_hh, start_mm, end_hh, end_mm)
    return time_str, hhmm


def get_day_hhmm(yymmdd: int, start: int, end: int):
    now = datetime.now()
    year = int(yymmdd / 10000)
    month = int((yymmdd - year * 10000) / 100)
    day = yymmdd - year * 10000 - month * 100
    then = datetime(year=year, month=month, day=day)
    delta = then.date() - now.date()
    if delta.days == 0:
        time_str = '今天 '
    elif delta.days == 1:
        time_str = '明天 '
    elif delta.days == 2:
        time_str = '后天 '
    else:
        time_str = then.strftime("%m月%d日 ")

    start_hh = int(start / 60)
    start_mm = start - start_hh * 60
    end_hh = int(end / 60)
    end_mm = end - end_hh * 60
    hhmm = '{}:{:02d}-{}:{:02d}'.format(start_hh, start_mm, end_hh, end_mm)
    return time_str, hhmm
