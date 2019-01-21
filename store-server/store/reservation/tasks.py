from sqlalchemy.sql.expression import true
from sqlalchemy import and_
from store.domain.models import Seat, SeatStatus, SeatTrigger, SeatPriority
from datetime import datetime, timedelta
from store.reservation.utils import StatusMachine
from store.utils.time_formatter import get_yymmdd
from typing import List
from store.utils import time_processing as tp
from store.database import db


def set_attend_flag():
    now = datetime.now()
    yymmdd = get_yymmdd(now)

    # 查询过去的，已经确认
    past_seats: List[Seat] = Seat.query.filter(and_(
        Seat.is_valid == true(),
        Seat.yymmdd <= yymmdd,
        Seat.status == SeatStatus.CONFIRMED.value
    )).all()

    for s in past_seats:
        if s.end_time < now:
            # 结束时间已过
            # 确认(待上课) -> 已上课
            # 扣除课时
            StatusMachine(s).transform(SeatStatus.ATTENDED)

    # 查询过去的, 待确认的
    expired_seats: List[Seat] = Seat.query.filter(and_(
        Seat.is_valid == true(),
        Seat.yymmdd <= yymmdd,
        Seat.status == SeatStatus.CONFIRM_REQUIRED.value
    )).all()

    for s in expired_seats:
        if s.start_time < now:
            # 开始时间已过
            # 待确认 -> 超时
            StatusMachine(s).transform(SeatStatus.CONFIRM_EXPIRED)


def automatic_reservation():
    """
    当前时间为周二0时，帮会员自动预约下周二的时段
    :return:
    """
    now = datetime.now()
    next_week = now + timedelta(days=7)       # 7天后的
    week = tp.get_week(next_week)
    yymmdd = get_yymmdd(next_week)

    seat_triggers: List[SeatTrigger] = SeatTrigger.query.filter(and_(
        SeatTrigger.week == week,
    )).all()

    for st in seat_triggers:
        same_seat: Seat = Seat.query.filter(
            Seat.is_valid == true(),
            Seat.coach_id == st.coach_id,
            Seat.customer_id == st.customer_id,
            Seat.yymmdd == yymmdd,
            Seat.start == st.start,
            # Seat.end == st.end
        ).first()
        if same_seat:
            # 已经写入数据库了
            continue
        else:
            # 预约
            seat = Seat(
                coach_id=st.coach_id,
                customer_id=st.customer_id,
                yymmdd=yymmdd,
                start=st.start,
                end=st.end,
                priority=SeatPriority.PRIVATE.value,
                status=SeatStatus.CONFIRMED.value,
                reserved_at=now,
                confirmed_at=now,
                created_at=now,
            )
            db.session.add(seat)
            db.session.commit()
