from datetime import datetime, timedelta
from http import HTTPStatus
from typing import List, Tuple

from flask import Blueprint, g, jsonify, request
from sqlalchemy import true, desc, asc

from store.config import get_res
from store.database import db
from store.diaries.utils import get_nearest_seat, post_diary_image, delete_diary_image, get_coach_notes, \
    update_coach_unread
from store.domain.cache import DiaryUnreadCache
from store.domain.key_data import get_nearest_record, sort_key_data
from store.domain.middle import roles_required, customer_id_require
from store.utils.time_formatter import get_yymmdd
from store.domain.models import Customer, Diary, Trainee, DiaryImage, Plan, Ex, ExHistory, ExProperty, DUMMY_ID
from store.domain.role import CustomerRole, CoachRole
from store.utils import time_processing as tp
from store.utils.logs import post_log

blueprint = Blueprint('_diary', __name__)


@blueprint.route('', methods=['GET'])
@roles_required(CustomerRole())
def get_diaries():
    """ 客户端查看日记 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND

    today = tp.get_day_min(datetime.today())
    # 正序获取所有日记
    diaries: List[Diary] = Diary.query.filter(
        Diary.customer_id == c_id,
        Diary.recorded_at <= today
    ).order_by(asc(Diary.recorded_at)).all()

    seat_data = get_nearest_seat(today, c_id)
    plan = Plan.get_effective_plan(c_id)
    diary_unread_cache = DiaryUnreadCache(c_id)
    diary_unread_cache.is_read()
    if not diaries:
        # 虚拟日记中的体测数据取最近一次所有体测数据
        diary = {
                'id': 0,
                'customer_note': '',
                'coach_note': [],
                'check_in_data': None,
                'images': [],
                'primary_mg': [],
                'training_type': [],
                'body_data': get_nearest_record(c_id, plan),
                'date': today.strftime('%m.%d'),
                'workout': {'cards': []},
                'is_today': True,
            }
        if seat_data:
            diary.update({'seat_data': seat_data})
        return jsonify({
            'diaries': [diary],
            'avatar': customer.avatar
        })

    res = []
    for d in diaries:
        brief = d.get_brief()
        brief.update({'is_today': bool(d.recorded_at == today)})
        brief.update({'coach_note': get_coach_notes(d.coach_note)})
        # 若今日已经有日记了,则体测数据只返回今日在日记中记录的数据,而不是最近一次的所有体测数据
        # 将体测数据进度条按照选择页面的顺序排序
        brief.update({'body_data': sort_key_data(d.body_data)})
        brief.update({'workout': d.workout if d.workout else {'cards': []}})
        res.append(brief)
    # 查看今日是否有日记
    if diaries[-1].recorded_at != today:
        # 虚拟今日日记
        # 虚拟日记中的体测数据取最近一次所有体测数据
        res.append({
            'id': 0,
            'customer_note': '',
            'coach_note': [],
            'check_in_data': None,
            'images': [],
            'primary_mg': [],
            'training_type': [],
            'body_data': get_nearest_record(c_id, plan),
            'date': today.strftime('%m.%d'),
            'workout': {'cards': []},
            'is_today': True,
        })

    # 若没有课则直接返回日记列表
    if not seat_data:
        return jsonify({
            'diaries': res,
            'avatar': customer.avatar
        })

    # 在日记中添加上课提醒
    res[-1].update({
        'seat': seat_data
    })
    return jsonify({
        'diaries': res,
        'avatar': customer.avatar

    })


@blueprint.route('/<string:d_id>', methods=['GET'])
@roles_required(CustomerRole())
def get_diary(d_id):
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    diary: Diary = Diary.find(d_id)
    if not diary:
        return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
    if diary.customer_id != c_id:
        return jsonify(msg='您无权查看他人的日记'), HTTPStatus.FORBIDDEN

    today = tp.get_day_min(datetime.today())
    brief = diary.get_brief()
    brief.update({'is_today': bool(diary.recorded_at == today)})
    brief.update({'body_data': sort_key_data(diary.body_data)})  # 将体测数据进度条按照选择页面的顺序排序
    return jsonify({
        'diary': brief
    })


@blueprint.route('/<string:d_id>/note', methods=['GET'])
@roles_required(CustomerRole())
def get_note(d_id):
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    diary: Diary = Diary.find(d_id)
    if not diary:
        return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
    if diary.customer_id != c_id:
        return jsonify(msg='您无权查看他人的日记'), HTTPStatus.FORBIDDEN
    return jsonify({
        'note': diary.customer_note or ''
    })


def find_or_create(d_id, c_id) -> Tuple[Diary, bool]:
    biz_id = g.get('biz_id')
    if d_id == '0':
        date = tp.get_day_min(datetime.today())
        diary = Diary(
            biz_id=biz_id,
            customer_id=c_id,
            recorded_at=date,
            created_at=datetime.now()
        )
        db.session.add(diary)
        is_new = True
    else:
        diary: Diary = Diary.find(d_id)
        is_new = False
    return diary, is_new


@blueprint.route('/<string:d_id>/note', methods=['PUT'])
@roles_required(CustomerRole())
def put_note(d_id):
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    note = json_data.get('note')
    try:
        diary, is_new = find_or_create(d_id, c_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
        if diary.customer_id != c_id:
            return jsonify(msg='您无权修改他人的日记'), HTTPStatus.FORBIDDEN

        diary.customer_note = note
        diary.modified_at = datetime.now()
        db.session.commit()

        if is_new:
            update_coach_unread(c_id)
    except Exception as e:
        db.session.rollback()
        raise e
    return jsonify(msg='修改成功')


@blueprint.route('/images', methods=['GET'])
@roles_required(CustomerRole())
def get_images():
    """ 查看健身相册 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND

    images: List[DiaryImage] = DiaryImage.query.filter(
        DiaryImage.customer_id == c_id
    ).order_by(desc(DiaryImage.created_at)).all()

    res = []
    if not images:
        res.append({
            'd_id': 0,
            'date': datetime.today().strftime("%Y年%m月%d日"),
            'images': [],

        })
        return jsonify(res)
    last_date = ""
    for i in images:
        date = i.created_at.strftime('%Y年%m月%d日')
        if date != last_date:
            last_date = date
            diary: Diary = Diary.query.filter(
                Diary.customer_id == c_id,
                Diary.recorded_at == tp.get_day_min(i.created_at)
            ).first()
            res.append({
                'd_id': diary.get_hash_id() if diary else 0,
                'date': date,
                'images': []
            })
        res[-1]['images'].append({
            'id': i.get_hash_id(),
            'image': i.image
        })

    if res[0].get('date') != datetime.today().strftime('%Y年%m月%d日'):
        res.insert(0, {
            'd_id': 0,
            'date': datetime.today().strftime('%Y年%m月%d日'),
            'images': []
        })

    return jsonify(res)


@blueprint.route('/<string:d_id>/images', methods=['POST'])
@roles_required(CustomerRole())
def post_images(d_id):
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    image = json_data.get('image')
    try:
        diary, is_new = find_or_create(d_id, c_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
        if diary.customer_id != c_id:
            return jsonify(msg='您无权修改他人的日记'), HTTPStatus.FORBIDDEN
        if is_new:
            update_coach_unread(c_id)
        msg = post_diary_image(diary, image)
        post_log(
            biz_id=biz_id, operator_id=w_id, operation="上传",
            operating_object_id=c_id,
            content="健身照片"
        )
    except Exception as e:
        db.session.rollback()
        raise e
    return jsonify(msg=msg)


@blueprint.route('/<string:d_id>/images/<string:i_id>', methods=['DELETE'])
@roles_required(CustomerRole())
def delete_image(d_id, i_id):
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    diary: Diary = Diary.find(d_id)
    if not diary:
        return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
    if diary.customer_id != c_id:
        return jsonify(msg='您无权修改他人的日记'), HTTPStatus.FORBIDDEN

    msg = delete_diary_image(diary, i_id)
    post_log(
        biz_id=biz_id, operator_id=w_id, operation="删除",
        operating_object_id=c_id,
        content="健身照片"
    )
    return jsonify(msg=msg)


@blueprint.route('/<string:d_id>/training_type', methods=['GET'])
@roles_required(CustomerRole())
def get_training_type(d_id):
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    training_type = get_res(directory='training_type', file_name='training_type.yml').get('training_type')
    diary: Diary = Diary.find(d_id)

    if not diary:
        return jsonify({
            'all_type': training_type,
            'chose_type': []
        })
    if diary.customer_id != c_id:
        return jsonify({
            'all_type': training_type,
            'chose_type': []
        })
    return jsonify({
        'all_type': training_type,
        'chose_type': diary.training_type or []
    })


@blueprint.route('/<string:d_id>/training_type', methods=['PUT'])
@roles_required(CustomerRole())
def put_training_type(d_id):
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    w_id = g.get('w_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(), HTTPStatus.BAD_REQUEST
    training_type = json_data.get('training_type')

    try:
        diary, is_new = find_or_create(d_id, c_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
        if diary.customer_id != c_id:
            return jsonify(msg='您无权修改他人的日记'), HTTPStatus.FORBIDDEN
        if is_new:
            update_coach_unread(c_id)

        diary.training_type = training_type
        diary.modified_at = datetime.now()
        db.session.commit()
        post_log(
            biz_id=biz_id, operator_id=w_id, operation="修改",
            operating_object_id=c_id,
            content="训练类型"
        )
    except Exception as e:
        db.session.rollback()
        raise e
    return jsonify(msg='修改成功')


@blueprint.route('/<string:d_id>/muscle_group', methods=['GET'])
@roles_required(CustomerRole())
def get_muscle_group(d_id):
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)

    diary: Diary = Diary.find(d_id)
    if not diary:
        return jsonify({
            'primary_mg': [],
            'secondary_mg': []
        })
    if diary.customer_id != c_id:
        return jsonify(msg='您无权查看他人的日记'), HTTPStatus.FORBIDDEN
    return jsonify({
        'primary_mg': diary.primary_mg or [],
        # 'secondary_mg': diary.secondary_mg
    })


@blueprint.route('/<string:d_id>/muscle_group', methods=['PUT'])
@roles_required(CustomerRole())
def put_muscle_group(d_id):
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    w_id = g.get('w_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    primary_mg = json_data.get('primary_mg')
    # secondary_mg = json_data.get('secondary_mg')
    try:
        diary, is_new = find_or_create(d_id, c_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
        if diary.customer_id != c_id:
            return jsonify(msg='您无权修改他人的日记'), HTTPStatus.FORBIDDEN
        if is_new:
            update_coach_unread(c_id)

        diary.primary_mg = primary_mg
        diary.modified_at = datetime.now()
        # diary.secondary_mg = secondary_mg
        db.session.commit()
        post_log(
            biz_id=biz_id, operator_id=w_id, operation="修改",
            operating_object_id=c_id,
            content="训练部位"
        )
    except Exception as e:
        db.session.rollback()
        raise e
    return jsonify(msg='修改成功')


@blueprint.route('/<string:d_id>/workout', methods=['GET'])
@customer_id_require()
def get_workout(d_id):
    customer_id = g.customer_id
    diary: Diary = Diary.find(d_id)

    if not diary:
        return jsonify({
            'workout': {'cards': []},
        })
    if diary.customer_id != customer_id:
        return jsonify(msg='您无权查看他人的日记'), HTTPStatus.FORBIDDEN
    return jsonify({
        'workout': diary.workout if diary.workout else {'cards': []},
    })


@blueprint.route('/<string:d_id>/workout', methods=['PUT'])
@customer_id_require()
def put_workout(d_id):
    customer_id = g.customer_id
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(), HTTPStatus.BAD_REQUEST

    cards = json_data.get('cards')

    try:
        diary, is_new = find_or_create(d_id, customer_id)
        if not diary:
            return jsonify(msg='日记不存在'), HTTPStatus.NOT_FOUND
        if diary.customer_id != customer_id:
            return jsonify(msg='您无权修改他人的日记'), HTTPStatus.FORBIDDEN

        diary.workout = {
            'cards': cards
        }
        diary.modified_at = datetime.now()

        if is_new:
            db.session.flush()
            db.session.refresh(diary)

        old_exs = ExHistory.query.filter(
            ExHistory.customer_id == customer_id,
            ExHistory.diary_id == diary.id
        ).all()
        for old_ex in old_exs:
            db.session.delete(old_ex)

        # 找出ExHistory对应的。
        for card in cards:
            if 'ex' in card:
                process_ex(card, diary.id, diary.recorded_at, customer_id)

        db.session.commit()

        if is_new:
            update_coach_unread(customer_id)
    except Exception as e:
        db.session.rollback()
        raise e
    post_log(
        biz_id=biz_id, operator_id=w_id, operation="修改",
        operating_object_id=customer_id,
        content="训练动作"
    )
    return jsonify(msg='修改成功')


def get_last(sets):
    last_record_method, last_unit = None, None
    if sets:
        last_record_method = sets[-1].get('method')
        last_unit = sets[-1].get('unit')
    return last_record_method, last_unit


def process_ex(card, diary_id, diary_date, customer_id):
    ex_id = card.get('ex').get('id')
    ex_title = card.get('ex').get('title')
    sets = card.get('sets')
    note = card.get('note')

    if not sets and not note:
        return

    now = datetime.now()
    last_record_method, last_unit = get_last(sets)

    if str(ex_id) == DUMMY_ID:
        # 自定义动作类型

        ex_his = ExHistory(
            ex_id=int(DUMMY_ID),
            ex_title=ex_title,
            customer_id=customer_id,
            diary_id=diary_id,
            diary_date=diary_date,
            created_at=now
        )
        ex_his.sets = sets
        ex_his.note = note
        ex_his.recorded_at = now
        db.session.add(ex_his)

        if last_record_method:
            ex_property: ExProperty = ExProperty.query.filter(
                ExProperty.customer_id == customer_id,
                ExProperty.ex_id == int(DUMMY_ID),
                ExProperty.ex_title == ex_title
            ).first()
            if not ex_property:
                ex_property = ExProperty(
                    customer_id=customer_id,
                    ex_id=DUMMY_ID,
                    ex_title=ex_title,
                    created_at=now,
                )
                db.session.add(ex_property)
            ex_property.record_method = last_record_method
            ex_property.unit = last_unit
            ex_property.last_recorded_at = now
    else:
        ex: Ex = Ex.find(ex_id)
        if not ex:
            return

        ex_his = ExHistory(
            ex_id=ex.id,
            customer_id=customer_id,
            diary_id=diary_id,
            diary_date=diary_date,
            created_at=now
        )
        ex_his.sets = sets
        ex_his.note = note
        ex_his.recorded_at = now
        db.session.add(ex_his)

        if last_record_method:
            ex_property: ExProperty = ExProperty.query.filter(
                ExProperty.customer_id == customer_id,
                ExProperty.ex_id == ex.id
            ).first()
            if not ex_property:
                ex_property = ExProperty(
                    customer_id=customer_id,
                    ex_id=ex.id,
                    created_at=now
                )
                db.session.add(ex_property)
            ex_property.record_method = last_record_method
            ex_property.unit = last_unit
            ex_property.last_recorded_at = now
