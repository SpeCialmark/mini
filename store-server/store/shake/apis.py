import json
import random
from datetime import datetime, timedelta
from typing import List

from flask import Blueprint
from flask import jsonify, request, g
from sqlalchemy import true, desc, func
from store.check_in.apis import RecordUtil
import requests
from http import HTTPStatus

from store.database import db
from store.domain.cache import GroupCoursesCache, CheckInCache, CustomerCache
from store.domain.middle import roles_required, permission_required, hide_shake_videos
from store.domain.models import Store, Coach, CheckIn, Video, GroupTime, Place
from store.domain.role import CustomerRole
from store.group_course_v2.apis import get_group_times_brief, get_active
from store.places.apis import get_nearest_course
from store.videos.utils import get_mini_tags_data, get_thumb_count, check_video_info
from store.utils import time_processing as tp

blueprint = Blueprint('_shake', __name__)
map_accessKey = 'TCABZ-GDD65-SBRIU-Q63GA-OIZ5V-EUBG4'
gd_map_accessKey = '2cf77237ab1e722a93335c56571f9f7d'


@blueprint.route('', methods=['POST'])
@roles_required(CustomerRole())
@hide_shake_videos()
def post_shake():
    """ 用户摇一摇时触发,根据其地理位置返回不同的数据 """
    # 由于小程序原生接口getLocation获取的用户位置可能会不准确
    # 因此暂时采用多点比对取最短距离的方式
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    if not store:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    locations = json_data.get('locations')  # type: List
    if not all([locations]):
        return jsonify(msg='获取地理位置失败'), HTTPStatus.BAD_REQUEST
    # 获取商家的地理位置(经纬度)
    # latitude: 纬度, longitude: 经度
    to_latitude, to_longitude = store.get_position()

    origins = ""
    accuracies = []
    for index, l in enumerate(locations):
        # 前端进过筛选后同时发送多个坐标点到后台
        from_latitude = l.get('latitude')
        from_longitude = l.get('longitude')
        accuracy = l.get('accuracy')
        accuracies.append(accuracy)
        if index != 0:
            origins += '|{f_longitude},{f_latitude}'.format(f_longitude=from_longitude, f_latitude=from_latitude)
        else:
            origins += '{f_longitude},{f_latitude}'.format(f_longitude=from_longitude, f_latitude=from_latitude)

    gd_d_url = """https://restapi.amap.com/v3/distance?key={key}&origins={origins}&destination={t_longitude},{t_latitude}&output=json&type=0""".format(
        origins=origins, t_longitude=to_longitude, t_latitude=to_latitude,
        key=gd_map_accessKey
    )
    gd_r = requests.get(gd_d_url)
    gd_response_data = json.loads(gd_r.content)
    if not gd_response_data:
        return jsonify(msg='too fast'), HTTPStatus.BAD_REQUEST

    response = gd_response_data.get('results')
    distances = [int(res.get('distance')) for res in response]
    min_distance = min(distances)
    if min_distance <= 300:
        store_shake = get_store_shake(biz_id, customer_id)
        return jsonify(store_shake)

    home_shake = get_home_shake(biz_id, customer_id)
    return jsonify(home_shake)


def get_place(biz_id):
    group_times: List[GroupTime] = GroupTime.query.filter(
        GroupTime.biz_id == biz_id
    ).order_by(desc(GroupTime.start_date)).all()

    group_times_brief = get_group_times_brief(group_times)
    active_group_time_id = get_active(group_times_brief)

    if active_group_time_id:
        group_courses_cache = GroupCoursesCache(biz_id, active_group_time_id)
        group_courses = group_courses_cache.get('group_courses')
        if not group_courses:
            group_courses_cache.reload()
            group_courses = group_courses_cache.get('group_courses')

        g_place_ids = set(group_course.get('place_id') for group_course in group_courses)
    else:
        # 如果没有正在生效的课表
        g_place_ids = set()
        group_courses = list()

    v_places: List[Place] = Place.query.filter(
        Place.biz_id == biz_id,
        Place.videos != [],
    ).all()

    v_place_ids = set(v_p.id for v_p in v_places)

    place_ids = list(g_place_ids | v_place_ids)
    if not place_ids:
        return {}
    place_id = random.choice(place_ids)
    place: Place = Place.query.filter(
        Place.id == place_id
    ).first()

    nearest_course = get_group_course(group_courses, place_id)
    v_titles = []

    if place.videos:
        videos: List[Video] = Video.query.filter(
            Video.id.in_(place.videos)
        ).all()
        for v in videos:
            v_titles.append(v.title or '精彩视频')

    return {
        'videos': v_titles,
        'nearest_course': nearest_course,
        'id': Place.encode_id(place_id),
        'title': place.name
    }


def get_group_course(group_courses, place_id):
    group_courses = [group_course for group_course in group_courses if group_course.get('place_id') == place_id]
    nearest_course = get_nearest_course(group_courses)
    return nearest_course


def get_coaches(biz_id):
    res = []
    coaches: List[Coach] = Coach.query.filter(
        Coach.biz_id == biz_id,
        Coach.coach_type == 'private',
        Coach.in_service == true()
    ).all()
    max_count = 2
    if len(coaches) < max_count:
        max_count = len(coaches)

    random_set = set()
    for i in range(max_count):
        random_set.add(random.choice(coaches))

    for c in random_set:
        res.append(c.get_brief())

    return res


def get_videos(biz_id, max_count):
    res = []
    videos: List[Video] = Video.query.filter(
        Video.biz_id == biz_id,
        Video.is_valid == true()
    ).all()
    if len(videos) < max_count:
        max_count = len(videos)

    random_set = set()
    for i in range(max_count):
        random_set.add(random.choice(videos))

    for v in random_set:
        brief = v.get_brief()
        tags = get_mini_tags_data(v)
        thumb = get_thumb_count(v)
        brief.update({'tags': tags})
        res.append({
            'thumb': thumb,
            'brief': brief
        })

    return res


def get_check_in(biz_id, customer_id):
    record_util = RecordUtil(biz_id, customer_id)
    # 打卡
    is_check, check_hid = record_util.post_check_in()
    check_in_cache = CheckInCache(biz_id)
    cache_date = datetime.strptime(check_in_cache.get('date'), '%Y.%m.%d %H:%M:%S')
    now = datetime.now()
    today_min = tp.get_day_min(now)
    today_max = tp.get_day_max(datetime.today())
    if cache_date != today_min:
        # 只取当天的打卡信息
        check_in_cache.reload()

    briefs = check_in_cache.get('briefs')
    avatars = []
    for brief in briefs:
        check_in_customer_cache = CustomerCache(brief.get('customer_id'))
        avatars.append(check_in_customer_cache.get('avatar'))
    customer_cache = CustomerCache(customer_id)

    check_in: CheckIn = CheckIn.find(check_hid)
    customer_brief = {'customer_id': customer_id, 'check_in_time': check_in.check_in_date.strftime('%Y.%m.%d %H:%M:%S')}

    if customer_brief not in briefs:
        # 将该用户头像打卡信息存入缓存
        briefs.append(customer_brief)
        check_in_cache.set(k_v={'briefs': json.dumps(briefs)})
    if customer_cache.get('avatar') in avatars:
        avatars.remove(customer_cache.get('avatar'))

    check_in_count = db.session.query(func.count(CheckIn.customer_id)).filter(
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= today_min,
        CheckIn.check_in_date <= today_max
    ).scalar()
    return {
        'is_check': True,  # 前端直接显示已打卡
        'date': today_min.strftime("%Y/%m/%d"),
        'avatars': avatars[:7] if len(avatars) > 8 else avatars,  # 头像列表
        'avatar': customer_cache.get('avatar'),  # 每次摇一摇都返回当前用户的头像
        'count': check_in_count
    }


def get_articles():
    """ 返回推荐文章,该文章有后台随机获取,与biz_id无关 """
    articles = []

    return articles


def get_store_shake(biz_id, customer_id):
    max_videos = 4
    check_in = get_check_in(biz_id, customer_id)
    videos = get_videos(biz_id, max_videos)
    coaches = get_coaches(biz_id)
    articles = get_articles()
    place = get_place(biz_id)
    return {
        'check_in': check_in,
        'videos': videos,
        'coaches': coaches,
        'articles': articles,
        'place': place
    }


def get_home_shake(biz_id, customer_id):
    max_videos = 2
    videos = get_videos(biz_id, max_videos)
    coaches = get_coaches(biz_id)
    articles = get_articles()
    place = get_place(biz_id)
    today_min = tp.get_day_min(datetime.today())
    today_max = tp.get_day_max(datetime.today())
    check_in: CheckIn = CheckIn.query.filter(
        CheckIn.biz_id == biz_id,
        CheckIn.customer_id == customer_id,
        CheckIn.check_in_date >= today_min,
        CheckIn.check_in_date <= today_max,
    ).first()

    check_in_cache = CheckInCache(biz_id)
    briefs = check_in_cache.get('briefs')
    avatars = []
    for brief in briefs:
        check_in_customer_cache = CustomerCache(brief.get('customer_id'))
        avatars.append(check_in_customer_cache.get('avatar'))
    customer_cache = CustomerCache(customer_id)
    if customer_cache.get('avatar') in avatars:
        avatars.remove(customer_cache.get('avatar'))

    check_in_count = db.session.query(func.count(CheckIn.customer_id)).filter(
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= today_min,
        CheckIn.check_in_date <= today_max
    ).scalar()

    return {
        'check_in': {
            'is_check': bool(check_in),
            'date': today_min.strftime("%Y/%m/%d"),
            'avatars': avatars[:7] if len(avatars) > 8 else avatars,  # 头像列表
            'avatar': customer_cache.get('avatar'),  # 每次摇一摇都返回当前用户的头像
            'count': check_in_count
        },
        'videos': videos,
        'coaches': coaches,
        'articles': articles,
        'place': place
    }
