from typing import List

from flask import Blueprint, abort
from sqlalchemy import null

from store.config import cfg
from flask import jsonify, request, g, redirect
from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.exceptions import InvalidSignatureException
from wechatpy.enterprise.exceptions import InvalidCorpIdException
from wechatpy.enterprise import parse_message, create_reply
from store.cache import audit_redis_store
from store.domain.models import WxAuthorizer
from store.domain.wxapp import ReleaseAction
from store.domain.cache import AppAuditCache
from store.wxopen import component
from wechatpy.exceptions import WeChatClientException
import requests


blueprint = Blueprint('_robot', __name__)


@blueprint.route('/health', methods=['GET'])
def health():
    return jsonify(msg='Hello 11train!')


def get_release_agent_crypto():
    token = cfg['wxapp_release_agent']['token']
    aes_key = cfg['wxapp_release_agent']['encodingAESKey']
    corp_id = cfg['corp_id']
    return WeChatCrypto(token, aes_key, corp_id)


@blueprint.route('/release', methods=['GET'])
def get_release_agent():
    signature = request.args.get('msg_signature', '')
    timestamp = request.args.get('timestamp', '')
    nonce = request.args.get('nonce', '')
    echo_str = request.args.get('echostr', '')

    crypto = get_release_agent_crypto()
    try:
        echo_str = crypto.check_signature(
            signature,
            timestamp,
            nonce,
            echo_str
        )
    except InvalidSignatureException:
        abort(403)
    return echo_str


def get_all_app():
    res = ''
    apps: List[WxAuthorizer] = WxAuthorizer.query.filter(
        WxAuthorizer.mark != null()
    ).all()
    for app in apps:
        if res:
            res += '\n'
        content = app.nick_name
        res += content
    if not res:
        res = '没有已经发布的小程序'
    return res


def get_auditing_answer():
    res = ''
    for b_key in audit_redis_store.scan_iter():
        key = b_key.decode('utf-8')
        app_key = key.split('-')
        biz_id = int(app_key[0])
        app_mark = int(app_key[1])
        wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(
            WxAuthorizer.biz_id == biz_id,
            WxAuthorizer.mark == app_mark
        ).first()

        version = audit_redis_store.hget(key, 'version').decode('utf-8')
        if res:
            res += '\n'
        content = '{name}, 版本{version}'.format(name=wx_authorizer.nick_name, version=version)
        res += content
    if not res:
        res = '没有正在审核的小程序'
    return res


def undo_code_audit(app_name):
    """ 审核撤回 """
    app = get_app(app_name)
    if not app:
        return '没有该小程序'

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
    return errmsg


def get_app(app_name) -> WxAuthorizer:
    app: WxAuthorizer = WxAuthorizer.query.filter(WxAuthorizer.nick_name == app_name).first()
    return app


def release(app_name):
    app = get_app(app_name)
    if not app:
        return '没有该小程序'
    release_action = ReleaseAction(wx_authorizer=app)
    release_action.execute()
    return ''


def latest_audit_status(app_name):
    app = get_app(app_name)
    if not app:
        return '没有该小程序'
    try:
        client = component.get_client_by_appid(app.app_id)
        res = client.wxa.get_latest_audit_status()
        status = res.get('status')
        audit_id = res.get('auditid')
        if status == 0:
            return '审核成功, 审核ID是{}'.format(audit_id)
        elif status == 1:
            return '审核失败, 审核ID是{}, 失败原因是{}'.format(audit_id, res.get('reason'))
        elif status == 2:
            return '审核中, 审核ID是{}'.format(audit_id)
        else:
            return str(res)
    except WeChatClientException as e:
        return '错误消息为{}, 错误码为{}'.format(e.errmsg, e.errcode)


def bind_tester(app_name, wechat_id):
    app = get_app(app_name)
    if not app:
        return '没有该小程序'
    try:
        client = component.get_client_by_appid(app.app_id)
        res = client.wxa.bind_tester(wechat_id)
        return str(res)
    except WeChatClientException as e:
        return '错误消息为{}, 错误码为{}'.format(e.errmsg, e.errcode)


@blueprint.route('/release', methods=['POST'])
def post_release_agent():
    signature = request.args.get('msg_signature', '')
    timestamp = request.args.get('timestamp', '')
    nonce = request.args.get('nonce', '')

    crypto = get_release_agent_crypto()
    try:
        msg = crypto.decrypt_message(
            request.data,
            signature,
            timestamp,
            nonce
        )
    except (InvalidSignatureException, InvalidCorpIdException):
        abort(403)

    about = """host目前可接收的命令为:
1.审核中
2.发布xxx
3.审核状态xxx
4.撤销审核xxx
5.所有小程序
6.xxx新增体验者wechat_id"""

    msg = parse_message(msg)
    if msg.type != 'text':
        reply = create_reply('很抱歉, host暂时只懂文字消息\n' + about, msg).render()
        res = crypto.encrypt_message(reply, nonce, timestamp)
        return res

    # 目前只处理文字消息
    if msg.content == '审核中':
        reply = create_reply(get_auditing_answer(), msg).render()
        return crypto.encrypt_message(reply, nonce, timestamp)
    elif msg.content.startswith('发布'):
        app_name = msg.content[2:]
        reply = create_reply(release(app_name), msg).render()
        return crypto.encrypt_message(reply, nonce, timestamp)
    elif msg.content.startswith('审核状态'):
        app_name = msg.content[4:]
        reply = create_reply(latest_audit_status(app_name), msg).render()
        return crypto.encrypt_message(reply, nonce, timestamp)
    elif msg.content.startswith('撤销审核'):
        app_name = msg.content[4:]
        reply = create_reply(undo_code_audit(app_name), msg).render()
        return crypto.encrypt_message(reply, nonce, timestamp)
    elif msg.content == '所有小程序':
        reply = create_reply(get_all_app(), msg).render()
        return crypto.encrypt_message(reply, nonce, timestamp)
    elif '新增体验者' in msg.content:
        index = msg.content.find('新增体验者')
        app_name = msg.content[0:index]
        wechat_id = msg.content[index+5:]
        reply = create_reply(bind_tester(app_name, wechat_id), msg).render()
        return crypto.encrypt_message(reply, nonce, timestamp)
    else:
        reply = create_reply(about, msg).render()

    res = crypto.encrypt_message(reply, nonce, timestamp)
    return res

