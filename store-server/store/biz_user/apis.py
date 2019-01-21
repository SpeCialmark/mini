import json
from flask import Blueprint
from flask import jsonify, request, g, redirect
from http import HTTPStatus
from sqlalchemy import and_
from sqlalchemy.sql.expression import false, true
from datetime import datetime
from store.database import db
from store.domain.middle import roles_required
from store.domain.role import AdminRole, UNDEFINED_BIZ_ID, BizUserRole
from typing import List
import re
import requests
from store.domain.models import BizUser, StoreBiz, BizStaff, ClientInfo
from store.domain.cache import BizUserCache
from store.utils.sms import send_sms_code, verify_sms_code

blueprint = Blueprint('_biz_user', __name__)


@blueprint.route('/admin', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def admin_post_biz_user():
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    phone_number = json_data.get('phone_number')
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    now = datetime.now()
    password = json_data.get('password')

    biz_user: BizUser = BizUser.query.filter(and_(
        BizUser.phone_number == phone_number
    )).first()
    if biz_user:
        return jsonify(msg='该手机号码已被注册'), HTTPStatus.BAD_REQUEST
    else:
        biz_user = BizUser(
            phone_number=phone_number,
            created_at=now)
        biz_user.set_password(password)
        db.session.add(biz_user)
        db.session.commit()

    return jsonify(msg='注册成功')


@blueprint.route('/register', methods=['POST'])
def register():
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    phone_number = json_data.get('phone_number')
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    client_info: ClientInfo = ClientInfo.query.filter(
        ClientInfo.phone_number == phone_number
    ).first()
    if not client_info:
        return jsonify(msg='很抱歉, 尚未开放注册'), HTTPStatus.BAD_REQUEST

    sms_code = json_data.get('sms_code')
    if not sms_code:
        return jsonify(msg='验证码缺失'), HTTPStatus.BAD_REQUEST

    verified, msg = verify_sms_code(phone_number=phone_number, sms_code=sms_code)
    if not verified:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    password = json_data.get('password')
    if not password:
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST
    if len(password) < 7:
        return jsonify(msg='密码过短，请设置位数超过7位'), HTTPStatus.BAD_REQUEST
    if len(password) > 20:
        return jsonify(msg='密码过长，请设置位数小于20位'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    if not name:
        return jsonify(msg='请输入姓名'), HTTPStatus.BAD_REQUEST
    now = datetime.now()

    biz_user: BizUser = BizUser.query.filter(and_(
        BizUser.phone_number == phone_number
    )).first()
    if biz_user:
        return jsonify(msg='该手机号码已被注册'), HTTPStatus.BAD_REQUEST
    else:
        biz_user = BizUser(
            phone_number=phone_number,
            name=name,
            created_at=now)
        biz_user.set_password(password)
        db.session.add(biz_user)
        db.session.commit()

    return jsonify(msg='注册成功')


@blueprint.route('/sms_code', methods=['POST'])
def post_sms_code():
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    phone_number = json_data.get('phone_number')
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST
    send_sms_code(phone_number)
    return jsonify({
        'msg': '短信已发送, 请注意查收.'
    })


@blueprint.route('/login', methods=['POST'])
def post_login():
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    phone_number = json_data.get('phone_number')
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    password = json_data.get('password')
    if not password:
        return jsonify(msg='密码有误'), HTTPStatus.BAD_REQUEST

    biz_user: BizUser = BizUser.query.filter(and_(
        BizUser.phone_number == phone_number
    )).first()  # 有可能是staff

    if not biz_user:
        return jsonify(msg='该手机尚未注册'), HTTPStatus.NOT_FOUND
    else:
        if not biz_user.password_hash:
            # staff
            return jsonify(msg='尚未设置密码, 请先设置密码'), HTTPStatus.BAD_REQUEST
        verified_pwd = biz_user.verify_password(password)
        if not verified_pwd:
            return jsonify(msg='密码有误'), HTTPStatus.BAD_REQUEST

    biz_user_cache = BizUserCache(website='11train', phone_number=phone_number)
    token = biz_user_cache.login()

    return jsonify({
        'token': token,
        'user': {
            'id': biz_user.get_hash_id(),
            'phone_number': phone_number
        },
        'role': BizUserRole.role
    })


@blueprint.route('/reset_pwd', methods=['POST'])
def post_reset_pwd():
    json_data = request.get_json()
    phone_number = json_data.get('phone_number')
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    sms_code = json_data.get('sms_code')
    if not sms_code:
        return jsonify(msg='验证码缺失'), HTTPStatus.BAD_REQUEST

    verified, msg = verify_sms_code(phone_number=phone_number, sms_code=sms_code)
    if not verified:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    password = json_data.get('password')
    if not password:
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST
    if len(password) < 7:
        return jsonify(msg='密码过短，请设置位数超过7位'), HTTPStatus.BAD_REQUEST
    if len(password) > 20:
        return jsonify(msg='密码过长，请设置位数小于20位'), HTTPStatus.BAD_REQUEST

    now = datetime.now()
    biz_user: BizUser = BizUser.query.filter(and_(
        BizUser.phone_number == phone_number
    )).first()

    biz_user.set_password(password)
    biz_user.modified_at = now
    db.session.commit()

    biz_user_cache = BizUserCache(website='11train', phone_number=phone_number)
    biz_user_cache.logout()
    return jsonify(msg='密码已被重置')


@blueprint.route('/mapping', methods=['POST'])
def get_mapping():
    """ 腾讯地图定位接口 """
    json_data = request.get_json()
    address = json_data.get('address')
    url = "https://apis.map.qq.com/ws/geocoder/v1/?address=" + address + "&key=TCABZ-GDD65-SBRIU-Q63GA-OIZ5V-EUBG4"
    r = requests.get(url)
    data = json.loads(r.content)

    return jsonify(data)
