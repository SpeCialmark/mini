import secrets
from http import HTTPStatus
from flask import Blueprint, json
from sqlalchemy import and_, null
from store.database import db
from store.cache import invitation_redis_store
from store.config import cfg
from store.domain.cache import TraineeCache, AppCache, CoachCache
from store.domain.models import WxOpenUser, Coach, Customer, Trainee, WxMessage
from flask import jsonify, request, g
from datetime import datetime
from store.domain.wx_push import queue_coach_binding_message
from store.user.apis import send_messages
from store.domain.middle import roles_required, permission_required
from store.domain.role import CustomerRole, CoachRole
from store.domain.permission import ViewBizPermission

blueprint = Blueprint('_invitations', __name__)


@blueprint.route('/customer_app_id', methods=['GET'])
@roles_required(CoachRole())
def get_customer_app_id():
    """ 获取跳转的客户端小程序app_id """
    app_id = g.get('app_id')
    app_cache = AppCache(app_id)
    customer_app_id = app_cache.get('customer_app_id')

    return jsonify({
        "customer_app_id": customer_app_id
    })


@blueprint.route('', methods=['POST'])
@roles_required(CoachRole())
def post_invitations():
    """保存form_id的同时访问此接口生成邀请函"""
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    is_demo = g.get('is_demo')
    coach: Coach = Coach.query.filter(
        Coach.id == coach_id,
    ).first()
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='类别错误'), HTTPStatus.BAD_REQUEST
    i_type = json_data.get('type')  # 邀请类型(分为私教会员和体测会员两种)
    if not i_type:
        i_type = "private"
    if is_demo:
        token = 'demo'
    else:
        token = secrets.token_hex(12)
        invitation_redis_store.hset(token, 'coach_id', coach_id)
        invitation_redis_store.hset(token, 'type', i_type)
        invitation_redis_store.expire(token, cfg['redis_expire']['invitations'])

    return jsonify({
        "id": token,
        "coach": {
            "avatar": coach.avatar if coach.avatar else coach.images[0],
            "name": coach.name,
        },

    })


@blueprint.route('/<string:id>', methods=['GET'])
@permission_required(ViewBizPermission())
def get_invitations(id):
    """
    :param id: invitations_token
    :return: 该邀请的有效状态
    """
    coach_id_b = invitation_redis_store.hget(id, 'coach_id')
    if not coach_id_b:
        return jsonify({
            'status': 'fail'
        })
    coach_id = int(coach_id_b)
    coach_cache = CoachCache(coach_id)
    brief = coach_cache.get('brief')
    name = brief.get('name')
    avatar = brief.get('avatar')

    return jsonify({
        "status": 'success',
        "coach": {
            'name': name,
            'avatar': avatar,
        }
    })


@blueprint.route('/<string:id>/accept', methods=['POST'])
@roles_required(CustomerRole())
def post_accept_invitations(id):
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()

    json_data = request.get_json()
    name = json_data['realName']

    coach_id_b = invitation_redis_store.hget(id, 'coach_id')
    if not coach_id_b:
        return jsonify()
    i_type_b = invitation_redis_store.hget(id, 'type')
    if not i_type_b:
        return jsonify(msg='类别错误'), HTTPStatus.BAD_REQUEST

    if not i_type_b:
        i_type = "private"
    else:
        i_type = i_type_b.decode("utf-8")

    coach_id = int(coach_id_b)

    trainee: Trainee = Trainee.query.filter(and_(
        Trainee.customer_id == customer.id,
        Trainee.coach_id == coach_id,
    )).first()
    now = datetime.now()
    if i_type == 'private':
        # 邀请成为私教会员
        if trainee:
            # 如果有,查看是否为绑定的状态
            if trainee.is_bind:
                # 是则说明已经于该教练绑定过了
                return jsonify(msg='您已经接受过该教练的邀请了'), HTTPStatus.BAD_REQUEST
            else:
                # 不是则说明该会员曾经绑定过该教练但是解绑了
                # 重制该会员的状态
                trainee.unbind_at = None
                trainee.total_lessons = 0
                trainee.attended_lessons = 0
                trainee.modified_at = now
                trainee.name = name
                trainee.is_bind = True
                trainee.bind_at = now

        else:
            # 没有则说明是全新的会员
            trainee = Trainee(
                customer_id=customer.id,
                coach_id=coach_id,
                name=name,
                created_at=now,
                bind_at=now,
                attended_lessons=0,
                total_lessons=0,
                tags=[],
                is_bind=True,
            )
            db.session.add(trainee)

    elif i_type == 'measurements':
        # 体测会员
        if trainee:
            if trainee.is_measurements:
                return jsonify(msg='您已经接受过该教练的邀请了'), HTTPStatus.BAD_REQUEST

            trainee.is_measurements = True
            trainee.accepted_at = now
            trainee.modified_at = now
        else:
            trainee = Trainee(
                coach_id=coach_id,
                customer_id=customer_id,
                name=name,
                created_at=now,
                accepted_at=now,
                is_measurements=True
            )
            db.session.add(trainee)
            db.session.commit()
            db.session.refresh(trainee)

        invitation_redis_store.delete(id)
        trainee_cache = TraineeCache(coach_id=coach_id, customer_id=customer.id)
        trainee_cache.reload()  # 刷新缓存
    else:
        return jsonify(msg='类别错误'), HTTPStatus.BAD_REQUEST

    # 发送模板消息给教练
    # 获取教练的open_id
    coach_open: WxOpenUser = WxOpenUser.query.filter(and_(
        WxOpenUser.coach_id == coach_id,
        WxOpenUser.role == 'coach'
    )).first()

    db.session.commit()
    db.session.refresh(trainee)
    invitation_redis_store.delete(id)
    trainee_cache = TraineeCache(coach_id=coach_id, customer_id=customer.id)
    trainee_cache.reload()  # 刷新缓存
    data = {
        'coach_open': coach_open,
        'trainee': trainee,
        'customer': customer,
    }
    queue_coach_binding_message(data)  # 提交消息进入队列
    send_messages(coach_open)  # 发送消息
    return jsonify(msg='成功接受邀请')
