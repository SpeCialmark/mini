from datetime import datetime
from http import HTTPStatus
from typing import List

from flask import Blueprint
from flask import jsonify, request, g
from sqlalchemy import true, false, desc

from store.database import db
from store.domain.cache import StoreBizCache, CustomerCache
from store.domain.middle import roles_required, permission_required
from store.domain.models import Customer, Salesman, Coupon, CouponReport, WxOpenUser
from store.domain.permission import ManageSalesmanPermission
from store.domain.role import CustomerRole
from store.utils import time_processing as tp

blueprint = Blueprint('_coupons', __name__)


@blueprint.route('', methods=['GET'])
@permission_required(ManageSalesmanPermission())
def get_biz_coupons():
    biz_id = g.get('biz_id')
    store_cache = StoreBizCache(biz_id)
    coupons_brief = store_cache.get('coupons_brief')
    return jsonify({
        "coupons": coupons_brief
    })


@blueprint.route('', methods=['POST'])
@permission_required(ManageSalesmanPermission())
def post_coupon():
    # 添加新的优惠券
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    name = json_data.get('name')
    effective_date = json_data.get('effective_date')
    description = json_data.get('description')
    if not all([name, description, effective_date]):
        return jsonify(msg='请将信息填写完整'), HTTPStatus.BAD_REQUEST

    effective_at = datetime.strptime(effective_date[0], '%Y-%m-%d')
    expire_at = datetime.strptime(effective_date[1], '%Y-%m-%d')

    today_min = tp.get_day_min(datetime.today())
    if expire_at < today_min:
        # 选择的失效日期小于今日
        return jsonify(msg='请选择正确的有效期限'), HTTPStatus.BAD_REQUEST

    old_coupon: Coupon = Coupon.query.filter(
        Coupon.biz_id == biz_id,
        Coupon.name == name
    ).first()
    if old_coupon:
        return jsonify(msg='该优惠券已存在'), HTTPStatus.BAD_REQUEST

    new_coupon = Coupon(
        biz_id=biz_id,
        name=name,
        description=description,
        created_at=datetime.now(),
        effective_at=effective_at,
        expire_at=expire_at,
    )
    db.session.add(new_coupon)
    db.session.commit()
    store_cache = StoreBizCache(biz_id)
    store_cache.reload()

    return jsonify(msg='添加成功')


@blueprint.route('/pc/<string:c_id>', methods=['GET'])
@permission_required(ManageSalesmanPermission())
def get_coupon_brief(c_id):
    # pc端获取优惠券详情
    coupon: Coupon = Coupon.find(c_id)
    if not coupon:
        return jsonify(msg='不存在的优惠券'), HTTPStatus.NOT_FOUND
    return jsonify({
        'coupon': coupon.get_brief()
    })


@blueprint.route('/<string:c_id>', methods=['PUT'])
@permission_required(ManageSalesmanPermission())
def put_coupon(c_id):
    # 修改优惠券信息
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    coupon: Coupon = Coupon.find(c_id)
    if not coupon:
        return jsonify(msg='不存在的优惠券'), HTTPStatus.NOT_FOUND
    name = json_data.get('name')
    description = json_data.get('description')

    effective_date = json_data.get('effective_date')
    if effective_date:
        effective_at = datetime.strptime(effective_date[0], '%Y-%m-%d')
        expire_at = datetime.strptime(effective_date[1], '%Y-%m-%d')
        today_min = tp.get_day_min(datetime.today())
        if expire_at < today_min:
            return jsonify(msg='请选择正确的有效期限'), HTTPStatus.BAD_REQUEST
        coupon.effective_at = effective_at
        coupon.expire_at = expire_at
    if name:
        coupon.name = name
    if description:
        coupon.description = description

    db.session.commit()
    db.session.refresh(coupon)

    store_cache = StoreBizCache(biz_id)
    store_cache.reload()

    return jsonify({
        'coupon': coupon.get_brief()
    })


@blueprint.route('/<string:c_id>/switch', methods=['PUT'])
@permission_required(ManageSalesmanPermission())
def put_switch(c_id):
    # 修改券的开关
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    coupon_switch = json_data.get('switch')
    coupon: Coupon = Coupon.find(c_id)
    if not coupon:
        return jsonify(msg='不存在的优惠券'), HTTPStatus.NOT_FOUND

    if coupon_switch is None:
        return jsonify(msg='missing data'), HTTPStatus.BAD_REQUEST

    if coupon_switch:
        today_min = tp.get_day_min(datetime.today())
        if coupon.expire_at < today_min:
            return jsonify(msg='该优惠券有效期已过,请修改有效期后再打开开关'), HTTPStatus.BAD_REQUEST
    coupon.switch = coupon_switch
    db.session.commit()
    db.session.refresh(coupon)
    store_cache = StoreBizCache(biz_id)
    store_cache.reload()
    return jsonify({
        'switch': coupon.switch
    })


@blueprint.route('/<string:c_id>/validity_period', methods=['PUT'])
@permission_required(ManageSalesmanPermission())
def put_validity_period(c_id):
    # 修改劵的有效期
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    validity_period = json_data.get('validity_period')
    coupon: Coupon = Coupon.find(c_id)
    if not coupon:
        return jsonify(msg='不存在的优惠券'), HTTPStatus.NOT_FOUND

    if validity_period:
        coupon.validity_period = validity_period
    db.session.commit()
    db.session.refresh(coupon)
    store_cache = StoreBizCache(biz_id)
    store_cache.reload()
    return jsonify(msg='修改成功')


@blueprint.route('/salesman/<string:s_id>', methods=['GET'])
@roles_required(CustomerRole())
def get_salesman_coupons(s_id):
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND
    salesman: Salesman = Salesman.find(s_id)
    if not salesman:
        return jsonify({
            'coupons': []
        })

    coupons = Coupon.get_all_coupons(biz_id)
    # 查询用户领取过的优惠券
    coupon_ids = [c.id for c in coupons]
    c_reports: List[CouponReport] = CouponReport.query.filter(
        CouponReport.customer_id == customer_id,
        CouponReport.coupon_id.in_(coupon_ids),
        CouponReport.is_used == false()
    ).all()

    res = []
    if not check_coupons(c_reports, salesman.id):
        # 若当前还有未使用过的优惠券则无法领取其他会籍的优惠券,但是仍然显示可领取,在领取时会有相应的提示
        for c in coupons:
            brief = c.get_brief()
            brief.update({'is_used': True})
            res.append(brief)

        return jsonify({
            'coupons': res
        })

    res = get_coupons_status(coupons=coupons, c_reports=c_reports)

    return jsonify({
        'coupons': res
    })


@blueprint.route('/salesman/<string:s_id>', methods=['POST'])
@roles_required(CustomerRole())
def receive_salesman_coupon(s_id):
    # 领取优惠券
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    coupon_hid = json_data.get('coupon_id')
    phone_number = json_data.get('phone_number')
    salesman: Salesman = Salesman.find(s_id)
    if not salesman:
        return jsonify(msg='会籍不存在'), HTTPStatus.NOT_FOUND
    coupon: Coupon = Coupon.find(coupon_hid)
    if not coupon:
        return jsonify(msg='商家尚未开放此类优惠券'), HTTPStatus.NOT_FOUND
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND

    if not check_salesman(biz_id, phone_number):
        return jsonify(msg='健身顾问不能相互领取优惠券'), HTTPStatus.BAD_REQUEST

    now = datetime.now()

    coupons = Coupon.get_all_coupons(biz_id)
    # 查询用户领取过的优惠券
    coupon_ids = [c.id for c in coupons]
    c_reports: List[CouponReport] = CouponReport.query.filter(
        CouponReport.customer_id == customer_id,
        CouponReport.coupon_id.in_(coupon_ids),
        CouponReport.is_used == false()
    ).all()
    for c in c_reports:
        if c.coupon_id == coupon.id and c.customer_id == customer_id and c.is_used is False:
            # 已领取未使用
            return jsonify(msg='您已经领取过该优惠券了'), HTTPStatus.BAD_REQUEST

    if not check_coupons(c_reports, salesman.id):
        return jsonify(msg='您已经领取过其他健身顾问的优惠券了'), HTTPStatus.BAD_REQUEST

    try:
        new_coupon = CouponReport(
            customer_id=customer_id,
            coupon_id=coupon.id,
            salesman_id=salesman.id,
            expire_at=coupon.expire_at,
            effective_at=coupon.effective_at,
            created_at=now,
            is_used=False
        )

        customer.belong_salesman_id = salesman.id  # 绑定用户与会籍
        customer.phone_number = phone_number
        customer_cache = CustomerCache(customer_id)
        customer_cache.reload()

        db.session.add(new_coupon)
        db.session.commit()
        db.session.refresh(new_coupon)

        c_reports.append(new_coupon)

    except Exception as e:
        db.session.rollback()
        return jsonify(msg='领取失败,请稍后重试'), HTTPStatus.BAD_REQUEST

    res = get_coupons_status(coupons=coupons, c_reports=c_reports)

    return jsonify({
        'coupons': res
    })


@blueprint.route('/customers', methods=['GET'])
@roles_required()
def get_coupon_customer():
    # 获取领取过优惠劵的用户
    w_id = g.get('w_id')
    biz_id = g.get('biz_id')
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
            Customer.biz_id == biz_id
        ).first()
        if not customer:
            return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

        salesman: Salesman = Salesman.query.filter(
            Salesman.biz_id == biz_id,
            Salesman.phone_number == customer.phone_number
        ).first()
        if not salesman:
            return jsonify()

    # PC
    else:
        salesman_hid = request.args.get('salesman_id')
        salesman: Salesman = Salesman.find(salesman_hid)
        if not salesman:
            return jsonify(msg='会籍不存在'), HTTPStatus.NOT_FOUND

    c_reports: List[CouponReport] = CouponReport.query.filter(
        CouponReport.salesman_id == salesman.id,
    ).order_by(desc(CouponReport.created_at)).all()

    for c_report in c_reports:
        customer_id = c_report.customer_id
        customer_cache = CustomerCache(customer_id)
        nick_name, avatar, phone_number = customer_cache.get('nick_name', 'avatar', 'phone_number')
        c_brief = {
            'nick_name': nick_name,
            'avatar': avatar,
            'phone_number': phone_number,
            'received_date': c_report.created_at.strftime("%Y-%m-%d")  # 领取时间
        }
        res.append(c_brief)

    return jsonify(res)


def check_salesman(biz_id, phone_number):
    # 校验领券的手机号是否是官方会籍(为了防止绑定后无法进入自己名片的情况)
    official_salesman: Salesman = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.phone_number == phone_number,
        Salesman.is_official == true()
    ).first()
    if official_salesman:
        # 不能相互领取优惠券
        return False

    return True


def check_coupons(coupon_reports, salesman_id):
    # 领取过某个会籍的券后在有效期间不能再领取别的会籍的券
    # 未使用过的劵
    # c_reports = [c for c in coupon_reports if c.is_used is False]
    salesman_ids = [c.salesman_id for c in coupon_reports]
    if not salesman_ids or salesman_id in salesman_ids:
        # 可以领取
        return True
    return False


def get_coupons_status(coupons, c_reports):
    # 获取所有优惠券的状态
    res = []
    for c_report in c_reports:
        if c_report.coupon in coupons:
            coupons.remove(c_report.coupon)
        res.append(c_report.get_brief())

    for c in coupons:
        brief = c.get_brief()
        brief.update({'is_used': True})
        res.append(brief)
    return res
