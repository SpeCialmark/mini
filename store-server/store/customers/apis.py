from datetime import datetime
from typing import List

import re
from flask import Blueprint
from flask import jsonify, request, g
from sqlalchemy import null, or_, and_, true, desc

from store.database import db
from http import HTTPStatus

from store.domain.cache import CourseCache, CoachCache
from store.domain.middle import roles_required
from store.domain.models import Customer, Trainee, Contract, Salesman, Beneficiary, ContractContent
from store.domain.role import CustomerRole
from store.trainee.utils import get_lesson_profile
from store.utils.sms import verify_sms_code

blueprint = Blueprint('_customer', __name__)


@blueprint.route('/phone_login', methods=['POST'])
@roles_required(CustomerRole())
def post_phone_login():
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

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

    try:
        # TODO 不同手机不同账号
        # 将手机号绑定到customer上
        customer.phone_number = phone_number
        customer.is_login = True
        customer.modified_at = datetime.now()

        # 查询有手机号但是没有customer_id的或者有customer_id但是没有手机号的学员
        trainee: List[Trainee] = Trainee.query.filter(
            or_(
                and_(
                    Trainee.phone_number == phone_number,
                    Trainee.customer_id == null()
                ),
                and_(
                    Trainee.phone_number == null(),
                    Trainee.customer_id == customer.id
                )
            )
        ).all()
        for t in trainee:
            if not t.customer_id:
                t.customer_id = c_id
            if not t.phone_number:
                t.phone_number = phone_number

        # 查询该门店下相同号码的合同受益人,填充其customer_id
        beneficiaries: List[Beneficiary] = Beneficiary.query.filter(
            Beneficiary.biz_id == biz_id,
            Beneficiary.phone_number == phone_number,
            Beneficiary.customer_id == null()
        ).all()
        for b in beneficiaries:
            b.customer_id = customer.id

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e

    return jsonify(msg='登陆成功')


@blueprint.route('/phone_number', methods=['PUT'])
@roles_required(CustomerRole())
def changer_phone_number():
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(MSG='账号有误'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    new_phone_number = json_data.get('phone_number')
    old_phone_number = customer.phone_number
    if new_phone_number == old_phone_number:
        return jsonify()
    # TODO
    return jsonify()


@blueprint.route('/login_status', methods=['GET'])
@roles_required(CustomerRole())
def get_login_status():
    """ 获取用户登陆状态(前端保存到本地,丢失后再获取) """
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


@blueprint.route('/logout', methods=['POST'])
@roles_required(CustomerRole())
def post_logout():
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND
    customer.is_login = False
    customer.modified_at = datetime.now()
    db.session.commit()
    return jsonify()


@blueprint.route('/contracts', methods=['GET'])
@roles_required(CustomerRole())
def get_contracts():
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND
    if not customer.phone_number or not customer.is_login:
        return jsonify(msg='请登陆后再查看'), HTTPStatus.BAD_REQUEST
    contract_ids = Beneficiary.get_contract_ids(biz_id, c_id, customer.phone_number)
    contracts: List[Contract] = Contract.query.filter(
        Contract.id.in_(contract_ids),
        Contract.is_valid == true()
    ).order_by(desc(Contract.signed_at)).all()
    res = []
    for c in contracts:
        course_ids = c.get_courses()
        res.append({
            "id": c.get_hash_id(),
            "signed_at": c.signed_at.strftime("%m月%d日"),
            "course_names": [CourseCache(course_id).get('brief').get('title') for course_id in course_ids],
            "is_valid": c.is_valid,
            "is_group": c.is_group,
            "created_at": c.created_at
        })

    lessons = get_lesson_profile(customer)
    res.sort(key=lambda x: (x['created_at']))
    return jsonify({
        "contracts": res,
        "lesson": lessons
    })


@blueprint.route('/contracts/<string:c_id>', methods=['GET'])
@roles_required(CustomerRole())
def get_contract(c_id):
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND
    if not customer.is_login:
        return jsonify(msg='请登陆后再查看'), HTTPStatus.BAD_REQUEST

    contract: Contract = Contract.find(c_id)
    if not contract:
        return jsonify(msg='合同不存在'), HTTPStatus.NOT_FOUND

    page = contract.get_page()
    content: List[ContractContent] = ContractContent.query.filter(
        ContractContent.contract_id == contract.id
    ).all()
    for c in content:
        coach_cache = CoachCache(c.coach_id)
        course_cache = CourseCache(c.course_id)
        coach_brief = coach_cache.get('brief')
        course_brief = course_cache.get('brief')
        coach_name = coach_brief.get('name')
        course_name = course_brief.get('title')
        brief = {
            "coach_name": coach_name,
            "course_name": course_name,
            "total": c.total,
            "attended": c.attended,
            "price": c.price,
        }
        if brief not in page['content']:
            page['content'].append(brief)

    return jsonify({
        "contract": page
    })
