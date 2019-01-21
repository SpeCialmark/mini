from datetime import datetime
from typing import List

from flask import Blueprint
from flask import jsonify, request, g
from http import HTTPStatus

from sqlalchemy import true, func, desc, asc

from store.coaches.apis import get_exp_count, get_total_lesson
from store.database import db
from store.domain.cache import CoachCache
from store.domain.middle import roles_required, permission_required
from store.domain.models import Salesman, CouponReport, ShareVisit, Share, Coach, Trainee, Store
from store.domain.permission import ManageSalesmanPermission, ManagePrivateCoachPermission
from store.share.utils import ShareRecord
from store.utils import time_processing as tp
import time

blueprint = Blueprint('_statistics', __name__)


@blueprint.route('/salesmen', methods=['GET'])
@permission_required(ManageSalesmanPermission())
def get_salesmen_statistics():
    # 获取会籍的统计数据
    biz_id = g.get('biz_id')
    salesmen: List[Salesman] = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.is_official == true(),
    ).all()
    if not salesmen:
        return jsonify({
            'total_count': {
                'access_count': 0,  # 访问此页面的总访问量
                'total_visit_new': 0,  # 访问此页面的总用户量
                'today_visit': 0,  # 当日访问此页面的总用户量
                'today_visit_new': 0,  # 当日访问此页面的新用户量(当日创建的customer)
                'exp_customers': 0,  # 领取优惠券的人数
            },
            'salesman_statistics': []
        })
    start_date_str = request.args.get('start_date', default=datetime.today().strftime('%Y-%m-%d'))
    end_date_str = request.args.get('end_date', default=datetime.today().strftime('%Y-%m-%d'))

    start_date = tp.get_day_min(datetime.strptime(start_date_str, '%Y-%m-%d'))
    end_date = tp.get_day_max(datetime.strptime(end_date_str, '%Y-%m-%d'))
    total_count = {
        'access_count': 0,  # 访问此页面的总访问量
        'total_visit_new': 0,  # 访问此页面的总用户量
        'today_visit': 0,  # 当日访问此页面的总用户量
        'today_visit_new': 0,  # 当日访问此页面的新用户量(当日创建的customer)
        'exp_customers': 0,  # 领取优惠券的人数
    }
    salesman_statistics = []
    for salesman in salesmen:
        sr = ShareRecord(biz_id=biz_id, salesman_id=salesman.id)
        shares = sr.get_user_shares()  # 获取用户的所有share记录
        salesman_visit = sr.get_all_pages_visit(s=shares, start_date=start_date, end_date=end_date)  # 总访客记录
        exp_customers = len(db.session.query(func.count(CouponReport.customer_id), CouponReport.customer_id).filter(
            CouponReport.salesman_id == salesman.id,
            CouponReport.created_at >= start_date,
            CouponReport.created_at <= end_date,
        ).group_by(CouponReport.customer_id).all())  # 领取优惠券的人数
        salesman_visit.update({
            'name': salesman.name,
            'avatar': salesman.avatar,
            'exp_customers': exp_customers
        })
        salesman_statistics.append(salesman_visit)
        total_count['exp_customers'] += exp_customers
        total_count['access_count'] += salesman_visit['access_count']
        total_count['total_visit_new'] += salesman_visit['total_visit_new']
        total_count['today_visit'] += salesman_visit['today_visit']
        total_count['today_visit_new'] += salesman_visit['today_visit_new']
    salesman_statistics.sort(key=lambda x: (x['exp_customers']), reverse=True)

    all_share: List[Share] = Share.query.filter(
        Share.biz_id == biz_id
    ).all()
    share_ids = [s.id for s in all_share]
    first_visit: ShareVisit = ShareVisit.query.filter(
        ShareVisit.share_id.in_(share_ids)
    ).order_by(asc(ShareVisit.created_at)).first()
    first_date = first_visit.created_at
    return jsonify({
        'total_count': total_count,
        'salesman_statistics': salesman_statistics,
        'first_date': int((time.mktime(first_date.timetuple()) + first_date.microsecond / 1E6) * 1000),
        'is_one_day': bool(start_date_str == end_date_str)
    })


@blueprint.route('/coaches', methods=['GET'])
@permission_required(ManagePrivateCoachPermission())
def get_coaches_statistics():
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    if not store:
        return jsonify(msg='商家不存在'), HTTPStatus.NOT_FOUND
    if not store.coach_indexes:
        return jsonify({
            'total_count': {
                'private_lesson': 0,
                'exp_lesson_count': 0,
                'trainee_count': 0
            },
            'coach_statistics': []
        })
    coach_ids = store.coach_indexes
    yymm = request.args.get('yymm', default=tp.get_early_month(datetime.today()).strftime('%Y%m'))
    year = int(yymm[:4])
    month = int(yymm[4:])
    early_month = datetime(year, month, 1)
    end_month = tp.get_end_month(early_month)
    coaches: List[Coach] = Coach.query.filter(
        Coach.id.in_(coach_ids)
    ).all()
    coach_statistics = []
    total_count = {
        'private_lesson': 0,
        'exp_lesson': 0,
        'trainee_count': 0
    }
    for coach in coaches:
        exp_count = get_exp_count(coach.id, early_month)  # 体验会员人数
        private_count = db.session.query(func.count(Trainee.id).filter(
            Trainee.coach_id == coach.id,
            Trainee.bind_at >= early_month,
            Trainee.bind_at <= end_month
        )).scalar()  # 会员总数
        month_total_lesson = get_total_lesson(coach.id, year, month)
        coach_cache = CoachCache(coach.id)
        c_brief = coach_cache.get('brief')
        c_brief.update({
            'private_lesson': month_total_lesson,
            'exp_lesson': exp_count,
            'private_count': private_count
        })
        coach_statistics.append(c_brief)
        total_count['private_lesson'] += month_total_lesson
        total_count['exp_lesson'] += exp_count
        total_count['trainee_count'] += private_count

    first_date = tp.get_early_month(store.created_at)
    return jsonify({
        'total_count': total_count,
        'coach_statistics': coach_statistics,
        'first_date': int((time.mktime(first_date.timetuple()) + first_date.microsecond / 1E6) * 1000)
    })
