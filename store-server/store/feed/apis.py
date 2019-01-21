from typing import List

from flask import Blueprint, g, jsonify, request
from sqlalchemy import desc, and_, func, asc
from store.domain.cache import AppCache, StoreBizCache, CoachCache, CustomerCache, AppAuditCache
from store.domain.middle import roles_required, permission_required, hide_feed_videos
from store.domain.permission import ManageFeedPermission, ViewBizPermission
from http import HTTPStatus
from datetime import datetime
from store.domain.models import Feed, WxOpenUser, Thumb, Video, Coach
from store.database import db
from store.utils import time_processing as tp
from store.videos.apis import check_video_info

blueprint = Blueprint('_feed', __name__)


@blueprint.route('', methods=['POST'])
@permission_required(ManageFeedPermission())
def post_feed_v2():
    biz_id = g.get('biz_id')
    feed_data = request.get_json()

    if not feed_data:
        return jsonify(msg='missing feed_data'), HTTPStatus.BAD_REQUEST

    feed_type = request.args.get('feed_type', default=FeedType.Store)  # 选择是教练自己发还是门店发
    if feed_type not in [FeedType.Coach, FeedType.Store]:
        return jsonify(msg='类别错误'), HTTPStatus.BAD_REQUEST

    feed = Feed()
    if feed_type == FeedType.Coach:
        w_id = g.get('w_id')
        wx_open_user: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.id == w_id
        ).first()
        if not wx_open_user.coach_id:
            return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
        feed.coach_id = wx_open_user.coach_id

    images = feed_data.get('images')
    words = feed_data.get('words')
    video = feed_data.get('video')

    feed.biz_id = biz_id
    feed.words = words or ""
    feed.images = images or []
    feed.video = video or {}
    feed.created_at = datetime.now()

    db.session.add(feed)
    db.session.commit()

    return jsonify(msg='发布成功')


@blueprint.route('', methods=['GET'])
@permission_required(ViewBizPermission())
@hide_feed_videos
def get_feed():
    biz_id = g.get('biz_id')

    store_biz_cache = StoreBizCache(biz_id=biz_id)
    app_id = store_biz_cache.get('customer_app_id')  # 获取小程序头像和昵称需要
    # PC端
    page = request.args.get('page', 1, type=int)  # 默认显示第一页的数据
    page_size = request.args.get('page_size', 10, type=int)  # 每页显示条数(pc端与小程序不同)

    feeds: Feed = Feed.query.filter(
        Feed.biz_id == biz_id
    ).order_by(desc(Feed.created_at)).paginate(page=page, per_page=page_size, error_out=False)  # 分页器(页数, 每页显示条数)

    if page == 1 and feeds.items == []:
        # 第一页没有数据说明没有发布过动态
        return jsonify({'feed_list': []})

    app_cache = AppCache(app_id)
    name, head_img = app_cache.get('nick_name', 'head_img')
    w_id = g.get('w_id')
    if w_id:
        # 小程序端返回点赞数据
        w_user: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.id == w_id
        ).first()

        feed_list = [get_mini_feed_dict(feed=feed, name=name, head_img=head_img, customer_id=w_user.customer_id) for
                     feed in feeds.items]
        return jsonify({
            'feed_list': feed_list,
            'page_count': feeds.pages,  # 总页数
            'page': feeds.has_next
        })

    feed_list = [get_feed_dict(feed=feed, name=name, head_img=head_img) for feed in feeds.items]
    return jsonify({
        'feed_list': feed_list,
        'page_count': feeds.pages,  # 总页数
        'page': feeds.has_next
    })


@blueprint.route('/<string:f_hid>', methods=['DELETE'])
@permission_required(ManageFeedPermission())
def del_feed(f_hid):
    feed: Feed = Feed.find(f_hid)
    if not feed:
        return jsonify(msg='动态不存在'), HTTPStatus.NOT_FOUND

    db.session.delete(feed)
    db.session.commit()

    return jsonify(msg='删除成功')


@blueprint.route('/<string:f_hid>/thumb', methods=['POST'])
@permission_required(ViewBizPermission())
def post_thumb(f_hid):
    biz_id = g.get('biz_id')
    feed: Feed = Feed.find(f_hid)
    if not feed:
        return jsonify(msg='动态不存在'), HTTPStatus.NOT_FOUND
    w_id = g.get('w_id')
    w_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.id == w_id
    ).first()
    if not w_user:
        return jsonify(msg='账号有误'), HTTPStatus.BAD_REQUEST
    thumb: Thumb = Thumb.query.filter(
        Thumb.feed_id == feed.id,
        Thumb.customer_id == w_user.customer_id
    ).first()

    if thumb:
        return jsonify({
            'thumb': True,
            "thumb_count": get_thumb_count(feed),
            'nick_names': get_thumb_nick_name(feed)
        })

    thumb = Thumb(
        biz_id=biz_id,
        customer_id=w_user.customer_id,
        feed_id=feed.id,
        created_at=datetime.now()
    )

    db.session.add(thumb)
    db.session.commit()
    db.session.refresh(thumb)

    return jsonify({
        'thumb': True,
        'thumb_count': get_thumb_count(feed),
        'nick_names': get_thumb_nick_name(feed)
    })


@blueprint.route('/unread', methods=['GET'])
@roles_required()
def get_feed_unread():
    biz_id = g.get('biz_id')
    read_feed_hid = request.args.get('id', default=None, type=str)
    latest_feed: Feed = Feed.query.filter(
        Feed.biz_id == biz_id,
    ).order_by(desc(Feed.created_at)).first()
    if not latest_feed:
        # 没有发布过动态,不显示红点
        unread = False
        return jsonify({"unread": unread})

    if not read_feed_hid:
        # 如果没有已读feed_id则直接显示红点
        unread = True
        return jsonify({"unread": unread})

    read_feed: Feed = Feed.find(read_feed_hid)
    if not read_feed:
        # 已读的feed_id是非法id
        unread = True
        return jsonify({"unread": unread})

    if latest_feed.id > read_feed.id:
        # 最新的动态id大于已读的动态id
        unread = True
        return jsonify({"unread": unread})

    return jsonify({"unread": False})


def get_feed_dict(feed, name, head_img):
    if feed.coach_id:
        c_cache = CoachCache(feed.coach_id)
        c_brief = c_cache.get('brief')
        name = c_brief.get('name')
        head_img = c_brief.get('image')

    feed_time = get_feed_time(feed.created_at)

    feed_dict = {
        "f_id": feed.get_hash_id(),
        "name": name,
        "head_img": head_img,
        "images": feed.images,
        "words": feed.words,
        "time": feed_time,
    }
    if feed.video:
        file_id = feed.video.get('fileId')
        video: Video = Video.find(file_id)
        if video:
            video = check_video_info(video)  # 校验视频信息(封面图等)
            feed_dict.update({"video": video.get_brief()})

    return feed_dict


def get_mini_feed_dict(feed, name, head_img, customer_id):
    # 小程序端需要显示点赞
    if feed.coach_id:
        c_cache = CoachCache(feed.coach_id)
        c_brief = c_cache.get('brief')
        name = c_brief.get('name')
        head_img = c_brief.get('image')

    feed_time = get_feed_time(feed.created_at)

    feed_dict = {
        "f_id": feed.get_hash_id(),
        "name": name,
        "head_img": head_img,
        "images": feed.images,
        "words": feed.words,
        "time": feed_time,
        "thumb": get_feed_thumb(customer_id, feed),
        "thumb_count": get_thumb_count(feed),
        "nick_names": get_thumb_nick_name(feed),
        "coach_id": Coach.encode_id(feed.coach_id) if feed.coach_id else ""  # 点击头像跳转需要
    }
    if feed.video:
        file_id = feed.video.get('fileId')
        video: Video = Video.find(file_id)
        if video:
            video = check_video_info(video)  # 校验视频信息(封面图等)
            feed_dict.update({"video": video.get_brief()})

    return feed_dict


def get_feed_time(feed_date):
    feed_date_min = tp.get_day_min(feed_date)
    today = tp.get_day_min(datetime.today())
    delta = today - feed_date_min
    if delta.days == 0:
        time_str = "今天  " + feed_date.strftime("%H:%M")
    elif delta.days == 1:
        time_str = "昨天" + feed_date.strftime("%H:%M")
    else:
        time_str = feed_date.strftime("%Y年%m月%d日  %H:%M")

    return time_str


def get_feed_thumb(customer_id, feed):

    thumb: Thumb = Thumb.query.filter(
        Thumb.customer_id == customer_id,
        Thumb.feed_id == feed.id
    ).first()

    if not thumb:
        return False
    return True


def get_thumb_count(feed):
    thumb_count = db.session.query(func.count(Thumb.customer_id)).filter(
        Thumb.feed_id == feed.id
    ).scalar()
    return thumb_count


def get_thumb_nick_name(feed):
    thumbs: List[Thumb] = Thumb.query.filter(
        Thumb.feed_id == feed.id
    ).order_by(asc(Thumb.created_at)).all()
    res = []
    for t in thumbs:
        c_cache = CustomerCache(t.customer_id)
        nick_name = c_cache.get('nick_name')
        res.append(nick_name)
    return res


class FeedType:
    Coach = 'coach'
    Store = 'store'
