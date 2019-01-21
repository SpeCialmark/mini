from datetime import datetime, timedelta
from typing import List

from sqlalchemy import false, true

from store.database import db
from store.domain.cache import StoreBizCache
from store.domain.key_data import get_nearest_record
from store.domain.models import CouponReport, Customer, Coupon, Plan, PlanStatus
from store.utils import time_processing as tp


def finish_plan():
    # 查询所有正在生效中的计划
    today = datetime.now()
    plans: List[Plan] = Plan.query.filter(
        Plan.status == PlanStatus.ACTION.value
    ).all()
    for p in plans:
        effective_at = p.effective_at
        if not effective_at:
            continue
        finished_at = effective_at + timedelta(days=p.duration)
        if finished_at <= today:
            p.status = PlanStatus.FINISH.value
            p.finished_at = finished_at

        nearest_record = get_nearest_record(p.customer_id, p)
        res = []
        for r in nearest_record:
            name = r.get('name')
            target = r.get('target')
            data = r.get('data')
            initial_data = r.get('initial_data')
            if target and data:
                data = round(float(data), 1)
                target = round(float(target), 1)
                initial_data = round(float(initial_data), 1)
                if initial_data < target:
                    if data == target:
                        change_str = '恭喜您!达成目标!请继续坚持.'
                    elif data > target:
                        change_str = '恭喜您!超额完成目标!比目标超出了{data}{unit}.请继续坚持.'.format(data=data - target,
                                                                                   unit=r.get('unit'))
                    else:
                        change_str = '很遗憾,您没能达成目标.距目标还差{data}{unit}.请继续坚持.'.format(data=target - data,
                                                                                   unit=r.get('unit'))
                else:
                    if data == target:
                        change_str = '恭喜您!达成目标!请继续坚持.'
                    elif data < target:
                        change_str = '恭喜您!超额完成目标!比目标超出了{data}{unit}.请继续坚持.'.format(data=target - data,
                                                                                   unit=r.get('unit'))
                    else:
                        change_str = '很遗憾,您没能达成目标.距目标还差{data}{unit}.请继续坚持.'.format(data=data - target,
                                                                                   unit=r.get('unit'))
                res.append({
                    'name': name,
                    'change': change_str,
                    'data': data,
                    'target': target
                })
        # 若是提前结束则该阶段的时长为截止日期的时长
        p.result = res
        p.finished_at = today
        p.status = PlanStatus.FINISH.value
        p.modified_at = today
        p.duration = (tp.get_day_min(today) - p.effective_at).days + 1
    db.session.commit()
    return
