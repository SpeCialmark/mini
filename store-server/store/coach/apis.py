from datetime import datetime
from http import HTTPStatus
from typing import List
from flask import Blueprint, request
from sqlalchemy import true

from store.database import db
from store.domain.cache import CoachCache
from store.domain.models import Coach, Trainee, DiaryImage, PhotoWall
from flask import jsonify, g

from store.domain.middle import roles_required, permission_required
from store.domain.role import CoachRole, CustomerRole

blueprint = Blueprint('_coach', __name__)


@blueprint.route('/info', methods=["GET"])
@roles_required(CoachRole())
def get_coach_info():
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    coach: Coach = Coach.query.filter(
        Coach.id == coach_id
    ).first()
    return jsonify({
        'id': coach.get_hash_id()
    })


@blueprint.route('/exp_reservation', methods=["GET"])
@roles_required(CoachRole())
def get_exp_reservation():
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    coach: Coach = Coach.query.filter(
        Coach.id == coach_id,
    ).first()
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND

    return jsonify({
        # 默认关闭
        "exp_reservation": coach.exp_reservation if coach.exp_reservation else False
    })


@blueprint.route('/exp_reservation', methods=["PUT"])
@roles_required(CoachRole())
def put_exp_reservation():
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    coach: Coach = Coach.query.filter(
        Coach.id == coach_id,
    ).first()
    json_data = request.get_json()
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND

    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    exp_reservation = json_data.get('exp_reservation')

    coach.exp_reservation = exp_reservation
    db.session.commit()
    db.session.refresh(coach)

    coach_cache = CoachCache(coach.id)
    coach_cache.reload()
    return jsonify({
        "exp_reservation": coach.exp_reservation
    })


@blueprint.route('/photo_wall/available_photos', methods=['GET'])
@roles_required(CoachRole())
def get_available_images():
    """ 教练在编辑照片墙的时候获取可用图片库 """
    biz_id = g.get('biz_id')
    c_id = CoachRole(biz_id).get_id(g.role)
    coach: Coach = Coach.query.filter(
        Coach.id == c_id
    ).first()
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    trainee: List[Trainee] = Trainee.query.filter(
        Trainee.coach_id == coach.id,
        Trainee.is_bind == true(),
    ).all()
    customer_ids = [t.customer_id for t in trainee]
    images: List[DiaryImage] = DiaryImage.query.filter(
        DiaryImage.customer_id.in_(customer_ids),
    ).all()
    res = [i.image for i in images]
    return jsonify({
        "photos": res
    })


@blueprint.route('/photo_wall', methods=['GET'])
@roles_required(CoachRole())
def get_photo_wall():
    biz_id = g.get('biz_id')
    c_id = CoachRole(biz_id).get_id(g.role)
    coach: Coach = Coach.query.filter(
        Coach.id == c_id
    ).first()
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    return jsonify({
        "photo_wall": PhotoWall.get_photos(coach.id)
    })


@blueprint.route('/photo_wall/photo', methods=['POST', 'DELETE'])
@roles_required(CoachRole())
def put_photo_wall():
    """ 修改照片墙的照片 """
    biz_id = g.get('biz_id')
    c_id = CoachRole(biz_id).get_id(g.role)
    coach: Coach = Coach.query.filter(
        Coach.id == c_id
    ).first()
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    photos = json_data.get('photos')
    if not photos:
        return jsonify(msg='请选择图片'), HTTPStatus.BAD_REQUEST
    if request.method == 'POST':
        for photo in photos:
            photo_wall = PhotoWall(
                biz_id=biz_id,
                coach_id=coach.id,
                photo=photo,
                created_at=datetime.now()
            )
            db.session.add(photo_wall)
        db.session.commit()
        return jsonify(msg='添加成功')
    elif request.method == "DELETE":
        p_ids = [PhotoWall.decode_id(p_hid) for p_hid in photos]
        photos: List[PhotoWall] = PhotoWall.query.filter(
            PhotoWall.coach_id == coach.id,
            PhotoWall.id.in_(p_ids)
        ).all()
        for photo in photos:
            db.session.delete(photo)
        db.session.commit()
        return jsonify(msg='删除成功')
    else:
        return HTTPStatus.METHOD_NOT_ALLOWED
