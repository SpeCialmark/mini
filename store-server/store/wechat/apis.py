from flask import Blueprint, current_app, abort, Response,  render_template
from store.config import cfg
from flask import jsonify, request, g, redirect
from store.wxopen import component, auth_client, auth_agent_id
from store.domain.models import WxAuthorizer, BizUser, StoreBiz, AppMark
from store.database import db
from datetime import datetime
import pprint
import xmltodict
from wechatpy import parse_message, utils
from sqlalchemy import desc, and_, asc
from wechatpy.crypto import WeChatCrypto
from wechatpy.exceptions import InvalidSignatureException, InvalidAppIdException
from wechatpy import parse_message, create_reply
from http import HTTPStatus
from wechatpy.utils import check_signature
from wechatpy.exceptions import (
    InvalidSignatureException,
    InvalidAppIdException,
)
from store.utils.token import generate_token
from store.domain.authorizer import update_authorizer
from store.domain.wxapp import AuditAction
from store.domain.cache import BizUserCache, BizUserNotFoundException, TokenCache, AuthLinkCache

blueprint = Blueprint('_wx', __name__)


@blueprint.route('/health', methods=['GET'])
def health():
    return jsonify(msg='Hello 11train!')


@blueprint.route('/callback', methods=['POST'])
def wechat_callback():
    signature = request.args.get('signature')
    raw_msg = request.data
    msg_signature = request.args.get('msg_signature')
    timestamp = request.args.get('timestamp')
    nonce = request.args.get('nonce')

    msg = component.parse_message(raw_msg, msg_signature, timestamp, nonce)
    """
    """
    pprint.pprint(msg)
    # msg.type 分为以下几种：component_verify_ticket，authorized，updateauthorized， unauthorized

    if msg.type == 'component_verify_ticket':
        # parse_message已经保存component_verify_ticket到redis
        return Response('success', mimetype='text/plain')
    elif msg.type == 'authorized':
        # 交给回调地址去处理
        return Response('success', mimetype='text/plain')
    elif msg.type == 'updateauthorized':
        """
        如果是authorized
        第一步： 解密获得authorization_code授权码。
        第二步： 使用授权码请求api换取公众号的授权信息, 同时在redis储存authorizer_access_token, authorizer_refresh_token
        """
        query_auth_result = msg.query_auth_result

        authorizer_appid = query_auth_result['authorization_info']['authorizer_appid']
        info_result = component.get_authorizer_info(authorizer_appid)

        wx_authorizer: WxAuthorizer = update_authorizer(
            authorizer_appid, query_auth_result['authorization_info'], info_result['authorizer_info'])

        content = '小程序更新授权, {nick_name}'.format(nick_name=wx_authorizer.nick_name)
        auth_client.message.send_text(
            agent_id=auth_agent_id,
            party_ids=cfg['party_id']['all'],
            user_ids=[],
            content=content
        )
        return Response('success', mimetype='text/plain')
    elif msg.type == 'unauthorized':
        update_unauthorized(msg.authorizer_appid)
        wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(WxAuthorizer.app_id == msg.authorizer_appid).first()
        content = '小程序取消授权, {nick_name}'.format(nick_name=wx_authorizer.nick_name)
        auth_client.message.send_text(
            agent_id=auth_agent_id,
            party_ids=cfg['party_id']['all'],
            user_ids=[],
            content=content
        )
    return Response('success', mimetype='text/plain')


def update_unauthorized(authorizer_appid):
    now = datetime.now()
    authorizer = WxAuthorizer.query.filter(WxAuthorizer.app_id == authorizer_appid).first()
    if not authorizer:
        return

    authorizer.is_authorized = False
    authorizer.unauthorized_at = now
    authorizer.modified_at = now
    db.session.commit()


@blueprint.route('/authorized/<string:auth_link_token>', methods=['GET'])
def get_authorized(auth_link_token):
    auth_code = request.args.get('auth_code', '')
    expires_in = request.args.get('expires_in', '')

    auth_cache = AuthLinkCache(token=auth_link_token)
    biz_user_id, biz_id, mark = auth_cache.get('biz_user_id', 'biz_id', 'mark')

    query_auth_result = component.query_auth(auth_code)

    authorizer_appid = query_auth_result['authorization_info']['authorizer_appid']
    info_result = component.get_authorizer_info(authorizer_appid)

    wx_authorizer: WxAuthorizer = update_authorizer(
        authorizer_appid, query_auth_result['authorization_info'], info_result['authorizer_info'])

    now = datetime.now()
    wx_authorizer.biz_id = biz_id
    wx_authorizer.mark = mark
    wx_authorizer.modified_at = now
    db.session.commit()

    content = '有新的小程序授权, {nick_name}'.format(nick_name=wx_authorizer.nick_name)
    auth_client.message.send_text(
        agent_id=auth_agent_id,
        party_ids=cfg['party_id']['all'],
        user_ids=[],
        content=content
    )

    redirect_uri = cfg['wxopen']['SUCCESS_REDIRECT_URI']
    return redirect(redirect_uri)


@blueprint.route('/server/<string:app_id>', methods=['POST'])
def post_server(app_id):
    """
    消息与事件接收
    """
    signature = request.args.get('signature', '')
    timestamp = request.args.get('timestamp', '')
    nonce = request.args.get('nonce', '')
    encrypt_type = request.args.get('encrypt_type', 'raw')
    msg_signature = request.args.get('msg_signature', '')

    # POST request
    if encrypt_type == 'raw':
        # plaintext mode, FOR TEST
        # msg = parse_message(request.data)
        # if msg.type == 'text':
        #     reply = create_reply(msg.content, msg)
        # else:
        #     reply = create_reply('Sorry, can not handle this for now', msg)
        # return reply.render()

        message = xmltodict.parse(utils.to_text(request.data))['xml']
        message_type = message['MsgType'].lower()

        # if message_type == 'text':
        #     reply = create_reply(msg.content, msg)
        #     return component.crypto.encrypt_message(reply.render(), nonce, timestamp)

        if message_type == 'event' and 'Event' in message:
            event_type = message['Event'].lower()
            if event_type == 'weapp_audit_success':
                content = '小程序审核通过, appid:{}'.format(app_id)
                print(content)

                reply = create_reply(None)
                return component.crypto.encrypt_message(reply.render(), nonce, timestamp)
            elif event_type == 'weapp_audit_fail':
                reason = message.get('Reason')
                content = '小程序审核失败, appid: {}, reason: {}'.format(app_id, reason)
                print(content)

                reply = create_reply(None)
                return component.crypto.encrypt_message(reply.render(), nonce, timestamp)

        reply = create_reply('Sorry, can not handle this for now')
        return component.crypto.encrypt_message(reply.render(), nonce, timestamp)
    else:
        # encryption mode
        try:
            msg = component.crypto.decrypt_message(
                request.data,
                msg_signature,
                timestamp,
                nonce
            )
        except (InvalidSignatureException, InvalidAppIdException):
            abort(403)
        else:
            message = xmltodict.parse(utils.to_text(msg))['xml']
            message_type = message['MsgType'].lower()

            if message_type == 'text':
                reply = create_reply(msg.content, msg)
                return component.crypto.encrypt_message(reply.render(), nonce, timestamp)

            if message_type == 'event' and 'Event' in message:
                event_type = message['Event'].lower()
                if event_type == 'weapp_audit_success':
                    wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(WxAuthorizer.app_id == app_id).first()

                    action: AuditAction = AuditAction(wx_authorizer=wx_authorizer)
                    action.execute(event_type)

                    reply = create_reply(None)
                    return component.crypto.encrypt_message(reply.render(), nonce, timestamp)
                elif event_type == 'weapp_audit_fail':
                    reason = message.get('Reason')
                    wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(WxAuthorizer.app_id == app_id).first()

                    action: AuditAction = AuditAction(wx_authorizer=wx_authorizer)
                    action.execute(event_type, reason)

                    reply = create_reply(None)
                    return component.crypto.encrypt_message(reply.render(), nonce, timestamp)

            reply = create_reply('Sorry, can not handle this for now', msg)
            return component.crypto.encrypt_message(reply.render(), nonce, timestamp)


@blueprint.route('/auth', methods=['GET'])
def get_authorized_uri():
    token = request.args.get('token', default=None, type=str)
    if not token:
        return jsonify(msg='missing token'), HTTPStatus.UNAUTHORIZED

    token_cache = TokenCache(token=token)
    if not token_cache.exists():
        return jsonify(), HTTPStatus.UNAUTHORIZED
    phone_number, website = token_cache.get('phone_number', 'website')

    # 网页端
    biz_user_cache = BizUserCache(website=website, phone_number=phone_number)

    try:
        biz_user_id = biz_user_cache.get('biz_user_id')
    except BizUserNotFoundException as e:
        return jsonify(), HTTPStatus.UNAUTHORIZED

    biz_hid = request.args.get('biz_id', default=None, type=str)
    if not biz_hid:
        return jsonify(msg='missing biz_id'), HTTPStatus.BAD_REQUEST
    store_biz: StoreBiz = StoreBiz.find(biz_hid)
    if not store_biz:
        return jsonify(msg='该门店不存在'), HTTPStatus.NOT_FOUND

    mark_str = request.args.get('mark', default=None, type=str)
    if not mark_str:
        return jsonify(msg='missing mark'), HTTPStatus.BAD_REQUEST
    if mark_str == AppMark.CUSTOMER.name.lower():
        mark = AppMark.CUSTOMER
    elif mark_str == AppMark.COACH.name.lower():
        mark = AppMark.COACH
    elif mark_str == AppMark.BOSS.name.lower():
        mark = AppMark.BOSS
    else:
        return jsonify(msg='app类型参数不对'), HTTPStatus.BAD_REQUEST

    auth_link_token = generate_token()
    auth_cache = AuthLinkCache(token=auth_link_token)
    auth_cache.set({
        'biz_user_id': biz_user_id,
        'biz_id': store_biz.id,
        'mark': mark.value
    })

    redirect_uri_format: str = cfg['wxopen']['AUTH_REDIRECT_URI']
    redirect_uri = redirect_uri_format.format(auth_link_token=auth_link_token)

    url = component.get_pre_auth_url(redirect_uri) + '&auth_type=2'
    """ auth_type 要授权的帐号类型， 1则商户扫码后，手机端仅展示公众号、2表示仅展示小程序，3表示公众号和小程序都展示。 """
    # return redirect(url)
    return render_template('transfer.html', url=url)
