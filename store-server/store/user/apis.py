from flask import Blueprint
from flask import jsonify, request, g

from store.activities.utils import refresh_group_reports_redis
from store.check_in.apis import RecordUtil
from store.config import cfg, _env
import requests
from http import HTTPStatus
from sqlalchemy import and_, func
from datetime import datetime, timedelta
from store.database import db
from store.diaries.utils import update_diary_body_data
from store.domain.key_data import get_base_data, get_circumference, get_physical_performance, Weight, \
    get_nearest_record
from store.domain.models import Customer, StoreBiz, WxOpenUser, Coach, FormId, WxMessage, Store, ReserveEmail, \
    Registration, GroupReport, GroupMember, Salesman, Activity, ActivityStatus, GroupStatus, CouponReport, BodyData, \
    Diary, Plan, CheckIn
from sqlalchemy.sql.expression import false, true, asc, desc

from store.store.apis import get_diary_tips
from store.utils import time_processing as tp
from store.utils.WXBizDataCrypt import WXBizDataCrypt
from store.utils.pc_push import push_registration_message
from store.domain.wx_push import push_message, send_phone_message
from store.domain.middle import roles_required
from store.domain.role import CustomerRole, AdminRole
import re
from store.notice import send_experience_email
from store.registration.apis import get_mini_salesman
from store.utils.sms import send_sms_code, verify_sms_code
from typing import List
from store.videos.utils import check_video_permission
from store.wxopen import component
from store.domain.cache import TokenCache, CustomerCache, AppCache, WxOpenUserCache, WxOpenUserNotFoundException, \
    StoreBizCache, CustomerUnreadCache, UserGroupReportsCache, CheckInCache
from collections import OrderedDict
import copy
import time
import json
import base64
import hmac
from hashlib import sha1 as sha
from random import randint
from store.cache import lock_redis_store
import redis_lock


blueprint = Blueprint('_user', __name__)
accessKeyId = cfg['aliyun_oss']['access_key']
accessKeySecret = cfg['aliyun_oss']['secret']
host = cfg['aliyun_oss']['host']
expire_time = 30


class SMSIntention:
    ExpReservation = 'exp_reservation'
    ToShop = 'to_shop'
    Coach = 'coach_login'
    Agent = 'agent_login'
    All = [ExpReservation, ToShop, Coach, Agent]


@blueprint.route('/<string:app_id>/head_img', methods=['GET'])
def get_head_img(app_id):
    app_cache = AppCache(app_id=app_id)
    try:
        head_img = app_cache.get('head_img')
        nick_name = app_cache.get('nick_name')
    except KeyError as e:
        return jsonify(msg='该账号异常, 请联系管理员'), HTTPStatus.BAD_REQUEST
    return jsonify({
        "head_img": head_img,
        "nick_name": nick_name
    })


@blueprint.route('/login', methods=['POST'])
def post_component_login():
    p_data = request.get_json()
    code = p_data.get('code')
    app_id = p_data.get('app_id')

    if not code:
        return jsonify(msg='Missing code'), HTTPStatus.BAD_REQUEST
    if not app_id:
        return jsonify(msg='Missing app_id'), HTTPStatus.BAD_REQUEST

    params = {
        'appid': app_id,
        'js_code': code,
        'component_appid': component.component_appid,
        'component_access_token': component.access_token,
        'grant_type': 'authorization_code'
    }
    r = requests.get(cfg['wx_component_jscode2session'], params)
    data = r.json()
    if data.get('errcode'):
        return jsonify(data), HTTPStatus.BAD_REQUEST

    open_id = data.get('openid')
    session_key = data.get('session_key')
    union_id = data.get('unionid')

    if app_id == "wx862c80b960ce0195":
        # for dev
        app_id = 'wx133ad343e54ce87e'

    with redis_lock.Lock(lock_redis_store,
                         '{app_id}-{open_id}'.format(app_id=app_id, open_id=open_id), expire=60, auto_renewal=True):
        try:
            wx_open_user_cache = WxOpenUserCache(app_id=app_id, open_id=open_id)
            token, client_role = wx_open_user_cache.login(session_key)
            return jsonify({
                'token': token,
                'role': client_role,
            })
        except WxOpenUserNotFoundException as e:
            # Cache 不存在
            pass

        now = datetime.now()
        app_cache = AppCache(app_id=app_id)
        try:
            biz_id = app_cache.get('biz_id')
        except KeyError as e:
            return jsonify(msg='该账号异常, 请联系管理员'), HTTPStatus.BAD_REQUEST

        try:
            # 第一次登录，但是由于历史数据库
            # role = CustomerRole.role
            w_user = WxOpenUser(
                wx_open_id=open_id,
                app_id=app_id,
                created_at=now,
                role=CustomerRole.role,
            )
            db.session.add(w_user)
            db.session.flush()
            db.session.refresh(w_user)

            customer = Customer(
                biz_id=biz_id,
                w_id=w_user.id,
                created_at=now
            )
            db.session.add(customer)
            db.session.flush()
            db.session.refresh(customer)

            # w_user.customer_id = customer.id
            # w_user.login_at = now
            #
            # w_user.session_key = session_key
            db.session.commit()
            wx_open_user_cache = WxOpenUserCache(app_id=app_id, open_id=open_id)
            token, client_role = wx_open_user_cache.login_as_customer(customer)
            return jsonify({
                'token': token,
                'role': client_role,
            })
        except Exception as e:
            db.session.rollback()
            raise e


@blueprint.route('/logout', methods=['POST'])
@roles_required()
def post_logout():
    token = request.headers.get('token')
    token_cache = TokenCache(token=token)
    app_id, open_id = token_cache.get('app_id', 'open_id')
    wx_open_user_cache = WxOpenUserCache(app_id=app_id, open_id=open_id)
    wx_open_user_cache.logout()
    return jsonify()


@blueprint.route('/admin_login/<string:phone_number>', methods=['POST'])
def post_admin_login(phone_number):

    admin_phones = cfg['admin_dev_phones']
    if phone_number not in admin_phones:
        return jsonify(), HTTPStatus.FORBIDDEN

    sms_code = send_sms_code(phone_number)
    token_format = '{phone_number}:{sms_code}'
    token = token_format.format(phone_number=phone_number, sms_code=sms_code)
    g_role = {
        0: {
            AdminRole.id_key_str: phone_number
        }
    }
    token_cache = TokenCache(token=token)
    k_v = {
        'admin_role': json.dumps(g_role)
    }
    token_cache.set(k_v)
    return jsonify({
        'token_format': token_format,
        'msg': '短信已发送, 请注意查收.'
    })


@blueprint.route('/sms_code', methods=['POST'])
@roles_required()
def post_sms_code():
    """ TODO 加个intention, 如果是教练端登录, 那么得认证该号码是否被教练端认证 """
    # TODO 场景验证
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


@blueprint.route('/sms_code_new', methods=['POST'])
def post_sms_code_new():
    # TODO time_out
    intention = request.args.get('intention', default=None, type=str)
    if not intention:
        return jsonify(msg='缺少场景值'), HTTPStatus.BAD_REQUEST
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    phone_number = json_data.get('phone_number')
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    if intention not in SMSIntention.All:
        return jsonify(msg='场景值错误'), HTTPStatus.BAD_REQUEST

    if intention == SMSIntention.Coach:
        # 校验该手机号是否是教练
        coach: Coach = Coach.query.filter(
            Coach.phone_number == phone_number,
            Coach.in_service == true()
        ).first()
        if not coach:
            return jsonify(msg='教练不存在'), HTTPStatus.BAD_REQUEST

    send_sms_code(phone_number)
    return jsonify({
        'msg': '短信已发送, 请注意查收.'
    })


@blueprint.route('/phone_login', methods=['POST'])
@roles_required()
def post_login():
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

    token = request.headers.get('token')
    token_cache = TokenCache(token=token)

    app_id, open_id = token_cache.get('app_id', 'open_id')
    wx_open_user_cache = WxOpenUserCache(app_id=app_id, open_id=open_id)
    biz_id, token, client_role = wx_open_user_cache.get('biz_id', 'token', 'client_role')
    coach: Coach = Coach.query.filter(and_(
        Coach.biz_id == biz_id,
        Coach.phone_number == phone_number,
        Coach.in_service == true()  # 只有在职教练才能登陆小助手
    )).first()
    if coach:
        wx_open_user_cache.upgrade_to_coach(coach)
        client_role = 'coach'
    return jsonify({
        'token': token,
        'role': client_role,
    })


@blueprint.route('/info', methods=['PUT'])
@roles_required()
def put_info():
    w_id = g.get('w_id')
    json_data = request.get_json()
    user_info = json_data.get('userInfo')
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    w_user: WxOpenUser = WxOpenUser.query.filter(and_(
        WxOpenUser.id == w_id
    )).first()
    customer_id = w_user.customer_id
    customer: Customer = Customer.query.filter(Customer.id == customer_id).first()

    if not w_user:
        return jsonify(), HTTPStatus.BAD_REQUEST

    wx_info = copy.deepcopy(w_user.wx_info) if w_user.wx_info else dict()
    if 'nickName' in user_info:
        wx_info['nickName'] = user_info['nickName']
        customer.nick_name = user_info['nickName']
    if 'gender' in user_info:
        wx_info['gender'] = user_info['gender']
    if 'city' in user_info:
        wx_info['city'] = user_info['city']
    if 'province' in user_info:
        wx_info['province'] = user_info['province']
    if 'country' in user_info:
        wx_info['country'] = user_info['country']
    if 'avatarUrl' in user_info:
        wx_info['avatarUrl'] = user_info['avatarUrl']
        customer.avatar = user_info['avatarUrl']

    now = datetime.now()
    w_user.wx_info = wx_info
    customer.modified_at = now
    db.session.commit()

    db.session.refresh(w_user)
    db.session.refresh(customer)

    CustomerCache(customer_id=customer_id).reload()
    return jsonify({
        'info': get_customer_info(w_user)
    })


def get_customer_info(w: WxOpenUser):
    info = dict()
    if not w.wx_info:
        return info
    if 'nickName' in w.wx_info:
        info.update({'nickName': w.wx_info['nickName']})
    if 'avatarUrl' in w.wx_info:
        info.update({'avatarUrl': w.wx_info['avatarUrl']})
    if 'gender' in w.wx_info:
        info.update({'gender': w.wx_info['gender']})

    return info


def get_dir(biz_id, folder):
    encode_id = StoreBiz.hash_ids.encode(biz_id)
    return 'store/' + encode_id + '/' + folder + '/'


def get_iso_8601(expire):
    gmt = datetime.fromtimestamp(expire).isoformat()
    gmt += 'Z'
    return gmt


@blueprint.route('/upload_token/<string:folder>', methods=['POST'])
@roles_required()
def upload_token(folder):
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    file_type = json_data.get('file_type')
    if not file_type:
        return jsonify(msg='missing file_type'), HTTPStatus.BAD_REQUEST

    if folder not in ['store', 'coach', 'feed', 'course', 'check_in', 'salesman', 'goods', 'group_active', 'tmp',
                      'diary', 'contract', 'photo_wall']:
        # tmp为用户在分享打卡时自行上传的图片(生命周期为5天)
        return jsonify(msg='unknown folder'), HTTPStatus.BAD_REQUEST

    now = datetime.now()
    biz_hid = StoreBiz.hash_ids.encode(biz_id)
    _dir = cfg['aliyun_oss']['biz_res_dir'].format(biz_hid=biz_hid, folder=folder)
    if _env == 'dev':
        _dir = 'dev/' + _dir
    # _dir = get_dir(biz_id, folder)
    upload_dir = _dir + now.strftime('%Y%m%d%H%M%S%f') + '.' + file_type

    now = int(time.time())
    expire_syncpoint = now + expire_time
    expire = get_iso_8601(expire_syncpoint)
    print('expire=', expire)

    condition_array = []
    array_item = list()
    array_item.append('starts-with')
    array_item.append('$key')
    array_item.append(upload_dir)
    condition_array.append(array_item)
    policy_dict = OrderedDict([('conditions', condition_array), ('expiration', expire)])
    policy = json.dumps(policy_dict).strip()
    print('policy', policy)
    policy_encode = base64.b64encode(policy.encode('UTF-8'))
    print(policy_encode)
    h = hmac.new(accessKeySecret.encode('UTF-8'), policy_encode, sha)
    sign_result = base64.encodebytes(h.digest()).strip()

    # callback_dict = {}
    # callback_dict['callbackUrl'] = callback_url
    # callback_dict['callbackBody'] =
    # 'filename=${object}&size=${size}&mimeType=${mimeType}&height=${imageInfo.height}&width=${imageInfo.width}'
    # callback_dict['callbackBodyType'] = 'application/x-www-form-urlencoded'
    # callback_param = json.dumps(callback_dict).strip()
    # base64_callback_body = base64.b64encode(callback_param)

    token_dict = dict()
    token_dict['accessid'] = accessKeyId
    token_dict['host'] = host
    token_dict['policy'] = policy_encode.decode('UTF-8')
    token_dict['signature'] = sign_result.decode('UTF-8')
    token_dict['expire'] = expire_syncpoint
    token_dict['dir'] = upload_dir
    # token_dict['callback'] = base64_callback_body
    # web.header("Access-Control-Allow-Methods","POST")
    # web.header("Access-Control-Allow-Origin","*")
    # web.header('Content-Type', 'text/html; charset=UTF-8')
    # result = json.dumps(token_dict)
    return jsonify(token_dict)


@blueprint.route('/upload_video', methods=['POST'])
@roles_required()
def upload_video_token():
    biz_id = g.get('biz_id')
    permissions = g.get('permission')
    # 根据需要上传的视频类别分别校验权限
    is_ok, msg = check_video_permission(biz_id, permissions)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    secret_id = cfg['tencent_video']['secret_id']
    secret_key = cfg['tencent_video']['secret_key']

    current = int(time.time())
    expired = current + 60 * 10  # 十分钟有效期
    random = randint(1, pow(2, 32))

    original = 'secretId={}&currentTimeStamp={}&expireTime={}&procedure=QCVB_SimpleProcessFile(0, 0, 10)&random={}'.format(
        secret_id, current, expired, random)

    h = hmac.new(secret_key.encode('utf-8'), original.encode('utf-8'), sha)
    signature = base64.b64encode(h.digest() + bytes(original, 'utf-8')).decode('utf-8')
    return jsonify({
        'signature': signature,
    })


@blueprint.route('/video_name', methods=['GET'])
@roles_required()
def get_video_name():
    biz_id = g.get('biz_id')

    video_name = 'b{biz_id}_'.format(biz_id=biz_id) + datetime.strftime(datetime.today(), '%Y%m%d_%H%M%S')
    if _env == 'dev':
        video_name = 'dev_' + video_name

    return jsonify({
        'video_name': video_name
    })


@blueprint.route('/info', methods=['POST'])
@roles_required()
def post_user_info():
    # 获取用户信息
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    json_date = request.get_json()
    user_info = json_date['userInfo']

    if not user_info:
        return jsonify(msg='userInfo不存在'), HTTPStatus.BAD_REQUEST
    # 保存头像和昵称
    avatar = user_info['avatarUrl']
    nick_name = user_info['nickName']
    now = datetime.now()

    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.id == w_id,
    ).first()

    customer_id = wx_open_user.customer_id
    customer: Customer = Customer.query.filter(Customer.id == customer_id).first()
    if not customer:
        customer = Customer(
            biz_id=biz_id,
            w_id=w_id,
            avatar=avatar,
            nick_name=nick_name,
            created_at=now,
        )
        db.session.add(customer)
        db.session.commit()
        db.session.refresh(customer)
    else:
        customer.avatar = avatar
        customer.nick_name = nick_name
        customer.biz_id = biz_id
        customer.modified_at = now
        db.session.commit()
        db.session.refresh(customer)

    CustomerCache(customer_id=customer_id).reload()

    print('-----------------------------')
    print(json_date)
    return jsonify(json_date)


@blueprint.route('/form_ids', methods=['POST'])
@roles_required()
def post_form_id():
    w_id = g.get('w_id')
    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.id == w_id
    ).first()
    open_id = wx_open_user.wx_open_id
    app_id = wx_open_user.app_id
    form_id = request.get_json().get('formId')
    now = int(time.time())
    expire_at = now + (60*60*24*7)

    f = FormId(
        form_id=form_id,
        open_id=open_id,
        app_id=app_id,
        expire_at=expire_at,
        created_at=datetime.now()
    )
    db.session.add(f)
    db.session.commit()

    send_messages(wx_open_user)

    return jsonify()


@blueprint.route('/experience', methods=['POST'])
@roles_required(CustomerRole())
def post_experience_new():
    """ 预约到店 """
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    store_cache = StoreBizCache(biz_id)
    customer_app_id = store_cache.get('customer_app_id')
    app_cache = AppCache(customer_app_id)
    store_name = app_cache.get('nick_name')

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    exp_date = json_data.get('day')
    exp_time = json_data.get('time')
    name = json_data.get('name')
    phone_number = json_data.get('phone_number')
    sms_code = json_data.get('sms_code')

    if not sms_code:
        return jsonify(msg='验证码缺失'), HTTPStatus.BAD_REQUEST
    verified, msg = verify_sms_code(phone_number=phone_number, sms_code=sms_code)
    if not verified:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST
    if not all([exp_date, exp_time, name]):
        return jsonify(msg='missing data'), HTTPStatus.BAD_REQUEST

    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    notice_title = '到店预约提醒'
    text = '您好，{store_name}有新的到店预约\n\n时间  {exp_date} {exp_time}\n名字  {name}\n手机  {phone_number}\n\n请您尽快与客户取得联系！'.format(
        store_name=store_name, exp_date=exp_date, exp_time=exp_time, name=name, phone_number=phone_number
    )
    # 发送邮件
    recipient = store.emails
    if not recipient:
        return jsonify(msg='很抱歉,线上预约失败,请您直接联系前台完成预约'), HTTPStatus.BAD_REQUEST
    send_experience_email(subject=notice_title, text=text, recipient=recipient)

    # 保存数据
    is_ok, msg = save_exp_data(biz_id, customer_id, json_data)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    return jsonify(msg=msg)


@blueprint.route('/experience/brief', methods=['GET'])
@roles_required()
def get_experience_brief_new():
    biz_id = g.get('biz_id')
    store_cache = StoreBizCache(biz_id)
    begin, end, customer_app_id = store_cache.get('business_hours_begin', 'business_hours_end', 'customer_app_id')
    app_cache = AppCache(customer_app_id)
    store_name = app_cache.get('nick_name')
    now = datetime.now()
    hhmm = now.hour * 60 + 59
    days = list()
    times = list()
    today_times = list()  # 今日的可选时间
    for i in range(0, 7):
        if i == 0:
            date_str = '今天'
        elif i == 1:
            date_str = '明天'
        else:
            date_str = now.strftime('%-m月%-d日')
        days.append({
            'date_str': date_str,
            'date': now.strftime('%Y.%m.%d')
        })
        now += timedelta(days=1)

    while begin <= end:
        hh = int(begin / 60)
        start = "{:02d}:{:02d}".format(hh, 0)
        if begin > hhmm:
            today_times.append(start)
        times.append(start)
        begin += 60
    return jsonify({
        "store_name": store_name,
        "days": days,
        "times": times,
        'today_times': today_times
    })


@blueprint.route('/activities', methods=['GET'])
@roles_required(CustomerRole())
def get_customer_activity():
    """ 用户在"我"的页面点击"我的活动" """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND

    # 与我有关的所有的团
    all_groups: List[GroupMember] = GroupMember.query.filter(
        GroupMember.biz_id == biz_id,
        GroupMember.customer_id == c_id,
    ).all()
    # 我参与的
    participated = [group.group_report.get_brief() for group in all_groups if group.group_report.leader_cid != c_id]
    # 我发起的
    initiated = [group.group_report.get_brief() for group in all_groups if group.group_report.leader_cid == c_id]

    return jsonify({
        'participated': participated,
        'initiated': initiated,
    })


@blueprint.route('/phone_number', methods=['POST'])
@roles_required(CustomerRole())
def get_phone_number():
    # TODO 授权手机号码接口,v11.5之后的版本统一使用此接口
    """ 获取用户的绑定手机号码 """
    w_id = g.get('w_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    encrypted_data = json_data.get('encryptedData')
    iv = json_data.get('iv')
    if not all([encrypted_data, iv]):
        return jsonify(msg='数据不全'), HTTPStatus.BAD_REQUEST

    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.id == w_id
    ).first()
    if not wx_open_user:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

    pc = WXBizDataCrypt(wx_open_user.app_id, wx_open_user.session_key)
    res = pc.decrypt(encrypted_data, iv)
    return jsonify(res)


@blueprint.route('/activities/group_reports', methods=['GET'])
@roles_required(CustomerRole())
def get_activities():
    """ 获取活动拼团列表 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND

    if not customer.is_login:
        return jsonify(msg='尚未登录'), HTTPStatus.BAD_REQUEST

    salesman: Salesman = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.phone_number == customer.phone_number
    ).first()
    if salesman:
        group_members: List[GroupMember] = GroupMember.query.filter(
            GroupMember.biz_id == biz_id,
            GroupMember.customer_id == c_id,
        ).order_by(desc(GroupMember.created_at)).all()

        activities: List[Activity] = Activity.query.filter(
            Activity.biz_id == biz_id,
            Activity.status == ActivityStatus.ACTION.value
        ).all()
        res = []
        for activity in activities:
            brief = {
                'activity_id': activity.get_hash_id(),
                'title': activity.name,
                'cover_image': activity.cover_image,
                'end_date': activity.end_date.strftime('%Y-%m-%d'),
                'join_count': activity.get_join_count(),
                'has_report': False,
                'group_report_id': None
            }
            for member in group_members:
                if member.group_report.activity_id == activity.id:
                    # 或该用户参加的该活动中还有未结束的团,则不能继续开启新的同种活动的拼团
                    if member.group_report.status == GroupStatus.STANDBY.value or member.group_report.status == GroupStatus.SUCCESS.value:
                        brief.update({
                            'has_report': True,
                            'group_report_id': member.group_report.get_hash_id()
                        })
            res.append(brief)
        return jsonify({
            "group_activities": res
        })

    group_members: List[GroupMember] = GroupMember.query.filter(
        GroupMember.biz_id == biz_id,
        GroupMember.customer_id == c_id
    ).order_by(desc(GroupMember.created_at)).all()

    group_activities = [member.group_report.get_brief() for member in group_members]

    return jsonify({
        "group_activities": group_activities
    })


@blueprint.route('/group_reports', methods=['GET'])
@roles_required(CustomerRole())
def get_group_reports():
    """ 获取自己的拼团信息 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND

    user_group_reports_cache = UserGroupReportsCache(c_id)
    all_reports = refresh_group_reports_redis(user_group_reports_cache)

    return jsonify({
        "all_reports": all_reports,  # 全部
    })


@blueprint.route('/customers', methods=['GET'])
@roles_required(CustomerRole())
def get_customer():
    """ 会籍获取客户列表(根据type来分别获取) """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

    salesman: Salesman = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.phone_number == customer.phone_number
    ).first()
    if not salesman:
        return jsonify({
            'customers': []
        })

    customer_type = request.args.get('type', default=None)
    if customer_type not in CustomerType.AllType:
        return jsonify({
            'customers': []
        })

    if customer_type == CustomerType.Group:
        group_reports: List[GroupReport] = GroupReport.query.filter(
            GroupReport.biz_id == biz_id,
            GroupReport.leader_cid == c_id
        ).order_by(desc(GroupReport.created_at)).all()
        customers = []
        for report in group_reports:
            for member in report.group_members:
                if c_id == member.get('c_id'):
                    # 在参团客户中将自己去掉
                    continue
                # 添加拼团标题作为标示,不进行去重
                member.update({'title': report.activity.name})
                customers.append(member)
        customers.sort(key=lambda x: (x['created_at']), reverse=True)
        return jsonify({
            'customers': customers
        })

    elif customer_type == CustomerType.Coupon:

        customers = []
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
                'received_date': c_report.created_at.strftime("%Y-%m-%d"),  # 领取时间
                'title': c_report.coupon.name
            }
            customers.append(c_brief)

        return jsonify({
            'customers': customers
        })

    elif customer_type == CustomerType.Registration:
        customers = []
        registrations: List[Registration] = Registration.query.filter(
            Registration.biz_id == biz_id,
            Registration.belong_salesman_id == salesman.id,
            Registration.is_arrived == true()
        ).order_by(desc(Registration.arrived_at)).all()
        for r in registrations:
            brief = {
                'name': r.name,
                'phone_number': r.phone_number
            }
            if brief not in customers:
                customers.append(brief)

        return jsonify({
            'customers': customers
        })

    else:
        return jsonify({
            'customers': []
        })


class CustomerType:
    Registration = 'registration'
    Coupon = 'coupon'
    Group = 'group'  # 拼团用户
    All = 'all'
    AllType = [Registration, Coupon, Group, All]


@blueprint.route('/customer/unread', methods=['GET'])
@roles_required(CustomerRole())
def get_customer_unread():
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

    salesman: Salesman = Salesman.query.filter(
        Salesman.phone_number == customer.phone_number
    ).first()
    if not salesman:
        return jsonify({
            'coupon': 0,
            'registration': 0,
            'group': 0,
        })
    is_read = request.args.get('is_read')  # query参数是str
    read_customer_type = request.args.get('type', default='all', type=str)

    if read_customer_type not in CustomerType.AllType:
        return jsonify({
            'coupon': 0,
            'registration': 0,
            'group': 0,
        })

    unread_cache = CustomerUnreadCache(salesman.id)
    if is_read == 'true':
        unread_cache.reload(read_customer_type)
        if read_customer_type == CustomerType.Coupon:
            return jsonify({
                'coupon': 0,
            })
        elif read_customer_type == CustomerType.Group:
            return jsonify({
                'group': 0,
            })
        elif read_customer_type == CustomerType.Registration:
            return jsonify({
                'registration': 0,
            })

    unread = {
        'coupon': 0,
        'registration': 0,
        'group': 0,
    }
    for customer_type in CustomerType.AllType:
        if customer_type == CustomerType.Coupon:
            last_time = datetime.strptime(unread_cache.get('coupon_time'), '%Y.%m.%d %H:%M:%S')
            now = datetime.now()
            coupon_unread = len(
                db.session.query(CouponReport.customer_id).filter(
                    CouponReport.salesman_id == salesman.id,
                    CouponReport.is_used == false(),
                    CouponReport.created_at >= last_time,
                    CouponReport.created_at <= now,
                ).group_by(CouponReport.customer_id).all())

            unread.update({
                'coupon': coupon_unread
            })

        elif customer_type == CustomerType.Registration:
            last_time = datetime.strptime(unread_cache.get('registration_time'), '%Y.%m.%d %H:%M:%S')
            now = datetime.now()
            registration_unread = len(
                db.session.query(Registration.name).filter(
                    Registration.belong_salesman_id == salesman.id,
                    Registration.created_at >= last_time,
                    Registration.created_at <= now,
                ).group_by(Registration.name).all())

            unread.update({
                'registration': registration_unread
            })

        elif customer_type == CustomerType.Group:
            last_time = datetime.strptime(unread_cache.get('group_time'), '%Y.%m.%d %H:%M:%S')
            now = datetime.now()
            group_unread = len(
                db.session.query(GroupMember.customer_id).filter(
                    GroupReport.leader_cid == customer_id,
                    GroupMember.customer_id != customer_id,
                    GroupMember.created_at >= last_time,
                    GroupMember.created_at <= now,
                ).group_by(GroupMember.customer_id).all())

            unread.update({
                'group': group_unread
            })
    return jsonify(unread)


@blueprint.route('/base_info', methods=['POST'])
@roles_required(CustomerRole())
def post_base_info():
    """ 用户录入基本信息 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    birthday = json_data.get('birthday')
    gender = json_data.get('gender')
    height = json_data.get('height')
    if not all([birthday, str(gender), height]):
        return jsonify(msg='请将信息填写完毕'), HTTPStatus.BAD_REQUEST

    try:
        customer.birthday = birthday
        customer.gender = gender
        customer.height = height
    except Exception as e:
        db.session.rollback()
        return jsonify(msg='录入初始数据失败')

    customer_cache = CustomerCache(c_id)
    customer_cache.reload()
    return jsonify()


@blueprint.route('/base_info', methods=['GET'])
@roles_required(CustomerRole())
def get_base_info():
    """ 获取用户基本信息 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND
    return jsonify({
        'base_info': customer.get_base_info(),
    })


@blueprint.route('/record', methods=['PUT'])
@roles_required(CustomerRole())
def put_record():
    """ 修改记录数据 """
    # 每次用户点击添加纪录时可以进行添加(支持单个添加)
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND
    record = request.get_json()
    if not record:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    today = datetime.today()
    records = request.get_json()  # [{'data': 45.5, 'name': '体重'}]
    try:
        for record in records:
            record_type = record.get('name')
            data = record.get('data')
            body_data = BodyData(
                biz_id=biz_id,
                customer_id=c_id,
                record_type=record_type,
                data=data,
                recorded_at=today
            )
            db.session.add(body_data)
            db.session.commit()

        diary: Diary = Diary.query.filter(
            Diary.customer_id == c_id,
            Diary.recorded_at == tp.get_day_min(today),
        ).first()
        if not diary:
            diary = Diary(
                biz_id=biz_id,
                customer_id=c_id,
                recorded_at=tp.get_day_min(today),
                created_at=datetime.now()
            )
            db.session.add(diary)
            db.session.flush()
            db.session.refresh(diary)
        # 更新日记中的体测数据
        update_diary_body_data(diary, records)
    except Exception as e:
        db.session.rollback()
        return jsonify(msg='修改数据失败'), HTTPStatus.BAD_REQUEST

    customer_cache = CustomerCache(c_id)
    customer_cache.reload()
    return jsonify()


@blueprint.route('/record', methods=['GET'])
@roles_required(CustomerRole())
def get_record():
    """ 获取我的健康详细数据 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

    base_data = get_base_data()
    circumference = get_circumference()
    physical_performance = get_physical_performance()

    res = []
    b_res = []
    c_res = []
    p_res = []
    s_res = []

    plan = Plan.get_effective_plan(c_id)
    nearest_record = get_nearest_record(c_id, plan)
    for r in nearest_record:
        if r.get('name') in base_data.get('names'):
            b_res.append(r)
        elif r.get('name') in circumference.get('names'):
            c_res.append(r)
        elif r.get('name') in physical_performance.get('names'):
            p_res.append(r)
        else:
            s_res.append(r)

    res.append({
        'type': '基础数据',
        'res': b_res
    })
    res.append({
        'type': '围度',
        'res': c_res
    })
    res.append({
        'type': '体能成绩',
        'res': p_res
    })
    res.append({
        'type': '自定义指标',
        'res': s_res
    })
    return jsonify(res)


@blueprint.route('/decrypt_step_count', methods=['POST'])
@roles_required(CustomerRole())
def decrypt_step_count():
    """ 解密并更新步数数据 """
    # TODO 解密失败流程
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND
    w_id = g.get('w_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    encrypted_data = json_data.get('encryptedData')
    iv = json_data.get('iv')
    if not all([encrypted_data, iv]):
        return jsonify(msg='数据不全'), HTTPStatus.BAD_REQUEST

    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.id == w_id
    ).first()
    if not wx_open_user:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

    # 解密步数数据
    pc = WXBizDataCrypt(wx_open_user.app_id, wx_open_user.session_key)
    res = pc.decrypt(encrypted_data, iv)

    all_steps = res['stepInfoList']
    # 新的30条步数数据(从今天往前数30天)
    newest_steps = list()
    for newest_step in all_steps:
        timestamp = newest_step.get('timestamp')
        step = newest_step.get('step')
        newest_step_brief = {
            'step': step,
            'date': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        }
        newest_steps.append(newest_step_brief)
    last_step_count = customer.step_count[-1] if customer.step_count else None
    if last_step_count == newest_steps[-1]:
        return jsonify(res)
    customer.step_count = newest_steps
    db.session.commit()
    db.session.refresh(customer)
    CustomerCache(c_id).reload()

    # 更新完毕后将解密的数据返还给前端
    return jsonify(res)


@blueprint.route('/personal_card', methods=['GET'])
@roles_required(CustomerRole())
def get_personal_card():
    """ 我的页面中的个人卡片 """
    biz_id = g.get('biz_id')
    app_id = g.get('app_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    app_cache = AppCache(app_id)
    app_img = app_cache.get('head_img')

    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()


    today_min = tp.get_day_min(datetime.today())
    today_max = tp.get_day_max(datetime.today())
    # 查询是否打卡
    check_in: CheckIn = CheckIn.query.filter(
        CheckIn.biz_id == biz_id,
        CheckIn.customer_id == c_id,
        CheckIn.created_at >= today_min,
        CheckIn.created_at <= today_max
    ).first()
    record_util = RecordUtil(biz_id, c_id)
    check_in_sum = record_util.get_sum_record()
    month_sum = record_util.get_month_sum(today_min)
    check_in_cache = CheckInCache(biz_id)
    avatars = check_in_cache.get_avatars(customer_id=c_id)
    check_in_count = db.session.query(func.count(CheckIn.customer_id)).filter(
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= today_min,
        CheckIn.check_in_date <= today_max
    ).scalar()
    return jsonify({
        "avatar": customer.avatar,
        "app_img": app_img,
        "check_in": {
            "id": check_in.get_hash_id() if check_in else None,
            "month_sum": month_sum,
            "sum": check_in_sum
        },
        "fitness": avatars[:7],
        "check_in_count": check_in_count
    })


def save_exp_data(biz_id, customer_id, exp_data):
    reservation_date = exp_data.get('day')
    if reservation_date == '今天':
        reservation_date = datetime.today()
    elif reservation_date == '明天':
        reservation_date = datetime.today() + timedelta(days=1)
    else:
        reservation_date = datetime.strptime(reservation_date, '%Y.%m.%d')
    exp_time = exp_data.get('time')
    hh = int(exp_time[:2])
    mm = int(exp_time[3:])
    name = exp_data.get('name')
    phone_number = exp_data.get('phone_number')

    r = Registration(
        biz_id=biz_id,
        name=name,
        phone_number=phone_number,
        reservation_date=reservation_date,
        reservation_time=hh*60 + mm,
        created_at=datetime.now()
    )
    r_email = ReserveEmail(
        biz_id=biz_id,
        name=name,
        phone_number=phone_number,
        exp_date=reservation_date,
        exp_time=hh*60 + mm,
        created_at=datetime.now()
    )
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    salesman_id = customer.belong_salesman_id if customer.belong_salesman_id and customer.belong_salesman_id != 0 else customer.salesman_id
    if salesman_id and salesman_id != 0:
        r.mini_salesman_id = salesman_id
    try:
        db.session.add(r)
        db.session.add(r_email)
        db.session.commit()
        db.session.refresh(r)
        brief = r.get_brief()
        brief.update({'mini_salesman_name': get_mini_salesman(r)})
        push_registration_message(brief, StoreBiz.encode_id(biz_id))  # 推送前台
    except Exception as e:
        db.session.rollback()
        return False, '很抱歉,线上预约失败,请您直接联系前台完成预约'

    return True, '预约成功'


def send_messages(wx_open_user):
    """
    发送消息
    :param wx_open_user: 接收者
    :return:
    """
    # 查询是否有等待中任务
    wx_messages: List[WxMessage] = WxMessage.query.filter(and_(
        WxMessage.open_id == wx_open_user.wx_open_id,
        WxMessage.is_completed == false(),
    )).order_by(asc(WxMessage.publish_at)).all()

    if not wx_messages:
        return
    # 有任务
    fs = filter_form_ids(wx_open_user)
    if not fs:
        # 发送短信到用户手机
        for wx_message in wx_messages:
            send_phone_message(wx_message)
        return

    for wx_message in wx_messages:
        while fs:
            f = fs.pop()    # 由于是倒序, 最后一条是时间最早的
            # 提取form_id进行消息发送
            # 发送成功后将form_id移除列表,并结束对该次信息的循环
            # 发送失败时一直向下提取form_id进行发送直到成功为止
            data = wx_message.data
            result = push_message(wx_message, data, f)
            errcode = result.get('errcode')
            errmsg = result.get('errmsg')
            if errcode == 0:
                break
            elif errcode == 41028:
                # form_id不正确，或者过期
                continue
            elif errcode == 41029:
                # form_id已被使用
                continue
            else:
                # 不是form_id的错误
                raise Exception(errmsg)


def filter_form_ids(wx_open_user) -> List[FormId]:
    """ 注意是倒序 """
    now = time.time()

    FormId.query.filter(FormId.form_id == "the formId is a mock one").delete()  # 删除开发工具模拟的form_id
    FormId.query.filter(FormId.expire_at <= now).delete()  # 删除过期的form_id
    db.session.commit()

    fs: List[FormId] = FormId.query.filter(and_(
        FormId.app_id == wx_open_user.app_id,
        FormId.open_id == wx_open_user.wx_open_id,
    )).order_by(desc(FormId.expire_at)).all()

    return fs
