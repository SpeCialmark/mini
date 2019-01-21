import re

import base62
from http import HTTPStatus

from flask import Blueprint
from flask import jsonify, request, g
from sqlalchemy import true

from store.database import db
from store.domain.middle import permission_required, roles_required
from store.domain.models import Share, Salesman, ShareVisit, Customer
from store.domain.role import CustomerRole
from store.share.utils import ShareRecord, BaseRecord
from store.utils.sms import verify_sms_code

blueprint = Blueprint('_share', __name__)


@blueprint.route('/login_status', methods=['GET'])
@roles_required(CustomerRole())
def get_login_status():
    """ 获取用户登陆状态(前端保存到本地,丢失后再获取) """
    # 待用户端的版本更新后废除该接口, 改为customer接口下
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND

    salesman: Salesman = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.phone_number == customer.phone_number,
        Salesman.is_official == true()
    ).first()

    return jsonify({
        "is_login": customer.is_login,
        'is_salesman': bool(salesman)
    })


@blueprint.route('', methods=['POST'])
@roles_required(CustomerRole())
def post_share():
    """ 每当用户进行分享操作时调用,生成对应的share记录 """
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    path = json_data.get('path')
    params = json_data.get('params')
    s_type = json_data.get('share_type')
    salesman: Salesman = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.phone_number == customer.phone_number
    ).first()
    if salesman:
        # 创建分享记录器(id为分享者的id)
        sr = ShareRecord(biz_id=biz_id, salesman_id=salesman.id)
    else:
        sr = ShareRecord(biz_id=biz_id, customer_id=customer_id)

    # 校验参数
    is_ok, params = sr.check_params(params)

    if not is_ok:
        return jsonify(msg='参数错误'), HTTPStatus.BAD_REQUEST
    # 生成分享记录
    res = sr.post_share(path=path, params=params, s_type=s_type)  # s_id已经base62编码过了

    return jsonify(res)


@blueprint.route('/<string:s_id>', methods=['GET'])
@roles_required()
def get_share(s_id):
    """ 前端通过share_id获取对应的参数 """
    share_id = base62.decode(s_id)
    share: Share = Share.query.filter(
        Share.id == share_id
    ).first()
    if not share:
        return jsonify(msg='非法的share_id'), HTTPStatus.NOT_FOUND
    params = share.params
    params_dict = BaseRecord.get_params_dict(params)
    return jsonify(params_dict)


@blueprint.route('/phone_login', methods=['POST'])
@roles_required(CustomerRole())
def post_login():
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    phone_number = json_data.get('phone_number')
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    sms_code = json_data.get('sms_code')
    if not sms_code:
        return jsonify(msg='验证码缺失'), HTTPStatus.BAD_REQUEST

    verified, msg = verify_sms_code(phone_number=phone_number, sms_code=sms_code)
    if not verified:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()

    if not customer.phone_number or customer.phone_number == '':
        # 保证一个微信号对应一个手机号
        customer.phone_number = phone_number

    customer.is_login = True  # 记录登录状态
    db.session.commit()

    salesman: Salesman = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.phone_number == phone_number,
        Salesman.is_official == true()
    ).first()

    return jsonify({
        'is_login': True,
        'is_salesman': bool(salesman)
    })


@blueprint.route('/visit_report', methods=['GET'])
@roles_required(CustomerRole())
def get_visit_report():
    """ 获取访客记录报表 """
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND

    salesman: Salesman = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.phone_number == customer.phone_number
    ).first()
    if salesman:
        # 说明该customer是salesman
        sr = ShareRecord(biz_id=biz_id, salesman_id=salesman.id)
    else:
        sr = ShareRecord(biz_id=biz_id, customer_id=customer_id)

    shares = sr.get_user_shares()  # 获取用户的所有share记录
    all_visit = sr.get_visit(shares=shares)  # 总访客记录
    visit_detail = sr.get_visit_detail(shares)  # 访客记录详情

    return jsonify({
        'all_visit': all_visit,
        'visit_detail': visit_detail
    })


@blueprint.route('/<string:s_id>/visit', methods=['PUT'])
@roles_required()
def put_share_visit(s_id):
    """ 添加访客记录 """
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    share_id = base62.decode(s_id)
    share: Share = Share.query.filter(
        Share.id == share_id
    ).first()
    if not share:
        return jsonify(msg='非法的分享id'), HTTPStatus.NOT_FOUND

    if share.shared_customer_id:
        customer: Customer = Customer.query.filter(
            Customer.id == share.shared_customer_id
        ).first()
        # 当用户进行分享的时候,若该用户有会籍,则新打开这个分享的用户也会绑定该会籍
        salesman_id = customer.belong_salesman_id if customer.belong_salesman_id and customer.belong_salesman_id != 0 else customer.salesman_id
        if salesman_id:
            share.shared_salesman_id = salesman_id

    sr = ShareRecord(biz_id=biz_id)
    sr.put_share_visit(visit_cid=customer_id, s=share)

    return jsonify()
