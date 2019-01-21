from datetime import datetime
from typing import List

from sqlalchemy import false, true

from store.database import db
from store.domain.cache import StoreBizCache
from store.domain.models import CouponReport, Customer, Coupon
from store.utils import time_processing as tp


def set_expired_flag():
    today = tp.get_day_max(datetime.today())

    # 查询所有已领取过的优惠券
    received_coupons: List[CouponReport] = CouponReport.query.filter().all()
    # 所有领取过优惠劵的用户
    customers = set(c.customer_id for c in received_coupons)

    # 已过期的卷
    expired_coupons = [c for c in received_coupons if c.expire_at < today and c.is_used is False]
    try:
        for expired_coupon in expired_coupons:
            # 设置为已过期
            expired_coupon.is_used = True
        db.session.commit()

        # 查询用户是否还有有效的优惠券
        valid_coupons: List[CouponReport] = CouponReport.query.filter(
            CouponReport.customer_id.in_(customers),
            CouponReport.is_used == false()
        ).all()

        valid_customers = set(c.customer_id for c in valid_coupons)

        # 已经没有优惠劵的用户,对会籍来说属于公共资源
        free_customers = customers - valid_customers
        f_customers: List[Customer] = Customer.query.filter(
            Customer.id.in_(free_customers)
        ).all()
        for f_c in f_customers:
            f_c.belong_salesman_id = 0

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print('=========设置优惠券自动过期失败===========')
        raise e
    return


def turn_off_coupons():
    today_max = tp.get_day_max(datetime.today())
    # 查询所有已经到达失效时间开关还开着的优惠券
    coupons: List[Coupon] = Coupon.query.filter(
        Coupon.expire_at < today_max,
        Coupon.switch == true()
    ).all()
    for c in coupons:
        c.switch = False
        db.session.commit()
        store_cache = StoreBizCache(c.biz_id)
        store_cache.reload()

    return
