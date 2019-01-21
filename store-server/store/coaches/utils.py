from datetime import datetime
from store.database import db
from store.domain.models import MonthReport, Trainee, Seat, SeatPriority
from store.utils.time_formatter import get_yymm, get_year, get_month, get_yymmdd
from store.utils import time_processing as tp
from typing import List
from store.coaches.apis import get_total_lesson, get_month_attended_count
from store.domain.cache import TraineeCache, CustomerCache
from sqlalchemy import and_, func, false, true


def refresh_month_record(seat):
    coach_id = seat.coach_id
    yymm = get_yymm(seat.yymmdd)
    month_report: MonthReport = MonthReport.query.filter(and_(
        MonthReport.coach_id == coach_id,
        MonthReport.yymm == yymm
    )).first()

    if not month_report:
        # 如果没有月报则说明当月的月报还未生成，不需要刷新
        return

    year = get_year(seat.yymmdd)
    month = get_month(seat.yymmdd)
    early_month = datetime(year, month, 1)
    end_month = tp.get_end_month(early_month)
    days = tp.get_day_of_month(datetime(year, month, 1))

    early_yymmdd = get_yymmdd(early_month)
    end_yymmdd = get_yymmdd(end_month)

    exp_count = db.session.query(func.count(Seat.customer_id)).filter(and_(
        Seat.is_valid == true(),
        Seat.coach_id == coach_id,
        Seat.yymmdd >= early_yymmdd,
        Seat.yymmdd <= end_yymmdd,
        Seat.priority == SeatPriority.EXPERIENCE.value,
    )).scalar()  # 体验课时

    trainee_count = db.session.query(func.count(Trainee.id).filter(and_(
        Trainee.coach_id == coach_id,
        Trainee.is_bind == true(),
    ))).scalar()  # 会员总数

    trainees: List[Trainee] = Trainee.query.filter(and_(
        Trainee.coach_id == coach_id,
        Trainee.is_bind == true(),
    )).all()

    ranking = []
    for trainee in trainees:
        trainee_cache = TraineeCache(trainee.coach_id, trainee.customer_id)
        customer_cache = CustomerCache(customer_id=trainee.customer_id)
        name = trainee_cache.get('name')
        avatar = customer_cache.get('avatar')
        attended_count = get_month_attended_count(trainee, year, month)
        ranking.append({
            'name': name,
            'avatar': avatar,
            'attended_count': attended_count,
        })

    month_total_lesson = get_total_lesson(coach_id, year, month)
    month_report.exp_count = exp_count
    month_report.private_count = trainee_count
    month_report.trainee_ranking = ranking
    month_report.total_lesson = month_total_lesson
    month_report.average = "%.1f" % float(month_total_lesson / days)
    db.session.commit()
    return
