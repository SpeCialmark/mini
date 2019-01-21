from datetime import datetime
from http import HTTPStatus
from typing import List

from flask import Blueprint
from flask import jsonify, request, g

from store.database import db
from store.domain.cache import StoreBizCache
from store.domain.middle import permission_required
from store.domain.models import Customer, Salesman, Goods, Activity, ActivityStatus
from store.domain.permission import ManageSalesmanPermission, ViewBizPermission
from store.domain.role import CustomerRole

blueprint = Blueprint('_goods', __name__)


@blueprint.route('', methods=['POST'])
@permission_required(ManageSalesmanPermission())
def post_goods():
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    price = json_data.get('price')
    description = json_data.get('description')
    images = json_data.get('images')
    stock = json_data.get('stock')
    if not all([name, price, description, images]):
        return jsonify(msg='请将数据填写完整'), HTTPStatus.BAD_REQUEST

    old_goods: Goods = Goods.query.filter(
        Goods.biz_id == biz_id,
        Goods.name == name,
    ).first()
    if old_goods:
        return jsonify(msg='该商品已存在'), HTTPStatus.BAD_REQUEST

    new_goods = Goods(
        biz_id=biz_id,
        name=name,
        price=price,
        description=description,
        images=images,
        created_at=datetime.now(),
    )
    if stock:
        new_goods.stock = stock

    db.session.add(new_goods)
    db.session.commit()

    store_cache = StoreBizCache(biz_id)
    store_cache.reload()

    return jsonify(msg='添加成功')


@blueprint.route('', methods=['GET'])
@permission_required(ViewBizPermission())
def get_goods_list():
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    if w_id:
        store_cache = StoreBizCache(biz_id)
        goods_briefs = store_cache.get('goods_briefs')
    else:
        goods: List[Goods] = Goods.query.filter(
            Goods.biz_id == biz_id
        ).all()
        goods_briefs = [gs.get_brief() for gs in goods]
    return jsonify({
        'goods': goods_briefs
    })


@blueprint.route('/<string:g_id>', methods=['GET'])
@permission_required(ViewBizPermission())
def get_goods(g_id):
    goods: Goods = Goods.find(g_id)
    w_id = g.get('w_id')
    if w_id:
        if not goods or goods.is_shelf is False:
            return jsonify(msg='商品不存在或已下架')
    else:
        if not goods:
            return jsonify(msg='商品不存在')
    return jsonify({
        'goods': goods.get_brief()
    })


@blueprint.route('/<string:g_id>', methods=['PUT'])
@permission_required(ManageSalesmanPermission())
def put_goods(g_id):
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    goods: Goods = Goods.find(g_id)
    if not goods:
        return jsonify(msg='商品不存在')

    name = json_data.get('name')
    price = json_data.get('price')
    description = json_data.get('description')
    images = json_data.get('images')
    cover_image = json_data.get('cover_image')
    stock = json_data.get('stock')

    if name and name != '':
        goods.name = name
    if price and price != '':
        goods.price = price
    if description and description != '':
        goods.description = description
    if images and images != '':
        goods.images = images
    if stock and stock != '':
        goods.stock = stock
    if cover_image and cover_image != '':
        goods.cover_image = cover_image

    db.session.commit()
    db.session.refresh(goods)
    store_cache = StoreBizCache(biz_id)
    store_cache.reload()

    return jsonify(msg='修改成功')


@blueprint.route('/<string:g_id>', methods=['DELETE'])
@permission_required(ManageSalesmanPermission())
def delete_goods(g_id):
    biz_id = g.get('biz_id')
    goods: Goods = Goods.find(g_id)
    if not goods:
        return jsonify(msg='商品不存在')

    actives: Activity = Activity.query.filter(
        Activity.biz_id == biz_id,
        Activity.goods_id == goods.id,
        Activity.status != ActivityStatus.CLOSE,
        Activity.status != ActivityStatus.END,
    ).first()
    if actives:
        return jsonify(msg='该商品还有正在开启的拼团活动,请勿下架'), HTTPStatus.BAD_REQUEST
    goods.is_shelf = False
    db.session.commit()
    db.session.refresh(goods)

    store_cache = StoreBizCache(biz_id)
    store_cache.reload()

    return jsonify(msg='修改成功')


@blueprint.route('/<string:g_id>/re_shelf', methods=['PUT'])
@permission_required(ManageSalesmanPermission())
def re_shelf_goods(g_id):
    # 重新上架商品
    biz_id = g.get('biz_id')
    goods: Goods = Goods.find(g_id)
    if not goods:
        return jsonify(msg='商品不存在')

    goods.is_shelf = True
    db.session.commit()
    db.session.refresh(goods)

    store_cache = StoreBizCache(biz_id)
    store_cache.reload()
    return jsonify(msg='修改成功')
