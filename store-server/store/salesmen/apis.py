import io
from datetime import datetime
import base62
import re
from http import HTTPStatus
from typing import List

from flask import Blueprint, send_file
from flask import jsonify, request, g
from sqlalchemy import true, or_, func, false

from store.biz_list.apis import get_actions
from store.database import db
from store.domain.cache import StoreBizCache, AppCache, SalesmanCache, CouponCustomerCache
from store.domain.middle import permission_required, roles_required
from store.domain.models import Salesman, Store, ShareType, Share, Customer, Qrcode, WxAuthorizer, WxOpenUser, \
    CouponReport
from store.domain.permission import ManageSalesmanPermission
from store.domain.role import CustomerRole
from store.domain.wxapp import SalesmanQrcode
from store.salesmen.utils import generate_salesman_poster, AccessType, generate_salesman_share_cover
from store.config import cfg
from store.share.utils import BaseRecord
from store.utils.oss import bucket, encode_app_id
from store.utils.WXBizDataCrypt import WXBizDataCrypt

blueprint = Blueprint('_salesman', __name__)


@blueprint.route('', methods=['GET'])
@permission_required(ManageSalesmanPermission())
def get_salesmen():
    biz_id = g.get('biz_id')
    store_cache = StoreBizCache(biz_id=biz_id)
    customer_app_id = store_cache.get('customer_app_id')
    if not customer_app_id:
        # 不授权则无法生成会籍码因此直接拒绝其添加会籍
        return jsonify(msg='没有授权的小程序'), HTTPStatus.NOT_FOUND
    salesmen: List[Salesman] = Salesman.query.filter(
        Salesman.biz_id == biz_id,
        Salesman.is_official == true(),
    ).order_by().all()
    res = []
    for salesman in salesmen:
        file_name = "salesman_{hid}.jpg".format(hid=salesman.get_hash_id())
        key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=encode_app_id(customer_app_id), file_name=file_name)
        s_exist = bucket.object_exists(key)  # 查看文件是否存在
        if not s_exist:
            qrcode: Qrcode = SalesmanQrcode(app_id=customer_app_id, salesman=salesman).generate()
        else:
            qrcode: Qrcode = SalesmanQrcode(app_id=customer_app_id, salesman=salesman).get()
        brief = salesman.get_brief()
        brief.update({"qrcode": qrcode.get_brief()['url']})
        res.append(brief)
    return jsonify({
        'salesmen': res
    })


@blueprint.route('', methods=['POST'])
@permission_required(ManageSalesmanPermission())
def post_salesman():
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    store_cache = StoreBizCache(biz_id=biz_id)
    customer_app_id = store_cache.get('customer_app_id')
    wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(
        WxAuthorizer.app_id == customer_app_id
    ).first()
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND
    actions = get_actions(wx_authorizer)
    for action in actions:
        if action.get('action') == 'release':
            if action.get('status') != 1:
                return jsonify(msg='小程序尚未发布成功,暂时不能添加会籍'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    avatar = json_data.get('avatar')
    phone_number = json_data.get('phone_number')
    wechat = json_data.get('wechat')
    title = json_data.get('title')
    email = json_data.get('email')

    if not all([name, avatar, phone_number, wechat, title]):
        return jsonify(msg='请将资料填写完整'), HTTPStatus.BAD_REQUEST
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    if email:
        old_salesman: Salesman = Salesman.query.filter(or_(
            Salesman.name == name,
            Salesman.phone_number == phone_number,
            Salesman.wechat == wechat,
            Salesman.email == email
        ),
            Salesman.biz_id == biz_id,
        ).first()
    else:
        # 名字或手机号或微信号被录入过之后不能重复录入
        old_salesman: Salesman = Salesman.query.filter(or_(
            Salesman.name == name,
            Salesman.phone_number == phone_number,
            Salesman.wechat == wechat,
        ),
            Salesman.biz_id == biz_id,
        ).first()
    if old_salesman:
        return jsonify(msg='该会籍已存在'), HTTPStatus.BAD_REQUEST

    salesman = Salesman(
        biz_id=biz_id,
        name=name,
        avatar=avatar,
        phone_number=phone_number,
        wechat=wechat,
        title=title,
        email=email,
        is_official=True,
        created_at=datetime.now()
    )

    db.session.add(salesman)
    db.session.commit()
    db.session.refresh(salesman)

    # 生成小程序码
    SalesmanQrcode(salesman=salesman, app_id=customer_app_id).generate()
    # 同步生成分享记录
    share_type = ShareType.QRCODE.value
    path = str(cfg['codetable']['p'])
    params = 'id={salesman_id}'.format(salesman_id=salesman.get_hash_id())
    s: Share = Share.query.filter(
        Share.biz_id == salesman.biz_id,
        Share.type == share_type,
        Share.path == path,
        Share.params == params,
        Share.shared_salesman_id == salesman.id
    ).first()
    now = datetime.now()
    if not s:
        s = Share(
            biz_id=salesman.biz_id,
            type=share_type,
            path=path,
            params=params,
            shared_salesman_id=salesman.id,
            created_at=now
        )
        db.session.add(s)
        db.session.commit()
        db.session.refresh(s)

    return jsonify(msg='添加成功')


@blueprint.route('/<string:s_id>', methods=['PUT'])
@permission_required(ManageSalesmanPermission())
def put_salesman(s_id):
    salesman: Salesman = Salesman.find(s_id)
    if not salesman:
        return jsonify(msg='会籍不存在'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    avatar = json_data.get('avatar')
    phone_number = json_data.get('phone_number')
    wechat = json_data.get('wechat')
    title = json_data.get('title')
    email = json_data.get('email')

    if name and name != '':
        salesman.name = name
    if avatar and avatar != '':
        salesman.avatar = avatar
    if phone_number and phone_number != '':
        if not phone_number or not re.match('^\d{11}$', phone_number):
            return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST
        salesman.phone_number = phone_number
    if wechat and wechat != '':
        salesman.wechat = wechat
    if title and title != '':
        salesman.title = title
    if email and email != '':
        salesman.email = email

    db.session.commit()
    db.session.refresh(salesman)
    s_cache = SalesmanCache(salesman.id)
    s_cache.reload()

    return jsonify(msg='修改成功')


@blueprint.route('/<string:id>', methods=['GET'])
@roles_required()
def get_salesman(id):
    """
    此页面可以通过扫码进入或者绑定后从首页下部卡片进入或通过分享页面进入
    :param id: 此id通过不同方式访问时会得到不同的值, 需要使用对应的方式进行解析
    :return:
    """
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    access_type = request.args.get('access_type', default=AccessType.Home, type=str)

    if access_type == AccessType.Home:
        # 从首页进入时id为salesman_hid
        is_ok, res = access_from_home(id)
    elif access_type == AccessType.Qrcode:
        # 通过扫码进入id为share_id
        is_ok, res = access_from_qrcode(id)
    elif access_type == AccessType.Share:
        # 通过分享页面进入id为salesman_hid
        s_id = request.args.get('s_id')
        if not s_id:
            return jsonify()
        share_id = base62.decode(s_id)
        is_ok, res = access_from_share(id, customer_id, share_id)
    else:
        return jsonify(msg='类别错误'), HTTPStatus.BAD_REQUEST

    if not is_ok:
        return jsonify(msg=res), HTTPStatus.NOT_FOUND
    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    res.update({"address": store.get_address()})
    return jsonify({
        'salesman': res
    })


@blueprint.route('/<string:s_id>', methods=['DELETE'])
@permission_required(ManageSalesmanPermission())
def delete_salesman(s_id):
    biz_id = g.get('biz_id')
    salesman: Salesman = Salesman.find(s_id)
    if not salesman:
        return jsonify(msg='会籍不存在'), HTTPStatus.NOT_FOUND

    # 查询该会籍绑定的会员
    customers: List[Customer] = Customer.query.filter(
        Customer.biz_id == biz_id,
        or_(
            Customer.salesman_id == salesman.id,
            Customer.belong_salesman_id == salesman.id
        )
    ).all()
    try:
        for customer in customers:
            if customer.belong_salesman_id == salesman.id:
                customer.belong_salesman_id = 0
            if customer.salesman_id == salesman.id:
                customer.salesman_id = 0
        s_cache = SalesmanCache(salesman.id)
        s_cache.delete()
        db.session.delete(salesman)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e
    # TODO 记录处理
    return jsonify(msg='删除成功')


@blueprint.route('/<string:s_id>/poster_info', methods=['GET'])
@roles_required()
def get_poster_info(s_id):
    salesman: Salesman = Salesman.find(s_id)
    if not salesman:
        return jsonify(msg='会籍不存在'), HTTPStatus.NOT_FOUND
    store_cache = StoreBizCache(biz_id=salesman.biz_id)
    store: Store = Store.query.filter(
        Store.biz_id == salesman.biz_id
    ).first()
    if not store:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND

    customer_app_id = store_cache.get('customer_app_id')
    if not customer_app_id:
        return jsonify(msg='没有授权的小程序'), HTTPStatus.NOT_FOUND

    app_cache = AppCache(app_id=customer_app_id)
    store_name = app_cache.get('nick_name')
    address = store.get_address()
    banner = store.cards[0].get('images')[0]
    image = store.cards[1].get('images')[0]
    brief = salesman.get_brief()

    file_name = "salesman_{hid}.jpg".format(hid=salesman.get_hash_id())
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=encode_app_id(customer_app_id), file_name=file_name)
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    exist = bucket.object_exists(key)  # 查看文件是否存在
    if not exist:
        qrcode: Qrcode = SalesmanQrcode(app_id=customer_app_id, salesman=salesman).generate()
        image_url = qrcode.get_brief()['url']

    brief.update({'qrcode': image_url})

    return jsonify({
        'store': {
            'name': store_name,
            'address': address,
            'image': banner or image
        },
        'salesman': brief
    })


@blueprint.route('/<string:s_id>/poster', methods=['GET'])
@roles_required()
def get_poster(s_id):
    salesman: Salesman = Salesman.find(s_id)
    if not salesman:
        return jsonify(msg='会籍不存在'), HTTPStatus.NOT_FOUND
    store_cache = StoreBizCache(biz_id=salesman.biz_id)
    store: Store = Store.query.filter(
        Store.biz_id == salesman.biz_id
    ).first()
    if not store:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND

    customer_app_id = store_cache.get('customer_app_id')
    if not customer_app_id:
        return jsonify(msg='没有授权的小程序'), HTTPStatus.NOT_FOUND

    app_cache = AppCache(app_id=customer_app_id)
    store_name = app_cache.get('nick_name')

    qrcode: Qrcode = SalesmanQrcode(app_id=customer_app_id, salesman=salesman).get()

    poster = generate_salesman_poster(salesman, store, store_name, qrcode)
    poster_bytes = io.BytesIO()
    poster.save(poster_bytes, format='JPEG')
    poster_bytes.seek(0)

    file_name = 'salesman_poster_' + str(salesman.get_hash_id()) + '.jpg'
    res = send_file(poster_bytes, attachment_filename=file_name, mimetype='image/jpeg', as_attachment=true)
    return res


@blueprint.route('/info', methods=['GET'])
@roles_required()
def get_salesman_info():
    # 此接口用于返回客户首页的会籍资料
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND
    salesman_id = customer.belong_salesman_id if customer.belong_salesman_id and customer.belong_salesman_id != 0 else customer.salesman_id
    if salesman_id == 0 or salesman_id is None:
        return jsonify()
    salesman: Salesman = Salesman.query.filter(
        Salesman.id == salesman_id
    ).first()
    if not salesman:
        # 不存在可能是id非法或者会籍已离职
        return jsonify()
    return jsonify({
        'salesman': salesman.get_brief()
    })


@blueprint.route('/customer/phone_number', methods=['POST'])
@roles_required(CustomerRole())
def get_customer_phone_number():
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
    return jsonify({
        'res': res
    })


@blueprint.route('/customer/unread', methods=['GET'])
@roles_required(CustomerRole())
def get_unread_customer():
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
            'unread': 0
        })
    is_read = request.args.get('is_read')  # query参数是str
    cc_cache = CouponCustomerCache(salesman.id)
    if is_read == 'true':
        cc_cache.reload()
        unread = 0
        return jsonify({
            'unread': unread
        })
    last_time = datetime.strptime(cc_cache.get('time'), '%Y.%m.%d %H:%M:%S')
    now = datetime.now()
    unread = len(
        db.session.query(func.count(CouponReport.customer_id), CouponReport.customer_id).filter(
            CouponReport.salesman_id == salesman.id,
            CouponReport.is_used == false(),
            CouponReport.created_at >= last_time,
            CouponReport.created_at <= now,
        ).group_by(CouponReport.customer_id).all())

    return jsonify({
        'unread': unread
    })


@blueprint.route('/share/<string:s_id>', methods=['GET'])
def get_share_cover(s_id):
    # 此接口用于生成转发页面的截图
    salesman: Salesman = Salesman.find(s_id)
    if not salesman:
        return jsonify(msg='会籍不存在'), HTTPStatus.NOT_FOUND
    store_cache = StoreBizCache(biz_id=salesman.biz_id)
    store: Store = Store.query.filter(
        Store.biz_id == salesman.biz_id
    ).first()
    if not store:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND

    customer_app_id = store_cache.get('customer_app_id')
    if not customer_app_id:
        return jsonify(msg='没有授权的小程序'), HTTPStatus.NOT_FOUND

    app_cache = AppCache(app_id=customer_app_id)
    store_name, head_img_url = app_cache.get('nick_name', 'head_img')

    share_cover = generate_salesman_share_cover(salesman, store, store_name, head_img_url)
    share_cover_bytes = io.BytesIO()
    share_cover.save(share_cover_bytes, format='JPEG')
    share_cover_bytes.seek(0)

    file_name = 'share_cover_' + str(salesman.get_hash_id()) + '.jpg'
    res = send_file(share_cover_bytes, attachment_filename=file_name, mimetype='image/jpeg', as_attachment=true)
    return res


def access_from_home(id):
    # 从首页进入时id为salesman_hid
    salesman: Salesman = Salesman.find(id)
    if not salesman:
        return False, '会籍不存在'
    brief = salesman.get_brief()

    store_cache = StoreBizCache(biz_id=salesman.biz_id)
    customer_app_id = store_cache.get('customer_app_id')
    if not customer_app_id:
        return False, '没有授权的小程序'
    app_cache = AppCache(app_id=customer_app_id)
    store_name, head_img = app_cache.get('nick_name', 'head_img')
    brief.update({'store_name': store_name, 'head_img': head_img})
    return True, brief


def access_from_qrcode(id):
    # 通过扫码进入id为share_id
    share_id = base62.decode(id)
    share: Share = Share.query.filter(
        Share.id == share_id
    ).first()
    if not share:
        return False, '无效的二维码'

    params_dict = BaseRecord.get_params_dict(share.params)
    salesman_hid = params_dict.get('id')  # 数值根据生成二维码时定义的字段来获取
    salesman: Salesman = Salesman.find(salesman_hid)
    if not salesman:
        return False, '会籍不存在'

    store_cache = StoreBizCache(biz_id=salesman.biz_id)
    customer_app_id = store_cache.get('customer_app_id')
    app_cache = AppCache(app_id=customer_app_id)
    brief = salesman.get_brief()
    store_name, head_img = app_cache.get('nick_name', 'head_img')
    brief.update({'store_name': store_name, 'head_img': head_img})
    return True, brief


def access_from_share(id, customer_id, share_id):
    # 从分享页面进入id为salesman_hid
    salesman: Salesman = Salesman.find(id)
    if not salesman:
        return False, '会籍不存在'

    # 绑定会员与会籍
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    customer.salesman_id = salesman.id

    # 如果是用户分享了会籍的名片则将此次访客也算入该会籍名下
    share: Share = Share.query.filter(
        Share.id == share_id
    ).first()
    share.shared_salesman_id = salesman.id
    db.session.commit()

    brief = salesman.get_brief()
    store_cache = StoreBizCache(biz_id=salesman.biz_id)
    customer_app_id = store_cache.get('customer_app_id')
    if not customer_app_id:
        return False, '没有授权的小程序'
    app_cache = AppCache(app_id=customer_app_id)
    store_name, head_img = app_cache.get('nick_name', 'head_img')
    brief.update({'store_name': store_name, 'head_img': head_img})

    return True, brief
