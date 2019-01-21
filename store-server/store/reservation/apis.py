from flask import Blueprint
from flask import jsonify, request, g
from http import HTTPStatus
from sqlalchemy.sql.expression import false, true
from sqlalchemy import and_, func, asc, desc, text, null

from store.domain.middle import permission_required, roles_required
from store.domain.models import Coach, Trainee, Seat, Customer, BaseSeat, SeatStatus, SeatPriority, Contract, Course, \
    ContractContent
from store.domain.permission import ReservationPermission
from store.domain.role import CustomerRole, CoachRole
from store.domain.seat_code import generate_seat_code
from store.registration.utils import get_seat_course_name
from store.reservation.utils import minus_lesson, StatusMachine, queue_and_send_cancel_message, \
    queue_and_send_confirmed_message, plus_lesson
from store.domain.cache import CoachCache, StoreBizCache, TraineeCache, CustomerCache
from store.database import db
from datetime import datetime, timedelta
from typing import List
from store.utils.time_formatter import get_date_hhmm, get_yymmdd, get_yymmddhhmm, get_hhmm
from store.utils.sms import verify_sms_code
from store.coaches.utils import refresh_month_record
from store.utils import time_processing as tp

blueprint = Blueprint('_reservation', __name__)


class SeatWrap(BaseSeat):
    def __init__(self, yymmdd: int, start: int, end: int, priority: int = None):
        if end - start <= Seat.min_interval:
            raise ValueError('end must larger than start + min_interval')
        self.yymmdd = yymmdd
        self.start = start
        self.end = end
        self.priority = priority

    def __str__(self):
        return str(self.time_id)


def get_time_id(yymmdd, start):
    hour = int(start / 60)
    minute = start - hour * 60
    return yymmdd * 10000 + hour * 100 + minute


def get_priority(coach_id, customer_id):
    trainee: Trainee = Trainee.query.filter(and_(
        Trainee.coach_id == coach_id,
        Trainee.customer_id == customer_id
    )).first()
    if trainee:
        if trainee.is_bind:
            priority = SeatPriority.PRIVATE.value
        else:
            priority = SeatPriority.EXPERIENCE.value
    else:
        priority = SeatPriority.EXPERIENCE.value
    return priority, trainee


class SeatOneDay:
    def __init__(self, coach_id: int, yymmdd: int):
        self.coach_id = coach_id
        self.yymmdd = yymmdd

    def get_all_seats(self) -> List[Seat]:
        seats: List[Seat] = Seat.query.filter(and_(
            Seat.is_valid == true(),
            Seat.coach_id == self.coach_id,
            Seat.yymmdd == self.yymmdd)).order_by(asc(Seat.start)).all()
        return seats

    def get_exp_confirm_required_count(self):
        all_seats = self.get_all_seats()
        count = 0
        for s in all_seats:
            if s.status == SeatStatus.CONFIRM_REQUIRED and s.priority == SeatPriority.EXPERIENCE:
                count += 1
        return count

    def get_conflict_seats(self, seat: Seat) -> List[Seat]:
        all_seats = self.get_all_seats()
        conflict = list()
        for s in all_seats:
            if s.id == seat.id:
                continue
            if s.slices & seat.slices:
                conflict.append(s)
        return conflict

    def get_conflict_msg(self, seat: Seat):
        conflict_seats = self.get_conflict_seats(seat)
        if not conflict_seats:
            return None
        msg_list = list()
        for s in conflict_seats:
            name = ''
            if s.customer_id:
                t_cache = TraineeCache(coach_id=s.coach_id, customer_id=s.customer_id)
                name = t_cache.get('name')
            start_str, end_str = get_hhmm(s.start, s.end)
            msg_list.append('{name}({start}-{end})'.format(name=name, start=start_str, end=end_str))
        return msg_list

    def display_seat(self, seat: Seat):
        start_str, end_str = get_hhmm(seat.start, seat.end)
        seat_dict = {
            'id': seat.get_hash_id(),
            'yymmdd': seat.yymmdd,
            'start': start_str,
            'end': end_str,
            'status': SeatStatus(seat.status).name.lower(),
            'is_exp': bool(seat.priority == SeatPriority.EXPERIENCE),
            'note': seat.note or ""
        }
        if seat.customer_id:
            t_cache = TraineeCache(coach_id=seat.coach_id, customer_id=seat.customer_id)
            name = t_cache.get('name')
            c_cache = CustomerCache(customer_id=seat.customer_id)
            avatar = c_cache.get('avatar')
            seat_dict.update({
                'trainee': {
                    'id': Trainee.encode_id(t_cache.get('trainee_id')),
                    'name': name,
                    'avatar': avatar
                }
            })
        conflict_msg = self.get_conflict_msg(seat)
        if conflict_msg:
            seat_dict.update({
                'conflict_msg': conflict_msg
            })
        return seat_dict

    def add_break_seat(self, the_seat: SeatWrap):
        now = datetime.now()
        all_seats = self.get_all_seats()
        previous_seat, next_seat = None, None  # 上一个, 下一个
        for s in all_seats:
            if the_seat.start == s.end and s.status == SeatStatus.BREAK:
                previous_seat = s
            elif the_seat.end == s.start and s.status == SeatStatus.BREAK:
                next_seat = s
            elif the_seat.slices & s.slices:
                # 目前的提交逻辑不会出现重叠
                return False, '已被占用'

        try:
            start = the_seat.start
            end = the_seat.end
            note = the_seat.note

            # 如果首尾相连, 那么把它们并到一起
            if previous_seat:
                start = previous_seat.start
                db.session.delete(previous_seat)
            if next_seat:
                end = next_seat.end
                db.session.delete(next_seat)

            new_seat = Seat(
                coach_id=self.coach_id,
                yymmdd=self.yymmdd,
                start=start,
                end=end,
                status=SeatStatus.BREAK.value,
                created_at=now,
                note=note
            )
            db.session.add(new_seat)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e
        return True, None

    def remove_break_seat(self, the_seat: SeatWrap):
        all_seats = self.get_all_seats()
        now = datetime.now()

        for s in all_seats:
            if s.status == SeatStatus.BREAK:
                if s.start <= the_seat.start and the_seat.end <= s.end:  # 被包含在内
                    parent_seat = s
                    break
        else:
            return False, '没有相应的休息时间可以取消'

        try:

            if parent_seat.start == the_seat.start and parent_seat.end == the_seat.end:
                # 整个删掉
                db.session.delete(parent_seat)
            elif parent_seat.start == the_seat.start:
                # 截掉开始的一段
                parent_seat.start = the_seat.end
                parent_seat.modified_at = now
            elif parent_seat.end == the_seat.end:
                # 截掉结尾的一段
                parent_seat.end = the_seat.start
                parent_seat.modified_at = now
            else:
                # 截掉中间的一段
                end = parent_seat.end
                parent_seat.end = the_seat.start
                parent_seat.modified_at = now
                new_seat = Seat(
                    coach_id=self.coach_id,
                    yymmdd=self.yymmdd,
                    start=the_seat.end,
                    end=end,
                    status=SeatStatus.BREAK.value,
                    created_at=now
                )
                db.session.add(new_seat)

            db.session.commit()
            return True, None
        except Exception as e:
            db.session.rollback()
            raise e

    def add_reserve_seat(self, the_seat: SeatWrap, customer_id, status):
        all_seats = self.get_all_seats()
        now = datetime.now()
        for s in all_seats:
            if the_seat.slices & s.slices:  # 有重合
                if s.status == SeatStatus.CONFIRM_REQUIRED and s.priority < the_seat.priority:
                    # 有重合, 但是未确认而且优先级较低, 可以覆盖
                    continue
                else:  # 有重合, 但是位置不允许覆盖
                    return False, '该时间段已被占用', None

        new_seat = Seat(
            coach_id=self.coach_id,
            yymmdd=self.yymmdd,
            start=the_seat.start,
            end=the_seat.end,
            customer_id=customer_id,
            status=status,
            priority=the_seat.priority,
            reserved_at=now,
            created_at=now
        )
        db.session.add(new_seat)
        db.session.commit()

        db.session.refresh(new_seat)
        return True, None, new_seat

    def confirm(self, seat):
        """ 把有冲突的seat都取消掉 """
        conflict_seats = self.get_conflict_seats(seat)
        try:
            for c_s in conflict_seats:
                StatusMachine(c_s).cancel()
            if seat.status == SeatStatus.CONFIRM_REQUIRED:
                # 待确认 -> 确认
                StatusMachine(seat).transform(SeatStatus.CONFIRMED)
            elif seat.status == SeatStatus.CONFIRM_EXPIRED:
                # 已过期 -> 已上课
                StatusMachine(seat).transform(SeatStatus.ATTENDED)
            elif seat.status == SeatStatus.CONFIRMED:
                # 已经是确认
                pass
            else:
                db.session.rollback()
                return False, '状态不对, 请重新刷新'
            return True, None
        except Exception as e:
            db.session.rollback()
            raise e

    @staticmethod
    def cancel(seat):
        """ 现在什么状态都可以取消 """
        now = datetime.now()
        seat.is_valid = False
        seat.canceled_at = now
        seat.modified_at = now
        db.session.commit()
        return True, None


def generate_seats(yymmdd, start, end, duration, priority):
    for s in range(start, end, duration):
        yield SeatWrap(yymmdd=yymmdd, start=s, end=s + duration, priority=priority)


def get_seats_role_coach(coach_id, yymmdd, start, end):
    """ 获取席位, 教练视角 """
    res = list()
    one_day = SeatOneDay(coach_id=coach_id, yymmdd=yymmdd)
    seats = one_day.get_all_seats()

    pos = start
    if not seats:
        start_str, end_str = get_hhmm(pos, end)
        res.append({
            'id': get_time_id(yymmdd, pos),
            'yymmdd': yymmdd,
            'start': start_str,
            'end': end_str,
            'status': SeatStatus.AVAILABLE.name.lower(),
        })
        return res

    count = len(seats)
    for i in range(0, count):
        if seats[i].start > pos:
            # 开头加available
            start_str, end_str = get_hhmm(pos, seats[i].start)
            res.append({
                'id': get_time_id(yymmdd, pos),
                'yymmdd': yymmdd,
                'start': start_str,
                'end': end_str,
                'status': SeatStatus.AVAILABLE.name.lower(),
            })

        res.append(one_day.display_seat(seats[i]))
        pos = seats[i].end

        if i == count - 1 and pos < end:
            # last one, 并且结尾有空隙
            start_str, end_str = get_hhmm(pos, end)
            res.append({
                'id': get_time_id(yymmdd, pos),
                'yymmdd': yymmdd,
                'start': start_str,
                'end': end_str,
                'status': SeatStatus.AVAILABLE.name.lower(),
            })
    return res


def get_now_index(res, yymmdd):
    now = datetime.now()
    today = datetime.today()
    today_yymmdd = get_yymmdd(today)
    if today_yymmdd != yymmdd:
        return -1

    hhmm = now.hour * 60 + now.minute
    for i, re in enumerate(res):
        start = datetime.strptime(re['start'], "%H:%M").hour * 60
        end = datetime.strptime(re['end'], "%H:%M").hour * 60
        if start <= hhmm <= end:
            now_index = i
            return now_index
    return -1


def get_seats(coach_id, yymmdd, start, end, duration, customer_id, priority):
    """ 获取席位, 用户视角 """
    now = datetime.now()
    res = list()
    new_seats: List[SeatWrap] = generate_seats(
        yymmdd=yymmdd, start=start, end=end, duration=duration, priority=priority)

    one_day = SeatOneDay(coach_id=coach_id, yymmdd=yymmdd)
    seats = one_day.get_all_seats()

    # default_status 对于空闲座位的默认处理, 对于体验预约, 如果超过限额, 那么是不可预约, 否则是可以预约的
    if priority == SeatPriority.PRIVATE:
        default_status = SeatStatus.AVAILABLE.name.lower()
    else:
        # 体验用户只要有一节待确认或者已确认但是未上课，所有教练的体验课都不能预约
        exp_seat: Seat = Seat.query.filter(and_(
            Seat.is_valid == true(),
            Seat.customer_id == customer_id,
            Seat.status >= SeatStatus.CONFIRM_REQUIRED.value,
            Seat.status <= SeatStatus.CONFIRMED.value,
        )).first()
        if exp_seat:
            default_status = SeatStatus.BREAK.name.lower()
        else:
            exp_confirm_required_count = one_day.get_exp_confirm_required_count()
            if exp_confirm_required_count >= 2:
                default_status = SeatStatus.BREAK.name.lower()
                # TODO 学员在选择的过程中教练的开关关闭的情况
            else:
                default_status = SeatStatus.AVAILABLE.name.lower()

    for ns in new_seats:
        seat_dict = {
            'id': ns.time_id,
            'duration': duration,
            'is_past': bool(ns.start_time < now)
        }

        for s in seats:
            if ns.slices & s.slices:
                if customer_id == s.customer_id:
                    # 教练预约的学员正是自己的, 那么正常显示状态
                    seat_dict.update({
                        'status': SeatStatus(s.status).name.lower(),
                        'start': get_yymmddhhmm(s.yymmdd, s.start),
                    })
                    res.append(seat_dict)
                    break
                elif s.status == SeatStatus.CONFIRM_REQUIRED and s.priority < ns.priority:
                    # TODO 提交之后还是待确认因此会出现一绿一蓝的情况
                    # 如果是待确认, 而且自己的优先级比较高, 那么还是空闲的
                    seat_dict.update({
                        'status': default_status
                    })
                    res.append(seat_dict)
                    break
                else:
                    # 其他被占用的情况, 或者教练预约的学员不是自己的, 那么状态显示为休息(就是不可预约)
                    seat_dict.update({
                        'status': SeatStatus.BREAK.name.lower()
                    })
                    res.append(seat_dict)
                    break
        else:
            # Didn't find anything.. 空闲的
            seat_dict.update({
                'status': default_status
            })
            res.append(seat_dict)
    return res


def get_coach_seats_summary(coach_id: int, yymmdd: int):
    confirmed_count = db.session.query(func.count(Seat.id)).filter(and_(
        Seat.is_valid == true(),
        Seat.coach_id == coach_id,
        Seat.status == SeatStatus.CONFIRMED.value,
        Seat.yymmdd == yymmdd
    )).scalar()
    attended_count = db.session.query(func.count(Seat.id)).filter(and_(
        Seat.is_valid == true(),
        Seat.coach_id == coach_id,
        Seat.status == SeatStatus.ATTENDED.value,
        Seat.yymmdd == yymmdd
    )).scalar()
    confirm_required_count = db.session.query(func.count(Seat.id)).filter(and_(
        Seat.is_valid == true(),
        Seat.coach_id == coach_id,
        Seat.status == SeatStatus.CONFIRM_REQUIRED.value,
        Seat.yymmdd == yymmdd
    )).scalar()
    lesson_count = confirmed_count + attended_count
    return lesson_count, confirm_required_count


def get_customer_seats_summary(customer_id: int, coach_id: int, yymmdd: int):
    confirmed_count = db.session.query(func.count(Seat.id)).filter(and_(
        Seat.is_valid == true(),
        Seat.customer_id == customer_id,
        Seat.coach_id == coach_id,
        Seat.status == SeatStatus.CONFIRMED.value,
        Seat.yymmdd == yymmdd
    )).scalar()
    attended_count = db.session.query(func.count(Seat.id)).filter(and_(
        Seat.is_valid == true(),
        Seat.customer_id == customer_id,
        Seat.coach_id == coach_id,
        Seat.status == SeatStatus.ATTENDED.value,
        Seat.yymmdd == yymmdd
    )).scalar()
    lesson_count = confirmed_count + attended_count
    return lesson_count


@blueprint.route('/coaches/<string:c_id>', methods=['GET'])
@permission_required(ReservationPermission())
@roles_required(CustomerRole())
def get_coach(c_id):
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    now = datetime.now()
    # 当携带了教练id时,说明是体验会员预约,只返回该教练的days和brief不返回教练列表
    coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    coach_cache = CoachCache(coach.id)
    days = list()
    week_end = tp.get_next_sunday(datetime.today())  # 本周末
    for i in range(0, 7):
        date = now + timedelta(days=i)
        yymmdd = get_yymmdd(date)
        lesson_count = get_customer_seats_summary(
            coach_id=coach.id, customer_id=customer_id, yymmdd=yymmdd)
        if i == 0:
            date_str = '今天'
        elif 7 >= i >= 1:
            week = tp.get_week(date)
            date_str = "周%s" % tp.transform_week_chstr(week)
            if tp.get_day_min(date) > week_end:
                date_str = "下周%s" % tp.transform_week_chstr(week)
        else:
            date_str = date.strftime('%-m月%-d')
        date_num = date.strftime('%-m.%-d')
        days.append({
            'date_num': date_num,
            'date': date_str,
            'yymmdd': yymmdd,
            'lesson_count': lesson_count,
        })
    return jsonify({
        'coach': {
            'brief': coach_cache.get('brief'),
            'days': days
        }
    })


@blueprint.route('/coaches', methods=['GET'])
@permission_required(ReservationPermission())
@roles_required(CustomerRole())
def get_coaches():
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    trainees: List[Trainee] = Trainee.query.filter(
        Trainee.customer_id == customer_id,
        Trainee.is_bind == true(),  # 私教预约时只返回已经绑定的教练
    ).all()

    now = datetime.now()
    coaches = []
    week_end = tp.get_next_sunday(datetime.today())  # 本周末
    for t in trainees:
        coach_cache = CoachCache(t.coach_id)

        days = list()
        for i in range(0, 7):
            date = now + timedelta(days=i)
            yymmdd = get_yymmdd(date)
            lesson_count = get_customer_seats_summary(
                coach_id=t.coach_id, customer_id=customer_id, yymmdd=yymmdd)
            if i == 0:
                date_str = '今天'
            elif 7 >= i >= 1:
                week = tp.get_week(date)
                date_str = "周%s" % tp.transform_week_chstr(week)
                if tp.get_day_min(date) > week_end:
                    date_str = "下周%s" % tp.transform_week_chstr(week)
            else:
                date_str = date.strftime('%-m月%-d')
            date_num = date.strftime('%-m.%-d')
            days.append({
                'date_num': date_num,
                'date': date_str,
                'yymmdd': yymmdd,
                'lesson_count': lesson_count,
            })
        coaches.append({
            'coach': coach_cache.get('brief'),
            'days': days
        })
    return jsonify({
        'coaches': coaches
    })


@blueprint.route('/coaches/<string:c_id>/days/<string:d_id>', methods=['GET'])
@permission_required(ReservationPermission())
@roles_required(CustomerRole())
def get_days(c_id, d_id):
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    coach: Coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    if coach.biz_id != biz_id:
        return jsonify(), HTTPStatus.FORBIDDEN
    yymmdd = int(d_id)

    duration = 30
    store_cache = StoreBizCache(biz_id)
    start, end = store_cache.get('business_hours_begin', 'business_hours_end')

    priority, _ = get_priority(coach.id, customer_id)

    res = get_seats(coach_id=coach.id, yymmdd=yymmdd, start=start, end=end, duration=duration,
                    customer_id=customer_id, priority=priority)
    return jsonify({
        'seats': res
    })


def parse_seat_id(s_id: str):
    day_str = s_id[:8]
    yymmdd = int(day_str)
    hh = int(s_id[-4:-2])
    mm = int(s_id[-2:])
    start = hh * 60 + mm
    return yymmdd, start


@blueprint.route('/coaches/<string:c_id>/seats/<string:s_id>/reserve', methods=['POST'])
@permission_required(ReservationPermission())
@roles_required(CustomerRole())
def post_reserve(c_id, s_id):
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST
    duration = json_data.get('duration')
    if not duration:
        return jsonify(msg='missing duration'), HTTPStatus.BAD_REQUEST
    duration = int(duration)

    biz_id = g.get('biz_id')
    coach: Coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    if coach.biz_id != biz_id:
        return jsonify(), HTTPStatus.FORBIDDEN

    yymmdd, start = parse_seat_id(s_id)

    now = datetime.now()

    priority, trainee = get_priority(coach.id, customer_id)

    if priority == SeatPriority.EXPERIENCE:
        name = json_data.get('name')
        if not name:
            return jsonify(msg='请输入您的称呼'), HTTPStatus.BAD_REQUEST
        phone_number = json_data.get('phone_number')
        if not phone_number:
            return jsonify(msg='请输入您的手机号码'), HTTPStatus.BAD_REQUEST
        sms_code = json_data.get('sms_code')
        if not sms_code:
            return jsonify(msg='请输入您收到的验证码'), HTTPStatus.BAD_REQUEST
        verified, msg = verify_sms_code(phone_number=phone_number, sms_code=sms_code)
        if not verified:
            return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

        if not trainee:
            trainee = Trainee(
                coach_id=coach.id,
                customer_id=customer_id,
                created_at=now,
                is_exp=True
            )
            db.session.add(trainee)

        trainee.name = name
        trainee.is_exp = True
        trainee.phone_number = phone_number
        db.session.commit()
        t_cache = TraineeCache(coach_id=coach.id, customer_id=customer_id)
        t_cache.reload()

    the_seat = SeatWrap(yymmdd=yymmdd, start=start, end=start + duration, priority=priority)
    if the_seat.start_time < now:
        return jsonify(msg='开始时间已经过了, 请选择其他时间'), HTTPStatus.BAD_REQUEST

    one_day = SeatOneDay(coach_id=coach.id, yymmdd=yymmdd)
    is_ok, msg, new_seat = one_day.add_reserve_seat(
        the_seat, customer_id=customer_id, status=SeatStatus.CONFIRM_REQUIRED.value)
    if not is_ok:
        return jsonify({'msg': msg}), HTTPStatus.BAD_REQUEST

    # 拉取合同获取课程id
    contract_ids = Contract.get_customer_valid_contract_ids(customer_id)
    contract_content: List[ContractContent] = ContractContent.query.filter(
        ContractContent.contract_id.in_(contract_ids),
        ContractContent.is_valid == true(),
        ContractContent.total > ContractContent.attended
    ).all()
    # if not contract_content:
    #     return jsonify(msg='您尚未购买私教课'), HTTPStatus.BAD_REQUEST
    if len(contract_content) == 1:
        content = contract_content[0]
        # 只购买了一种课程
        new_seat.course_id = content.course_id
        new_seat.is_group = content.is_group

    queue_and_send_confirmed_message(new_seat)

    return jsonify({'msg': '提交成功'})


@blueprint.route('/coach/days/<string:d_id>', methods=['GET'])
@roles_required(CoachRole())
def get_coach_day(d_id: str):
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    try:
        yymmdd = int(d_id)
    except ValueError:
        return jsonify(msg='日期错误,请重试'), HTTPStatus.BAD_REQUEST

    store_cache = StoreBizCache(biz_id)
    start, end = store_cache.get('business_hours_begin', 'business_hours_end')

    res = get_seats_role_coach(coach_id=coach_id, yymmdd=yymmdd, start=start, end=end)
    now_index = get_now_index(res, yymmdd)
    return jsonify({
        "seats": res,
        "now_index": now_index
    })


@blueprint.route('/coach', methods=['GET'])
@roles_required(CoachRole())
def get_coach_profile():
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    now = datetime.now()

    page = request.args.get('page', 1, type=int)
    days = list()
    confirm_required_sum = 0
    days_range = range(-7 * page, 7)
    week_end = tp.get_next_sunday(datetime.today())  # 本周末
    for i in days_range:
        date = now + timedelta(days=i)
        yymmdd = get_yymmdd(date)
        lesson_count, confirm_required_count = get_coach_seats_summary(coach_id=coach_id, yymmdd=yymmdd)
        if i == 0:
            date_str = '今天'
        elif 7 >= i >= 1:
            week = tp.get_week(date)
            date_str = "周%s" % tp.transform_week_chstr(week)
            if tp.get_day_min(date) > week_end:
                date_str = "下周%s" % tp.transform_week_chstr(week)
        else:
            date_str = date.strftime('%-m月%-d')
        days.append({
            'date': date_str,
            'yymmdd': yymmdd,
            'lesson_count': lesson_count,
            'confirm_required_count': confirm_required_count
        })
        confirm_required_sum += confirm_required_count
    return jsonify({
        'days': days[::-1],
        'today_index': 6,  # 因为列表已经被反转了,所以"今天"的index始终为6
        'confirm_required_sum': confirm_required_sum,
    })


@blueprint.route('/coach/seats/<string:h_id>/confirm', methods=['POST'])
@roles_required(CoachRole())
def post_reserve_confirm(h_id: str):
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)

    seat: Seat = Seat.find(h_id)
    if not seat:
        return jsonify({'msg': '没有预约可以确认'}), HTTPStatus.NOT_FOUND
    if seat.coach_id != coach_id:
        return jsonify(), HTTPStatus.FORBIDDEN

    one_day = SeatOneDay(coach_id=coach_id, yymmdd=seat.yymmdd)
    is_ok, msg = one_day.confirm(seat)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    return jsonify({'msg': '成功确认.'})


@blueprint.route('/coach/seats/<string:h_id>', methods=['DELETE'])
@roles_required(CoachRole())
def delete_seat(h_id: str):
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)

    seat: Seat = Seat.find(h_id)
    if not seat:
        return jsonify({'msg': '不存在该预约'}), HTTPStatus.NOT_FOUND

    if seat.coach_id != coach_id:
        return jsonify(), HTTPStatus.FORBIDDEN

    # 会员发起, 通知会员预约取消
    if seat.status == SeatStatus.CONFIRM_REQUIRED.value:
        # 待确认说明是会员发起的预约
        # 发送预约取消通知
        queue_and_send_cancel_message(seat)
    # 如果是自己发起的, 不用发起通知

    if seat.is_check:
        return jsonify(msg='该课程已经核销,不能取消'), HTTPStatus.BAD_REQUEST
    is_ok, msg = SeatOneDay.cancel(seat)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST
    if seat.status == SeatStatus.ATTENDED.value:
        # 如果是取消已经上过的课则增加一节课时
        plus_lesson(seat)
        # 刷新月报
        refresh_month_record(seat)
    return jsonify({'msg': '成功删除'})


@blueprint.route('/coach/seat/<string:s_id>', methods=['PUT'])
@roles_required(CoachRole())
def put_seat_type(s_id):
    """ 教练设置课程类型(设置完成后用户才能在前台销课) """
    seat: Seat = Seat.find(s_id)
    if not seat:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    course_hid = json_data.get('course_id')
    is_group = json_data.get('is_group')
    if not course_hid:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND
    course: Course = Course.find(course_hid)
    if not course:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND

    seat.course_id = course.id
    seat.is_group = is_group
    db.session.commit()
    return jsonify(msg='设置成功')


@blueprint.route('/coach/break', methods=['POST'])
@roles_required(CoachRole())
def post_break():
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST
    yymmdd = json_data.get('yymmdd')
    if not yymmdd:
        return jsonify(msg='missing yymmdd'), HTTPStatus.BAD_REQUEST
    start_str = json_data.get('start')
    if not start_str:
        return jsonify(msg='missing start'), HTTPStatus.BAD_REQUEST
    end_str = json_data.get('end')
    if not end_str:
        return jsonify(msg='missing end'), HTTPStatus.BAD_REQUEST
    start_hh = int(start_str.split(':')[0])
    start_mm = int(start_str.split(':')[1])
    start = start_hh * 60 + start_mm
    end_hh = int(end_str.split(':')[0])
    end_mm = int(end_str.split(':')[1])
    end = end_hh * 60 + end_mm

    if end - start <= Seat.min_interval:
        return jsonify(msg='结束时间必须大于开始时间'), HTTPStatus.BAD_REQUEST

    note = json_data.get('note')

    the_seat = SeatWrap(yymmdd=yymmdd, start=start, end=end)
    the_seat.note = note
    one_day = SeatOneDay(coach_id=coach_id, yymmdd=yymmdd)
    is_ok, msg = one_day.add_break_seat(the_seat)
    if is_ok:
        return jsonify({'msg': '成功设置'})
    else:
        return jsonify({'msg': msg}), HTTPStatus.BAD_REQUEST


@blueprint.route('/coach/break', methods=['DELETE'])
@roles_required(CoachRole())
def delete_break():
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST
    yymmdd = json_data.get('yymmdd')
    if not yymmdd:
        return jsonify(msg='missing yymmdd'), HTTPStatus.BAD_REQUEST
    start_str = json_data.get('start')
    if not start_str:
        return jsonify(msg='missing start'), HTTPStatus.BAD_REQUEST
    end_str = json_data.get('end')
    if not end_str:
        return jsonify(msg='missing end'), HTTPStatus.BAD_REQUEST
    start_hh = int(start_str.split(':')[0])
    start_mm = int(start_str.split(':')[1])
    start = start_hh * 60 + start_mm
    end_hh = int(end_str.split(':')[0])
    end_mm = int(end_str.split(':')[1])
    end = end_hh * 60 + end_mm
    if end - start <= Seat.min_interval:
        return jsonify(msg='结束时间必须大于开始时间'), HTTPStatus.BAD_REQUEST

    the_seat = SeatWrap(yymmdd=yymmdd, start=start, end=end)
    one_day = SeatOneDay(coach_id=coach_id, yymmdd=yymmdd)
    is_ok, msg = one_day.remove_break_seat(the_seat)

    if is_ok:
        return jsonify({'msg': '成功设置'})
    else:
        return jsonify({'msg': msg}), HTTPStatus.BAD_REQUEST


@blueprint.route('/coach/reserve', methods=['POST'])
@roles_required(CoachRole())
def post_coach_reserve():
    """ 跟学员发起的预约不一样的地方是, status初始为confirm """
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST
    customer_hid = json_data.get('customer_id')
    customer: Customer = Customer.find(customer_hid)
    if not customer:
        return jsonify(msg='该会员不存在'), HTTPStatus.NOT_FOUND
    if customer.biz_id != g.biz_id:
        return jsonify(), HTTPStatus.FORBIDDEN

    yymmdd = int(json_data.get('yymmdd'))
    if not yymmdd:
        return jsonify(msg='missing yymmdd'), HTTPStatus.BAD_REQUEST
    start_str = json_data.get('start')
    if not start_str:
        return jsonify(msg='missing start'), HTTPStatus.BAD_REQUEST
    end_str = json_data.get('end')
    if not end_str:
        return jsonify(msg='missing end'), HTTPStatus.BAD_REQUEST
    # TODO 暂时关闭合同校验, 解除教练端帮会员约课的限制
    # TODO 该限制解除后允许教练端约课,但是在合同录入完毕之前会员无法销课
    # course_hid = json_data.get('course_id')
    # if not course_hid:
    #     return jsonify(msg='请选择课程类别'), HTTPStatus.BAD_REQUEST
    # is_group = json_data.get('is_group')
    # if is_group is None:
    #     return jsonify(msg='请选择课程类别'), HTTPStatus.BAD_REQUEST

    start_hh = int(start_str.split(':')[0])
    start_mm = int(start_str.split(':')[1])
    start = start_hh * 60 + start_mm
    end_hh = int(end_str.split(':')[0])
    end_mm = int(end_str.split(':')[1])
    end = end_hh * 60 + end_mm
    if end - start <= Seat.min_interval:
        return jsonify(msg='结束时间必须大于开始时间'), HTTPStatus.BAD_REQUEST

    priority, trainee = get_priority(coach_id, customer.id)

    now = datetime.now()
    the_seat = SeatWrap(yymmdd=yymmdd, start=start, end=end, priority=priority)

    if the_seat.end_time < now:
        # 时间已过, 状态直接设为已上课
        status = SeatStatus.ATTENDED.value
    else:
        # 直接设为已确认
        status = SeatStatus.CONFIRMED.value

    one_day = SeatOneDay(coach_id=coach_id, yymmdd=yymmdd)
    is_ok, msg, new_seat = one_day.add_reserve_seat(the_seat, customer_id=customer.id, status=status)
    if not is_ok:
        return jsonify({'msg': msg}), HTTPStatus.BAD_REQUEST
    else:
        # course: Course = Course.find(course_hid)
        # if course:
        #     new_seat.course_id = course.id
        #     db.session.commit()
        # if is_group is not None:
        #     new_seat.is_group = is_group
        #     db.session.commit()
        if status == SeatStatus.ATTENDED.value:
            # 如果状态为已上课则扣除一节课时
            minus_lesson(new_seat, now)
            # 刷新月报
            refresh_month_record(new_seat)
        return jsonify({'msg': '预约成功'})


@blueprint.route('/customer/brief', methods=['GET'])
@roles_required(CustomerRole())
def get_customer_brief():
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)

    trainees: List[Trainee] = Trainee.query.filter(
        Trainee.customer_id == customer_id,
        Trainee.is_bind == true()
    ).all()
    coaches_count = len(trainees)

    r: Seat = Seat.query.filter(and_(
        Seat.is_valid == true(),
        Seat.customer_id == customer_id,
        Seat.status >= SeatStatus.CONFIRM_REQUIRED.value,
        Seat.status <= SeatStatus.CONFIRMED.value,
    )).order_by(asc(Seat.yymmdd), asc(Seat.start)).first()

    # 没有绑定过教练也没有约过课
    if coaches_count == 0 and not r:
        return jsonify({
            'coaches_count': coaches_count,
            'reserved': []
        })

    # 没有绑定过教练,但是约了体验课 or 绑定过教练，约了私教课
    elif r:
        date, hhmm = get_date_hhmm(yymmdd=r.yymmdd, start=r.start, end=r.end)
        # 如果有预约, 还没上课
        return jsonify({
            'coaches_count': coaches_count,
            'reserved': [{
                'date': date,
                'hhmm': hhmm,
                'status': SeatStatus(r.status).name.lower()
            }]
        })

    attended: Seat = Seat.query.filter(and_(
        Seat.is_valid == true(),
        Seat.customer_id == customer_id,
        Seat.status == SeatStatus.ATTENDED.value,
    )).order_by(desc(Seat.yymmdd)).first()

    if attended:
        now = datetime.now()
        yymmdd = attended.yymmdd
        year = int(yymmdd / 10000)
        month = int((yymmdd - year * 10000) / 100)
        day = yymmdd - year * 10000 - month * 100
        then = datetime(year=year, month=month, day=day)
        delta = now - then
        # 如果没有预约,返回上次上课距离天数
        return jsonify({
            'coaches_count': coaches_count,
            'reserved': [],
            'rest_days': delta.days
        })

    # 从来没有预约过
    return jsonify({
        'coaches_count': coaches_count,
        'reserved': [],
        'rest_days': -1
    })


@blueprint.route('/customer', methods=['GET'])
@roles_required(CustomerRole())
def get_customer():
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)

    now = datetime.now()
    trainee: Trainee = Trainee.query.filter(
        Trainee.customer_id == customer_id,
    ).first()
    reserved_list: List[Seat] = Seat.query.filter(and_(
        Seat.is_valid == true(),
        Seat.customer_id == customer_id,
        Seat.status >= SeatStatus.CONFIRM_REQUIRED.value,
        Seat.status <= SeatStatus.CONFIRMED.value,
    )).order_by(asc(Seat.yymmdd), asc(Seat.start)).all()

    r_list = list()
    for r in reserved_list:
        coach_cache = CoachCache(r.coach_id)
        date, hhmm = get_date_hhmm(yymmdd=r.yymmdd, start=r.start, end=r.end)
        r_list.append({
            'coach': coach_cache.get('brief'),
            'date': date,
            'hhmm': hhmm,
            'status': '待上课' if r.status == SeatStatus.CONFIRMED else '待教练确认'
        })

    attended_list: List[Seat] = Seat.query.filter(and_(
        Seat.is_valid == true(),
        Seat.customer_id == customer_id,
        Seat.status == SeatStatus.ATTENDED.value
    )).order_by(desc(Seat.yymmdd), desc(Seat.start)).all()

    a_list = list()
    for a in attended_list:
        if a.is_check or a.priority == SeatPriority.EXPERIENCE.value:
            check_status = "已核销"
        else:
            check_status = "未核销"
        # 只有已经上过的课才需要核销
        coach_cache = CoachCache(a.coach_id)
        date, hhmm = get_date_hhmm(yymmdd=a.yymmdd, start=a.start, end=a.end)
        a_list.append({
            'id': a.get_hash_id(),  # 用于销课
            'coach': coach_cache.get('brief'),
            'date': date,
            'hhmm': hhmm,
            'status': '已上课',
            'check_status': check_status,
            'course_name': get_seat_course_name(a)
        })

    res = {
        'reserved': r_list,
        'attended': a_list,
        'is_exp': trainee.is_exp if trainee else True  # 如果该用户不是学员则默认为体验用户
    }
    if not reserved_list and attended_list:
        attended = attended_list[0]
        yymmdd = attended.yymmdd
        year = int(yymmdd / 10000)
        month = int((yymmdd - year * 10000) / 100)
        day = yymmdd - year * 10000 - month * 100
        then = datetime(year=year, month=month, day=day)
        delta = now - then
        res.update({
            'rest_days': delta.days,
            'is_exp': trainee.is_exp if trainee else True  # 如果该用户不是学员则默认为体验用户
        })
    return jsonify(res)


@blueprint.route('/customer/check', methods=['GET'])
@roles_required(CustomerRole())
def customer_check():
    # 客户确认上课, 获取课程码
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)

    seat_id = request.args.get('id')
    seat: Seat = Seat.find(seat_id)
    if not seat:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND
    if seat.customer_id != c_id:
        return jsonify(msg='非法操作'), HTTPStatus.BAD_REQUEST
    if seat.is_check:
        return jsonify(msg='该课程已被核销'), HTTPStatus.BAD_REQUEST
    if seat.priority != SeatPriority.PRIVATE.value:
        return jsonify(msg='非私教课无需核销'), HTTPStatus.BAD_REQUEST
    course_id = seat.course_id
    if not course_id:
        return jsonify(msg='请联系教练设置课时类型'), HTTPStatus.BAD_REQUEST

    code = generate_seat_code(seat)
    return jsonify({
        "code": code
    })
