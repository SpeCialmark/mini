from datetime import datetime

from sqlalchemy import and_

from store.database import db

from store.domain.models import Trainee, LessonRecord, LessonRecordStatus, SeatStatus, WxOpenUser
from store.domain.wx_push import queue_customer_reservation_message, queue_customer_cancel_message, \
    queue_coach_confirmed_message
from store.user.apis import send_messages


def plus_lesson(seat):
    """ 增加课时"""
    try:
        now = datetime.now()
        customer_id = seat.customer_id
        coach_id = seat.coach_id
        trainee: Trainee = Trainee.query.filter(and_(
            Trainee.customer_id == customer_id,
            Trainee.coach_id == coach_id,
        )).first()
        lesson_record = LessonRecord(
            created_at=now,
            executed_at=now,
            customer_id=customer_id,
            coach_id=coach_id,
            status=LessonRecordStatus.CANCEL.value,
            charge=1,
            seat_id=seat.id
        )

        trainee.attended_lessons -= 1  # 将已上课时减一
        db.session.add(lesson_record)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e
    return


def minus_lesson(seat, now):
    """ 扣除课时 """
    try:
        customer_id = seat.customer_id
        coach_id = seat.coach_id
        trainee: Trainee = Trainee.query.filter(and_(
            Trainee.customer_id == customer_id,
            Trainee.coach_id == coach_id,
        )).first()
        # 记录
        lesson_record = LessonRecord(
            created_at=now,
            executed_at=now,
            customer_id=customer_id,
            coach_id=coach_id,
            status=LessonRecordStatus.ATTENDED.value,
            charge=-1,
            seat_id=seat.id
        )
        # 扣除一节课时
        trainee.attended_lessons += 1  # 将已上课时加一
        db.session.add(lesson_record)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e
    return


def queue_and_send_confirmed_message(new_seat):
    # 发送预约提醒信息给教练
    data = {"seat": new_seat}
    queue_coach_confirmed_message(data)
    coach_open: WxOpenUser = WxOpenUser.query.filter(and_(
        WxOpenUser.coach_id == new_seat.coach_id,
        WxOpenUser.role == 'coach',
    )).first()
    send_messages(coach_open)


def queue_and_send_reservation_message(seat):
    data = {'seat': seat}
    queue_customer_reservation_message(data)  # 添加预约成功信息进入队列

    customer_open: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.customer_id == seat.customer_id,
    ).first()
    send_messages(customer_open)  # 发送预约成功信息给会员


def queue_and_send_cancel_message(seat):
    customer_id = seat.customer_id
    customer_open: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.customer_id == customer_id,
    ).first()
    data = {"seat": seat}
    queue_customer_cancel_message(data)
    send_messages(customer_open)


class StatusMachine(object):
    def __init__(self, seat):
        self.seat = seat
        self.now = datetime.now()

    def transform(self, new_status: SeatStatus):
        if self.seat.status == SeatStatus.CONFIRM_REQUIRED and new_status == SeatStatus.CONFIRMED:
            # 待确认 -> 确认
            self.seat.status = SeatStatus.CONFIRMED.value
            self.seat.confirmed_at = self.now
            self.seat.modified_at = self.now
            queue_and_send_reservation_message(self.seat)
            db.session.commit()

        elif self.seat.status == SeatStatus.CONFIRMED and new_status == SeatStatus.ATTENDED:
            # 确认(待上课) -> 已上课
            self.seat.status = SeatStatus.ATTENDED.value
            self.seat.confirmed_at = self.now
            self.seat.modified_at = self.now
            db.session.commit()
            minus_lesson(self.seat, self.now)  # 扣除课时(此课时为旧版本的课时,暂时保留)

        elif self.seat.status == SeatStatus.CONFIRM_EXPIRED and new_status == SeatStatus.ATTENDED:
            # 已过期 -> 已上课
            self.seat.status = SeatStatus.ATTENDED.value
            self.seat.confirmed_at = self.now
            self.seat.modified_at = self.now
            db.session.commit()
            minus_lesson(self.seat, self.now)  # 扣除课时(此课时为旧版本的课时,暂时保留)

        elif self.seat.status == SeatStatus.CONFIRM_REQUIRED and new_status == SeatStatus.ATTENDED:
            # 待确认 -> 已上课
            self.seat.status = SeatStatus.ATTENDED.value
            self.seat.confirmed_at = self.now
            self.seat.modified_at = self.now
            db.session.commit()
            minus_lesson(self.seat, self.now)  # 扣除课时(此课时为旧版本的课时,暂时保留)

        elif self.seat.status == SeatStatus.CONFIRM_REQUIRED and new_status == SeatStatus.CONFIRM_EXPIRED:
            # 待确认 -> 超时
            self.seat.status = SeatStatus.CONFIRM_EXPIRED.value
            self.seat.modified_at = self.now
            db.session.commit()

        else:
            raise KeyError('unknown transform {}->{}'.format(self.seat.status, new_status))

    def cancel(self):
        # 取消
        self.seat.is_valid = False
        self.seat.canceled_at = self.now
        self.seat.modified_at = self.now
        queue_and_send_cancel_message(self.seat)
        db.session.commit()
