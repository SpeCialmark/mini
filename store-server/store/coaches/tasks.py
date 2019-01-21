from datetime import datetime
from typing import List
from sqlalchemy import and_, true, desc
from store.coaches.apis import get_exp_count, get_private_count, get_total_lesson, get_month_attended_count
from store.database import db
from store.domain.cache import TraineeCache, CustomerCache
from store.domain.models import Coach, Trainee, MonthReport
from store.utils import time_processing as tp
from store.utils.time_formatter import get_yymmdd, get_yymm


def generate_month_record(biz_id):
    """ 自动生成月报 """
    coaches: List[Coach] = Coach.query.filter(
        Coach.biz_id == biz_id,
        Coach.coach_type == 'private',  # 目前只有私教需要生成月报
        Coach.in_service == true()
    ).all()
    now = datetime.now()  # 2018.8.02
    # 生成上个月的月报 -> 7月份
    last_early_month = tp.get_last_early_month(now)  # 上个月初
    days = tp.get_day_of_month(last_early_month)  # 上月天数
    yymmdd = get_yymmdd(last_early_month)
    yymm = get_yymm(yymmdd)
    for coach in coaches:
        exp_count = get_exp_count(coach.id, last_early_month)
        private_count = get_private_count(coach.id)
        month_total_lesson = get_total_lesson(coach.id, last_early_month.year, last_early_month.month)

        trainees: List[Trainee] = Trainee.query.filter(and_(
            Trainee.coach_id == coach.id,
            Trainee.is_bind == true(),
        )).order_by(desc(Trainee.attended_lessons)).all()

        ranking = []
        for trainee in trainees:
            trainee_cache = TraineeCache(trainee.coach_id, trainee.customer_id)
            name = trainee_cache.get('name')
            customer_cache = CustomerCache(customer_id=trainee.customer_id)
            avatar = customer_cache.get('avatar')
            attended_count = get_month_attended_count(trainee, last_early_month.year, last_early_month.month)
            ranking.append({
                'name': name,
                'avatar': avatar,
                'attended_count': attended_count,
                'id': trainee.get_hash_id()
            })
        ranking.sort(key=lambda x: (x['attended_count']), reverse=True)  # 按照当月已上课时从大到小排序

        month_report = MonthReport(
            biz_id=biz_id,
            coach_id=coach.id,
            yymm=yymm,
            exp_count=exp_count,
            private_count=private_count,
            total_lesson=month_total_lesson,
            trainee_ranking=ranking,
            average="%.1f" % float(month_total_lesson / days),
            created_at=now,
        )

        db.session.add(month_report)
    db.session.commit()

    return
