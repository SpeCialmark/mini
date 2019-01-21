import sys

import requests
from PIL import ImageDraw, ImageFont, Image
from flask import Blueprint
from flask import jsonify, request, g
from http import HTTPStatus
from datetime import datetime

from store.check_in.apis import save_png_temp_file
from store.config import cfg
from store.database import db
from store.domain.cache import AppCache, StoreBizCache, AppAuditCache
from store.domain.middle import roles_required
from store.domain.role import AdminRole, UNDEFINED_BIZ_ID
from typing import List

from store.utils.oss import encode_app_id, bucket
from store.wxopen import component, release_client, release_agent_id
from store.domain.models import StoreTemplate, WxAuthorizer, Qrcode
from store.domain.wxapp import (
    ActionStatus, CheckInfoAction, SetTemplateAction, SetDbAction, CommitAction, SubmitAction,
    ReleaseAction, AuditAction, CheckInCoverQrcode)


blueprint = Blueprint('_codebase', __name__)


@blueprint.route('/templates', methods=['GET'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def get_templates():
    templates: List[StoreTemplate] = StoreTemplate.query.filter().all()
    result = [template.get_admin_page() for template in templates] if templates else []
    return jsonify({
        'templates': result
    })


@blueprint.route('/templates', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def post_templates():
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    if not name:
        return jsonify(msg='missing name'), HTTPStatus.BAD_REQUEST

    now = datetime.now()
    template: StoreTemplate = StoreTemplate.query.filter(StoreTemplate.name == name).first()
    if not template:
        template = StoreTemplate(
            name=name,
            created_at=now
        )
        db.session.add(template)

    template.title = json_data.get('title')
    template.ext_json_format = json_data.get('ext_json_format')
    template.params_desc = json_data.get('params_desc')
    template.wx_template_id = json_data.get('wx_template_id')
    template.version = json_data.get('version')
    template.description = json_data.get('description')
    template.app_mark = json_data.get('app_mark')  # 新增模板的时候与app_mark关联
    template.modified_at = now
    db.session.commit()
    db.session.refresh(template)
    return jsonify({
        'template': template.get_admin_page()
    })


@blueprint.route('/templates/<int:t_id>', methods=['GET'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def get_template(t_id):
    template: StoreTemplate = StoreTemplate.query.filter(StoreTemplate.id == t_id).first()
    if not template:
        return jsonify(), HTTPStatus.NOT_FOUND
    return jsonify({
        'template': template.get_admin_page()
    })


@blueprint.route('/templates/<int:t_id>', methods=['PUT'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def put_template(t_id):
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    template: StoreTemplate = StoreTemplate.query.filter(StoreTemplate.id == t_id).first()
    if not template:
        return jsonify(), HTTPStatus.NOT_FOUND

    now = datetime.now()
    if 'name' in json_data:
        template.name = json_data.get('name')
    if 'title' in json_data:
        template.title = json_data.get('title')
    if 'ext_json_format' in json_data:
        template.ext_json_format = json_data.get('ext_json_format')
    if 'params_desc' in json_data:
        template.params_desc = json_data.get('params_desc')
    if 'wx_template_id' in json_data:
        template.wx_template_id = json_data.get('wx_template_id')
    if 'version' in json_data:
        template.version = json_data.get('version')
    if 'description' in json_data:
        template.description = json_data.get('description')

    template.modified_at = now
    db.session.commit()
    db.session.refresh(template)
    return jsonify({
        'template': template.get_admin_page()
    })


@blueprint.route('/templates/<int:t_id>', methods=['DELETE'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def delete_template(t_id):
    template: StoreTemplate = StoreTemplate.query.filter(StoreTemplate.id == t_id).first()
    if not template:
        return jsonify(), HTTPStatus.NOT_FOUND

    db.session.delete(template)
    db.session.commit()
    return jsonify()


def get_apps(t_id: int, app_id_str: str, released: int):
    if not app_id_str:
        if released == 1:
            apps: List[WxAuthorizer] = WxAuthorizer.query.filter(
                WxAuthorizer.template_id == t_id,
                WxAuthorizer.release_result.isnot(None)
            ).all()
        else:
            apps: List[WxAuthorizer] = WxAuthorizer.query.filter(
                WxAuthorizer.template_id == t_id).all()
    else:
        app_id_list = app_id_str.split(',')
        if released == 1:
            apps: List[WxAuthorizer] = WxAuthorizer.query.filter(
                WxAuthorizer.template_id == t_id,
                WxAuthorizer.app_id.in_(app_id_list),
                WxAuthorizer.release_result.isnot(None)
            ).all()
        else:
            apps: List[WxAuthorizer] = WxAuthorizer.query.filter(
                WxAuthorizer.template_id == t_id,
                WxAuthorizer.app_id.in_(app_id_list)
            ).all()
    return apps


@blueprint.route('/templates/<int:t_id>/apps', methods=['GET'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def get_template_apps(t_id):
    app_id_str = request.args.get('app_id', default=None, type=str)
    released = request.args.get('released', default=1, type=int)
    apps = get_apps(t_id, app_id_str, released)
    res = [{
        'app_id': app.app_id,
        'nick_name': app.nick_name,
        'release_result': app.release_result
    } for app in apps]
    return jsonify({
        'apps': res
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


@blueprint.route('/templates/<int:t_id>/apps/actions', methods=['GET'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def get_template_apps_actions(t_id):
    app_id_str = request.args.get('app_id', default=None, type=str)
    released = request.args.get('released', default=1, type=int)
    apps = get_apps(t_id, app_id_str, released)
    res = list()
    for app in apps:
        res.append({
            'app_id': app.app_id,
            'nick_name': app.nick_name,
            'actions': get_actions(app)
        })
    return jsonify({
        'apps_actions': res
    })


@blueprint.route('/templates/<int:t_id>/apps/actions/check_info', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def post_template_apps_actions_check_info(t_id):
    app_id_str = request.args.get('app_id', default=None, type=str)
    released = request.args.get('released', default=1, type=int)
    apps = get_apps(t_id, app_id_str, released)
    res = list()
    for app in apps:
        check_info_action = CheckInfoAction(wx_authorizer=app)
        check_info_action.execute()
        res.append({
            'app_id': app.app_id,
            'nick_name': app.nick_name,
            'check_info_action': check_info_action.display
        })
    return jsonify({
        'check_info_actions': res
    })


@blueprint.route('/templates/<int:t_id>/apps/actions/commit', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def post_template_apps_actions_commit(t_id):
    app_id_str = request.args.get('app_id', default=None, type=str)
    released = request.args.get('released', default=1, type=int)
    apps = get_apps(t_id, app_id_str, released)
    res = list()
    for app in apps:
        action = CommitAction(wx_authorizer=app)
        action.execute()
        res.append({
            'app_id': app.app_id,
            'nick_name': app.nick_name,
            'commit_action': action.display
        })
    return jsonify({
        'commit_actions': res
    })


@blueprint.route('/templates/<int:t_id>/apps/actions/submit', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def post_template_apps_actions_submit(t_id):
    app_id_str = request.args.get('app_id', default=None, type=str)
    released = request.args.get('released', default=1, type=int)
    apps = get_apps(t_id, app_id_str, released)
    res = list()
    for app in apps:
        action = SubmitAction(wx_authorizer=app)
        action.execute()
        res.append({
            'app_id': app.app_id,
            'nick_name': app.nick_name,
            'submit_action': action.display
        })
    return jsonify({
        'submit_actions': res
    })


@blueprint.route('/templates/<int:t_id>/apps/actions/undo_code_audit', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def get_undo_code_audit(t_id):
    """ 审核撤回 """
    app_id_str = request.args.get('app_id', default=None, type=str)
    released = request.args.get('released', default=1, type=int)
    apps = get_apps(t_id, app_id_str, released)
    res = list()
    for app in apps:
        client = component.get_client_by_appid(app.app_id)
        access_token = client.access_token
        url = 'https://api.weixin.qq.com/wxa/undocodeaudit?access_token={access_token}'.format(access_token=access_token)
        r = requests.get(url)
        result = r.json()
        errcode = result.get('errcode')
        errmsg = result.get('errmsg')
        if errcode == 0:
            errmsg = '成功'
        elif errcode == -1:
            errmsg = '系统错误'
        elif errcode == 87013:
            errmsg = '撤回次数达到上限'

        res.append({
            'app_id': app.app_id,
            'nick_name': app.nick_name,
            'errmsg': errmsg
        })
        # 发送通知消息
        content = '{nick_name}撤销审核'.format(nick_name=app.nick_name)
        release_client.message.send_text(
            agent_id=release_agent_id,
            party_ids=[cfg['party_id']['wxapp']],
            user_ids=[],
            content=content
        )
        # 关闭审核开关
        app_audit_cache = AppAuditCache(biz_id=app.biz_id)
        app_audit_cache.delete()

    return jsonify({
        'undo_code_audits': res
    })


@blueprint.route('/templates/<int:t_id>/apps/latest_audit_status', methods=['GET'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def get_template_apps_actions_latest_audit_status(t_id):
    app_id_str = request.args.get('app_id', default=None, type=str)
    released = request.args.get('released', default=1, type=int)
    apps = get_apps(t_id, app_id_str, released)
    res = list()
    for app in apps:
        client = component.get_client_by_appid(app.app_id)
        res.append({
            'app_id': app.app_id,
            'nick_name': app.nick_name,
            'latest_audit_status':  client.wxa.get_latest_audit_status()
        })
    return jsonify({
        'latest_audit_status': res
    })


@blueprint.route('/templates/<int:t_id>/apps/qrcode/check_in_cover', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def post_check_in_cover(t_id):
    app_id_str = request.args.get('app_id', default=None, type=str)
    released = request.args.get('released', default=1, type=int)
    apps = get_apps(t_id, app_id_str, released)
    res = list()
    for app in apps:
        qrcode: Qrcode = CheckInCoverQrcode(app_id=app.app_id).generate()
        qr_code_url = qrcode.get_brief()['url']

        qr_code = Image.open(requests.get(qr_code_url, stream=True).raw).convert('RGBA')
        back_ground = Image.open(sys.path[0] + '/res/new_qrcode_back_ground.png').convert("RGBA")

        back_ground = back_ground.resize((back_ground.size[0] * 2, back_ground.size[1] * 2))
        back_ground_size = back_ground.size

        qr_code = qr_code.resize((qr_code.size[0] * 2, qr_code.size[1] * 2))
        qr_code_size = qr_code.size
        qr_code_x = int(round(back_ground_size[0] / 2 - qr_code_size[0] / 2))  # 居中
        qr_code_y = int(round(back_ground_size[1] / 7))

        qr_a = qr_code.split()[3]
        back_ground.paste(qr_code, (qr_code_x, qr_code_y), mask=qr_a)
        back_ground = back_ground.convert(mode='RGBA')

        word_draw = ImageDraw.Draw(back_ground)
        # store_name = '毅力私人健身房毅力私人健身房'  # for test
        if len(app.nick_name) > 10:
            font_size = 180
            str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
            str_x = back_ground.size[0] / 2 - (font_size * len(app.nick_name) / 2)
            str_y = back_ground.size[1] * 0.8
        else:
            font_size = 240
            str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
            str_x = back_ground.size[0] / 2 - (font_size * len(app.nick_name) / 2)
            str_y = back_ground.size[1] * 0.8
        word_draw.text((str_x, str_y), app.nick_name, font=str_font, fill="#202123")

        tmp = save_png_temp_file(back_ground)

        app_hid = encode_app_id(app.app_id)
        file_name = 'check_cover' + '.png'
        key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=app_hid, file_name=file_name)
        bucket.put_object_from_file(key=key, filename=tmp.name)
        image_url = cfg['aliyun_oss']['host'] + '/' + key
        tmp.close()  # 删除临时文件
        res.append(image_url)
    return jsonify({"image_url": res})


@blueprint.route('/templates/<int:t_id>/ext_json', methods=['GET'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def get_ext_json(t_id):
    template: StoreTemplate = StoreTemplate.query.filter(
        StoreTemplate.id == t_id
    ).first()
    if not template:
        return jsonify(msg='模板不存在'), HTTPStatus.NOT_FOUND
    ext_json = template.ext_json_format
    return jsonify({
        'ext_json': ext_json
    })
