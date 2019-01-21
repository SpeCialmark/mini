import json
import sys
import requests
from flask import Blueprint
from flask import jsonify, request, g
from store.biz_list.utils import generate_check_in_cover, generate_release_cover, generate_shake_cover, \
    generate_registration_cover
from store.coaches.apis import add_staff
from store.domain.models import BizUser, StoreBiz, WxAuthorizer, StoreTemplate, BizStaff, Qrcode, Store, \
    ClientInfo, Coach, WxOpenUser, AppMark, Coupon
from store.domain.middle import roles_required, permission_required
from store.domain.permission import (staff_selectable_permissions, ViewBizWebPermission, DeployPermission,
                                     EditStorePermission,
                                     ManagePrivateCoachPermission, ManagePublicCoachPermission,
                                     ManageFeedPermission, EditPrivateCoachPermission, ManageGroupCoursePermission,
                                     get_permission, get_permissions_name, ViewBizPermission,
                                     EditCoachItemPermission, get_all_permission)
from store.domain.role import UNDEFINED_BIZ_ID, BizUserRole, ManagerRole, CoachRole
from http import HTTPStatus
from typing import List
from datetime import datetime
from sqlalchemy import desc, asc, func, and_, true
from store.database import db
from store.wxopen import component
from store.utils.oss import bucket, encode_app_id
import re
from store.config import cfg, get_res, _env
from store.domain.cache import BizUserCache, TokenCache, StoreBizCache, AppCache, WxOpenUserCache, \
    get_default_coach_permission, get_default_staff_permission
from store.domain.wxapp import (
    ActionStatus, CheckInfoAction, SetTemplateAction, SetDbAction, CommitAction, SubmitAction,
    ReleaseAction, AuditAction, CheckInQrcode, CheckInCoverQrcode, ReleaseQrcode, ReleaseCoverQrcode, BetaQrcode,
    RegistrationQrcode)

blueprint = Blueprint('_biz_list', __name__)


def get_brief_biz(store_biz: StoreBiz):
    wx_authorizer_list: List[WxAuthorizer] = WxAuthorizer.query.filter(and_(
        WxAuthorizer.biz_id == store_biz.id
    )).order_by(WxAuthorizer.mark).all()
    app_list = list()
    for app in wx_authorizer_list:
        brief = app.get_brief()
        status = get_status(app)
        brief.update({
            'status': status
        })
        app_list.append(brief)

    return {
        'id': store_biz.get_hash_id(),
        'name': store_biz.name,
        'apps': app_list
    }


def get_status(wx_authorizer: WxAuthorizer):
    release_action = ReleaseAction(wx_authorizer=wx_authorizer)
    if release_action.status == ActionStatus.PASSED:
        return '已上线'
    else:
        return '待上线'


@blueprint.route('', methods=['GET'])
@roles_required()
def get_biz_list():
    biz_user_id = g.biz_user_id
    res = list()
    mine_biz_list: List[StoreBiz] = StoreBiz.query.filter(
        StoreBiz.biz_user_id == biz_user_id
    ).order_by(desc(StoreBiz.created_at)).all()
    for biz in mine_biz_list:
        res.append(get_brief_biz(biz))
    staffs: List[BizStaff] = BizStaff.query.filter(and_(
        BizStaff.biz_user_id == biz_user_id
    )).all()
    for staff in staffs:
        store_biz: StoreBiz = StoreBiz.query.filter(
            StoreBiz.id == staff.biz_id
        ).first()
        if get_brief_biz(store_biz) not in res:
            res.append(get_brief_biz(store_biz))

    return jsonify({
        'biz_list': res
    })


@blueprint.route('', methods=['POST'])
@roles_required()
def post_biz():
    biz_user_id = g.biz_user_id
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST
    name = json_data.get('name')
    if not name:
        return jsonify(msg='门店名字不能为空'), HTTPStatus.BAD_REQUEST
    now = datetime.now()

    try:
        store_biz = StoreBiz(
            biz_user_id=biz_user_id,
            name=name,
            created_at=now
        )
        db.session.add(store_biz)
        db.session.flush()
        db.session.refresh(store_biz)

        biz_data = get_res(directory='store_biz', file_name='store_biz.yml')
        store = Store(
            biz_id=store_biz.id,
            created_at=now
        )
        store_template = biz_data.get('template_name_base')
        store.cards = store_template['store']['cards']
        store.contact = store_template['store']['contact']
        store.modified_at = now
        db.session.add(store)

        coupon = Coupon(
            biz_id=store_biz.id,
            name='体验券',
            description='免费健身1次+私教体测1次',
            created_at=now
        )
        db.session.add(coupon)

        db.session.commit()

        token = request.headers.get('token')
        token_cache = TokenCache(token=token)
        website, phone_number = token_cache.get('website', 'phone_number')
        biz_user_cache = BizUserCache(website=website, phone_number=phone_number)
        biz_user_cache.reload()

    except Exception as e:
        db.session.rollback()
        raise e
    return jsonify({
        'biz': {
            'id': store_biz.get_hash_id(),
            'name': store_biz.name,
            'apps': []
        }
    })


@blueprint.route('/<string:biz_hid>', methods=['GET'])
@permission_required(ViewBizWebPermission())
def get_biz(biz_hid):
    store_biz: StoreBiz = StoreBiz.query.filter(
        StoreBiz.id == g.biz_id
    ).first()
    return jsonify({
        'biz': get_brief_biz(store_biz)
    })


@blueprint.route('/<string:biz_hid>', methods=['DELETE'])
@permission_required(EditStorePermission())
def delete_biz(biz_hid):
    store_biz: StoreBiz = StoreBiz.find(biz_hid)
    if not store_biz:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND

    wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(
        WxAuthorizer.biz_id == store_biz.id
    ).first()
    if wx_authorizer:
        return jsonify(msg='该门店存在有绑定的小程序,无法删除'), HTTPStatus.BAD_REQUEST

    db.session.delete(store_biz)
    db.session.commit()
    return jsonify(msg='删除成功')


@blueprint.route('/<string:biz_hid>', methods=['PUT'])
@permission_required(EditStorePermission())
def put_biz(biz_hid):
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg="missing json data"), HTTPStatus.BAD_REQUEST
    name = json_data.get('name')
    if not name:
        return jsonify(msg='missing name'), HTTPStatus.BAD_REQUEST
    store_biz: StoreBiz = StoreBiz.find(biz_hid)
    if not store_biz:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND
    store_biz.name = name
    db.session.commit()
    return jsonify(msg='修改成功')


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/actions', methods=['GET'])
@permission_required(ViewBizWebPermission())
def get_actions(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    return jsonify({
        'actions': get_actions(wx_authorizer),
        'is_auth': wx_authorizer.is_authorized
    })


def get_actions(wx_authorizer: WxAuthorizer):
    actions = [
        SetTemplateAction(wx_authorizer=wx_authorizer),
        SetDbAction(wx_authorizer=wx_authorizer),
        CheckInfoAction(wx_authorizer=wx_authorizer),
        CommitAction(wx_authorizer=wx_authorizer),
        SubmitAction(wx_authorizer=wx_authorizer),
        AuditAction(wx_authorizer=wx_authorizer),
        ReleaseAction(wx_authorizer=wx_authorizer)
    ]
    result = [action.display for action in actions]
    return result


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/templates', methods=['GET'])
@permission_required(ViewBizWebPermission())
def get_templates(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    app_mark = request.args.get('app_mark', default=None, type=int)
    if not app_mark:
        return jsonify(msg='missing app_mark'), HTTPStatus.BAD_REQUEST

    templates: List[StoreTemplate] = StoreTemplate.query.filter(
        StoreTemplate.app_mark == app_mark
    ).all()
    result = [template.get_brief() for template in templates] if templates else []
    return jsonify({
        'templates': result
    })


# @blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/actions/setting', methods=['POST'])
# @permission_required(DeployPermission())
# def post_setting(biz_hid, app_hid):
#     wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
#     if not wx_authorizer:
#         return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND
#     setting = request.get_json()
#     if not setting:
#         return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
#
#     if 'ext' and 'window' not in setting:
#         return jsonify(msg='key error'), HTTPStatus.BAD_REQUEST
#
#     ext = setting.get('ext')
#     window = setting.get('window')
#     # TODO key
#     wx_authorizer.setting = json.dumps(setting)
#     db.session.commit()
#     return jsonify(msg='模板设置成功')


@blueprint.route('/<string:biz_hid>/settings', methods=['PUT'])
@permission_required(DeployPermission())
def put_biz_settings(biz_hid):
    # TODO is_group_course
    store_biz = StoreBiz.find(biz_hid)
    if not store_biz:
        return jsonify(msg='该门店不存在'), HTTPStatus.NOT_FOUND

    json_date = request.get_json()
    if not json_date:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    settings = json_date.get('settings')
    if not settings:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    store_biz.settings = json.dumps(settings)
    db.session.commit()
    return jsonify(msg='模板设置成功')


@blueprint.route('/<string:biz_hid>/settings', methods=['GET'])
@permission_required(DeployPermission())
def get_biz_settings(biz_hid):
    store_biz = StoreBiz.find(biz_hid)
    if not store_biz:
        return jsonify(msg='该门店不存在'), HTTPStatus.NOT_FOUND

    return jsonify({
        'settings': json.loads(store_biz.settings) if store_biz.settings else []
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/actions/set_template', methods=['POST'])
@permission_required(DeployPermission())
def post_set_template(biz_hid, app_hid):
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    template_id = json_data.get('template_id')
    if not template_id:
        return jsonify(msg='missing template_id'), HTTPStatus.BAD_REQUEST

    set_template_action = SetTemplateAction(wx_authorizer=wx_authorizer)
    set_template_action.execute(template_id=template_id)

    set_db_action = SetDbAction(wx_authorizer=wx_authorizer)
    set_db_action.execute()

    check_info_action = CheckInfoAction(wx_authorizer=wx_authorizer)
    check_info_action.execute()

    if check_info_action.status == ActionStatus.PASSED:
        commit_action = CommitAction(wx_authorizer=wx_authorizer)
        commit_action.execute()

    return jsonify({
        'actions': get_actions(wx_authorizer)
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/actions/reset_template', methods=['POST'])
@permission_required(DeployPermission())
def post_reset_template(biz_hid, app_hid):
    # TODO
    return jsonify()


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/actions/set_db', methods=['POST'])
@permission_required(DeployPermission())
def post_set_db(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    action = SetDbAction(wx_authorizer=wx_authorizer)
    action.execute()
    return jsonify({
        'actions': get_actions(wx_authorizer)
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/actions/check_info', methods=['POST'])
@permission_required(DeployPermission())
def post_check_info(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    action = CheckInfoAction(wx_authorizer=wx_authorizer)
    action.execute()
    return jsonify({
        'actions': get_actions(wx_authorizer)
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/actions/commit', methods=['POST'])
@permission_required(DeployPermission())
def post_commit(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    check_info_action = CheckInfoAction(wx_authorizer=wx_authorizer)
    check_info_action.execute()

    action = CommitAction(wx_authorizer=wx_authorizer)
    action.execute()
    return jsonify({
        'actions': get_actions(wx_authorizer)
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/actions/submit', methods=['POST'])
@permission_required(DeployPermission())
def post_submit(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    check_info_action = CheckInfoAction(wx_authorizer=wx_authorizer)
    check_info_action.execute()

    action = SubmitAction(wx_authorizer=wx_authorizer)
    action.execute()
    return jsonify({
        'actions': get_actions(wx_authorizer)
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/actions/release', methods=['POST'])
@permission_required(DeployPermission())
def post_release(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    release_action = ReleaseAction(wx_authorizer=wx_authorizer)
    release_action.execute()

    return jsonify({
        'actions': get_actions(wx_authorizer)
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/latest_audit_status', methods=['GET'])
@permission_required(ViewBizWebPermission())
def get_biz_latest_audit_status(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    client = component.get_client_by_appid(wx_authorizer.app_id)
    latest_audit_status = client.wxa.get_latest_audit_status()
    return jsonify({
        'latest_audit_status': latest_audit_status
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/info', methods=['GET'])
@permission_required(ViewBizWebPermission())
def get_biz_authorizer_info(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    return jsonify({
        'info': wx_authorizer.get_page()
    })


@blueprint.route('/<string:biz_hid>/qrcodes', methods=['GET'])
@permission_required(ViewBizPermission())
def get_qrcodes(biz_hid):
    store_biz: StoreBiz = StoreBiz.find(biz_hid)
    store_biz_cache = StoreBizCache(store_biz.id)
    customer_app_id = store_biz_cache.get('customer_app_id')
    if not customer_app_id:
        return jsonify(msg='客户端小程序不存在'), HTTPStatus.NOT_FOUND
    res = list()
    app_cache = AppCache(customer_app_id)
    nick_name = app_cache.get('nick_name')

    check_in_images = get_check_in_images(nick_name, customer_app_id)
    res.append(check_in_images)

    release_images = get_release_images(nick_name, customer_app_id)
    res.append(release_images)

    shake_image = get_shake_image(nick_name, customer_app_id)
    res.append(shake_image)

    registration_image = get_registration_cover(customer_app_id)
    res.append(registration_image)
    return jsonify(res)


@blueprint.route('/<string:biz_hid>/qrcodes', methods=['PUT'])
@permission_required(EditStorePermission())
def put_qrcodes(biz_hid):
    store_biz: StoreBiz = StoreBiz.find(biz_hid)
    store_biz_cache = StoreBizCache(store_biz.id)
    customer_app_id = store_biz_cache.get('customer_app_id')
    if not customer_app_id:
        return jsonify(msg='客户端小程序不存在'), HTTPStatus.NOT_FOUND

    app_cache = AppCache(customer_app_id)
    nick_name = app_cache.get('nick_name')

    check_in: Qrcode = CheckInQrcode(app_id=customer_app_id).generate()
    check_in_cover: Qrcode = CheckInCoverQrcode(app_id=customer_app_id).generate()
    release: Qrcode = ReleaseQrcode(app_id=customer_app_id).generate()
    release_cover: Qrcode = ReleaseCoverQrcode(app_id=customer_app_id).generate()
    registration: Qrcode = RegistrationQrcode(app_id=customer_app_id).generate()
    beta: Qrcode = BetaQrcode(app_id=customer_app_id).generate()

    check_in_cover_url = generate_check_in_cover(check_in_cover, nick_name, customer_app_id)
    release_cover_url = generate_release_cover(release_cover, nick_name, customer_app_id)
    shake_cover_url = generate_shake_cover(release_cover, nick_name, customer_app_id)
    registration_cover_url = generate_registration_cover(registration, customer_app_id)
    check_in_url = check_in.get_brief()['url']
    registration_url = registration.get_brief()['url']

    check_in_images = {
        'name': '打卡小程序码',
        'qr_code_cover': check_in_cover_url,
        'qr_code': check_in_url,
    }
    release_url = release.get_brief()['url']
    release_images = {
        'name': "{nick_name}小程序码".format(nick_name=nick_name),
        'qr_code': release_url,
        'qr_code_cover': release_cover_url,
    }

    shake_image = {
        'qr_code_cover': shake_cover_url,
    }

    registration_image = {
        'qr_code': registration_url,
        'qr_code_cover': registration_cover_url
    }

    res = list()
    res.append(check_in_images)
    res.append(release_images)
    res.append(shake_image)
    res.append(registration_image)

    return jsonify(res)


@blueprint.route('/<string:biz_hid>/qrcodes', methods=['POST'])
@permission_required(EditStorePermission())
def post_qrcodes(biz_hid):
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    store_biz: StoreBiz = StoreBiz.find(biz_hid)
    if not store_biz:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    code_type = json_data.get('code_type')
    #  A接口，生成小程序码，可接受path参数较长，生成个数受限。 B接口，生成小程序码，可接受页面参数较短，生成个数不受限。
    if not code_type or code_type not in ['A', 'B']:
        return jsonify(msg='缺失code_type或非法'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    if code_type == 'A':
        path = json_data.get('path')
        if not path:
            return jsonify(msg='缺失path参数'), HTTPStatus.BAD_REQUEST
    else:
        scene = json_data.get('scene')
        if not scene or len(scene) > 32:
            return jsonify(msg='缺失scene参数或长度超过32'), HTTPStatus.BAD_REQUEST
        page = json_data.get('page')
        if not page:
            return jsonify(msg='缺失page参数'), HTTPStatus.BAD_REQUEST

    width = json_data.get('width') or 430
    auto_color = json_data.get('auto_color') or False
    line_color = json_data.get('line_color') or {"r": "0", "g": "0", "b": "0"}

    app_id = store_biz.wx_authorizer.app_id
    client = component.get_client_by_appid(app_id)

    if code_type == 'A':
        r = client.wxa.get_wxa_code(
            path=path,
            width=width,
            auto_color=auto_color,
            line_color=line_color
        )
    else:
        r = client.wxa.get_wxa_code_unlimited(
            scene=scene,
            page=page,
            width=width,
            auto_color=auto_color,
            line_color=line_color,
        )

    if r.status_code != 200:
        return jsonify(msg=r.text), HTTPStatus.BAD_REQUEST

    app_hid = encode_app_id(app_id)
    # dir_format = cfg['qrcode']['dir_format']
    # url_format = cfg['qrcode']['url_format']
    # dir = dir_format.format(app_hid=app_hid)
    # TODO
    # bucket.put_bucket(dir, )


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/qrcodes/check_in', methods=['POST'])
@permission_required(EditStorePermission())
def post_qrcodes_check_in(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    qrcode: Qrcode = CheckInQrcode(app_id=wx_authorizer.app_id).get()
    return jsonify({
        'qrcode': qrcode.get_brief()
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/qrcode/check_in_cover', methods=['GET'])
@permission_required(ViewBizPermission())
def get_qrcodes_check_in_cover(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND

    file_name = 'check_cover' + '.png'
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=encode_app_id(wx_authorizer.app_id), file_name=file_name)
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    return jsonify({
        'check_in_cover': image_url
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/qrcode/check_in_cover', methods=['POST'])
@permission_required(EditStorePermission())
def post_check_in_cover(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND
    customer_app_id = wx_authorizer.app_id
    qrcode: Qrcode = CheckInCoverQrcode(app_id=customer_app_id).generate()
    image_url = generate_check_in_cover(qrcode, wx_authorizer.nick_name, customer_app_id)
    return jsonify({
        "image_url": image_url
    })


@blueprint.route('/<string:biz_hid>/apps/<string:app_hid>/qrcode/release_cover', methods=['POST'])
@permission_required(EditStorePermission())
def post_release_cover(biz_hid, app_hid):
    wx_authorizer: WxAuthorizer = WxAuthorizer.find(app_hid)
    if not wx_authorizer:
        return jsonify(msg='该小程序不存在'), HTTPStatus.NOT_FOUND
    customer_app_id = wx_authorizer.app_id
    qr_code: Qrcode = ReleaseCoverQrcode(app_id=customer_app_id).generate()
    image_url = generate_release_cover(qr_code, wx_authorizer.nick_name, customer_app_id)
    return jsonify({
        'image_url': image_url
    })


@blueprint.route('/staffs', methods=['POST'])
@roles_required(ManagerRole())
def post_staff():
    json_data = request.get_json()
    biz_id = g.get('biz_id')
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    phone_number = json_data.get('phone_number')
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    permission_list = json_data.get('permission_list')
    for p in permission_list:
        if p not in staff_selectable_permissions:
            return jsonify(msg='权限参数有误'), HTTPStatus.BAD_REQUEST

    roles = json_data.get('roles') or list()
    for r in roles:
        if r not in [CoachRole.role]:
            return jsonify(msg='角色参数有误'), HTTPStatus.BAD_REQUEST

    now = datetime.now()
    try:
        biz_user = BizUser.query.filter(
            BizUser.phone_number == phone_number
        ).first()
        if not biz_user:
            biz_user = BizUser(
                phone_number=phone_number,
                created_at=now
            )
            db.session.add(biz_user)
            db.session.flush()
            db.session.refresh(biz_user)
        else:
            staff: BizStaff = BizStaff.query.filter(and_(
                BizStaff.biz_id == biz_id,
                BizStaff.biz_user_id == biz_user.id
            )).first()
            if staff:
                return jsonify(msg='已经添加过该成员'), HTTPStatus.BAD_REQUEST

        permission_list.append(ViewBizPermission.name)
        permission_list.append(ViewBizWebPermission.name)
        staff = BizStaff(
            biz_id=biz_id,
            biz_user_id=biz_user.id,
            name=name,
            roles=roles,
            permission_list=permission_list,
            created_at=now
        )
        db.session.add(staff)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        raise e

    return jsonify(msg='添加成员成功')


@blueprint.route('/staffs', methods=['GET'])
@permission_required(ViewBizWebPermission())
def get_staffs():
    biz_id = g.get('biz_id')
    staffs: List[BizStaff] = BizStaff.query.filter(and_(
        BizStaff.biz_id == biz_id
    )).order_by(asc(BizStaff.created_at)).all()
    staffs = supplement_private_coaches(biz_id, staffs)  # 检测私教是否在staff列表中,如果不在则添加
    res = [s.get_brief() for s in staffs]

    store_biz: StoreBiz = StoreBiz.query.filter(
        StoreBiz.id == biz_id
    ).first()
    biz_user: BizUser = BizUser.query.filter(
        BizUser.id == store_biz.biz_user_id
    ).first()

    permission_list = get_all_permission()  # 管理员的权限列表
    return jsonify({
        'manager': {
            'name': biz_user.name,
            'phone_number': biz_user.phone_number,
            'permission_list': list(set(permission_list)),
        },
        'staffs': res
    })


@blueprint.route('/staffs', methods=['PUT'])
@roles_required(ManagerRole())
def put_staff():
    # 编辑完所有成员之后一起提交
    staffs = request.get_json()  # type: List
    if not staffs:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    biz_id = g.get('biz_id')
    try:
        for s in staffs:
            staff: BizStaff = BizStaff.find(s.get('id'))
            if not staff:
                return jsonify(msg='没有该成员'), HTTPStatus.NOT_FOUND
            permission_list = s.get('permission_list')
            if permission_list:
                for p in permission_list:
                    if p not in staff_selectable_permissions:
                        return jsonify(msg='权限参数有误'), HTTPStatus.BAD_REQUEST
            if staff.roles == [CoachRole.role]:
                coach: Coach = Coach.query.filter(and_(
                    Coach.biz_id == staff.biz_id,
                    Coach.phone_number == staff.biz_user.phone_number,  # old_phone_number
                    Coach.coach_type == 'private'
                )).first()
                # 将私教角色的默认权限添加到权限列表中
                default_coach_permission = get_default_coach_permission(biz_id, coach.id)
                permission_list.extend(get_permissions_name(default_coach_permission, biz_id, coach.id))
                coach.permission_list = permission_list
                staff.permission_list = permission_list
                refresh_token_permissions(biz_id, coach)
            else:
                # 将staff角色的默认权限添加到权限列表中
                default_staff_permission = get_default_staff_permission(biz_id)
                permission_list.extend(get_permissions_name(default_staff_permission, biz_id))
                staff.permission_list = permission_list
            phone_number = s.get('phone_number')
            name = s.get('name')
            if name:
                staff.name = name
            if phone_number:
                if not re.match('^\d{11}$', phone_number):
                    return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST
                # phone_number change
                modify_staff_phone_number(staff, phone_number)
            now = datetime.now()
            staff.modified_at = now
            db.session.commit()
            db.session.refresh(staff)
            biz_user_cache = BizUserCache(website='11train', phone_number=phone_number)
            biz_user_cache.reload()
    except Exception as e:
        db.session.rollback()
        raise e
        # return jsonify(msg='修改出错,请联系客服'), HTTPStatus.BAD_REQUEST

    return jsonify(msg='修改成功')


@blueprint.route('/staffs/<string:s_hid>', methods=['DELETE'])
@roles_required(ManagerRole())
def delete_staff(s_hid):
    biz_id = g.get('biz_id')
    staff: BizStaff = BizStaff.find(s_hid)
    if not staff:
        return jsonify(msg='没有该成员'), HTTPStatus.NOT_FOUND
    # 删除的是私教 -> 离职
    if staff.roles == [CoachRole.role]:
        coach: Coach = Coach.query.filter(and_(
            Coach.biz_id == staff.biz_id,
            Coach.phone_number == staff.biz_user.phone_number,
            Coach.in_service == true()
        )).first()
        coach.in_service = False
        coach.not_in_service_at = datetime.now()
        coach.permission_list = [ViewBizPermission.name]
        store: Store = Store.query.filter(Store.biz_id == biz_id).first()
        store.coach_indexes.remove(coach.id)
        biz_cache = StoreBizCache(biz_id)
        biz_cache.reload()
    db.session.delete(staff)
    db.session.commit()
    return jsonify(msg='成功删除')


@blueprint.route('/<string:biz_hid>/exp_user', methods=['POST'])
@permission_required(DeployPermission())
def post_exp_user(biz_hid):
    store_biz: StoreBiz = StoreBiz.find(biz_hid)
    if not store_biz:
        return jsonify(msg='该门店不存在'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()  # {"wechatid":"testid"}
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(
        WxAuthorizer.biz_id == store_biz.id
    ).first()
    try:
        app_cache = AppCache(wx_authorizer.app_id)
        customer_app_id, coach_app_id = app_cache.get('customer_app_id', 'coach_app_id')
        customer_client = component.get_client_by_appid(customer_app_id)
        coach_client = component.get_client_by_appid(coach_app_id)
        customer_dict = {'client': customer_client, 'nick_name': AppCache(customer_app_id).get('nick_name')}
        coach_dict = {'client': coach_client, 'nick_name': AppCache(coach_app_id).get('nick_name')}
        clients = [customer_dict, coach_dict]

        res = [add_exp_user(client_dict, json_data) for client_dict in clients]

    except Exception as e:
        raise e
    return jsonify(res)


def get_shake_image(nick_name, customer_app_id):
    shake_cover = 'shake_cover.png'
    shake_cover_key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=encode_app_id(customer_app_id), file_name=shake_cover)
    if _env == 'dev':
        shake_cover_key = 'dev/' + shake_cover_key
    shake_cover_url = cfg['aliyun_oss']['host'] + '/' + shake_cover_key
    s_exist = bucket.object_exists(shake_cover_key)  # 查看文件是否存在
    if not s_exist:
        qrcode: Qrcode = ReleaseCoverQrcode(app_id=customer_app_id).get()
        shake_cover_url = generate_shake_cover(qrcode, nick_name, customer_app_id)

    return {
        'name': '摇一摇小程序码',
        'qr_code_cover': shake_cover_url
    }


def get_check_in_images(nick_name, customer_app_id):
    check_cover = 'check_cover' + '.png'
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=encode_app_id(customer_app_id), file_name=check_cover)
    if _env == 'dev':
        key = 'dev/' + key
    check_in_cover_url = cfg['aliyun_oss']['host'] + '/' + key
    exist = bucket.object_exists(key)  # 查看文件是否存在
    if not exist:
        qrcode: Qrcode = CheckInCoverQrcode(app_id=customer_app_id).generate()
        check_in_cover_url = generate_check_in_cover(qrcode, nick_name, customer_app_id)

    check_in: Qrcode = CheckInCoverQrcode(app_id=customer_app_id).get()
    check_in_url = check_in.get_brief()['url']
    check_in_images = {
        'name': '打卡小程序码',
        'qr_code': check_in_url,
        'qr_code_cover': check_in_cover_url
    }
    return check_in_images


def get_release_images(nick_name, customer_app_id):
    release_cover = 'release_cover' + '.png'
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=encode_app_id(customer_app_id), file_name=release_cover)
    qr_code_cover_url = cfg['aliyun_oss']['host'] + '/' + key
    exist = bucket.object_exists(key)
    if not exist:
        qrcode: Qrcode = ReleaseCoverQrcode(app_id=customer_app_id).generate()
        qr_code_cover_url = generate_release_cover(qrcode, nick_name, customer_app_id)

    release: Qrcode = ReleaseQrcode(app_id=customer_app_id).get()
    release_url = release.get_brief()['url']
    release_images = {
        'name': "{nick_name}小程序码".format(nick_name=nick_name),
        'qr_code': release_url,
        'qr_code_cover': qr_code_cover_url,
    }
    return release_images


def get_registration_cover(customer_app_id):
    app_hid = encode_app_id(customer_app_id)
    file_name = 'registration_cover' + '.png'
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=app_hid, file_name=file_name)
    if _env == 'dev':
        key = 'dev/' + key
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    exist = bucket.object_exists(key)  # 查看文件是否存在
    if not exist:
        qrcode: Qrcode = RegistrationQrcode(app_id=customer_app_id).generate()
        image_url = generate_registration_cover(qrcode, customer_app_id)
    else:
        qrcode: Qrcode = RegistrationQrcode(app_id=customer_app_id).get()

    return {
        'name': '前台到店码',
        'qr_code': qrcode.get_brief()['url'],
        'qr_code_cover': image_url
    }


def add_exp_user(client_dict, json_data):
    r = requests.post(
        'https://api.weixin.qq.com/wxa/bind_tester?access_token=' + client_dict.get('client').access_token,
        json=json_data)
    response = r.json()
    errcode = response.get('errcode')
    errmsg = response.get('errmsg')
    nick_name = client_dict.get('nick_name')
    if errcode == 85001:
        errmsg = '微信号不存在或微信号设置为不可搜索'
    elif errcode == 85002:
        errmsg = '小程序绑定的体验者数量达到上限'
    elif errcode == 85003:
        errmsg = '微信号绑定的小程序体验者达到上限'
    elif errcode == 85004:
        errmsg = '微信号已经绑定'
    elif errcode == 0:
        errmsg = '添加体验者成功'

    return {
        'nick_name': nick_name,
        'result': errmsg
    }


def refresh_token_permissions(biz_id, coach):
    wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(and_(
        WxAuthorizer.biz_id == biz_id,
        WxAuthorizer.mark == AppMark.COACH.value
    )).first()

    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.app_id == wx_authorizer.app_id,
        WxOpenUser.coach_id == coach.id
    ).first()
    if not wx_open_user:
        # 说明是全新的用户,还未打开过小程序
        return
    wx_open_user_cache = WxOpenUserCache(app_id=wx_open_user.app_id, open_id=wx_open_user.wx_open_id)
    wx_open_user_cache.reload()  # 更新token中的权限
    return


def modify_staff_phone_number(staff, new_phone_number):
    now = datetime.now()
    try:
        biz_user = BizUser.query.filter(
            BizUser.phone_number == new_phone_number
        ).first()
        if not biz_user:
            # 创建一个新的biz_user
            biz_user = BizUser(
                phone_number=new_phone_number,
                created_at=now
            )
            db.session.add(biz_user)
            db.session.flush()
            db.session.refresh(biz_user)

        if staff.roles == [CoachRole.role]:
            # 查询旧号码关联的coach
            coach: Coach = Coach.query.filter(and_(
                Coach.biz_id == staff.biz_id,
                Coach.phone_number == staff.biz_user.phone_number,
                Coach.coach_type == 'private'
            )).first()
            if coach:
                coach.phone_number = new_phone_number
                coach.modified_at = now

        staff.biz_user_id = biz_user.id
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e
    return


def supplement_private_coaches(biz_id, staffs):
    private_coaches: List[Coach] = Coach.query.filter(and_(
        Coach.biz_id == biz_id,
        Coach.coach_type == 'private',
        Coach.in_service == true()
    )).all()

    staffs_phone_numbers = [staff.biz_user.phone_number for staff in staffs]
    for coach in private_coaches:
        if coach.phone_number not in staffs_phone_numbers:
            coach_staff = add_staff(coach)
            staffs.append(coach_staff)
        else:
            # 如果电话号码一样则把staff的角色升级为私教
            index = staffs_phone_numbers.index(coach.phone_number)
            staff = staffs[index]
            staff.roles = [CoachRole.role]
            if not staff.name:
                staff.name = coach.name
            db.session.commit()
    return staffs
