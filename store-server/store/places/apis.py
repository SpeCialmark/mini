import math
from datetime import datetime
from http import HTTPStatus
from typing import List

import copy
from flask import Blueprint
from flask import jsonify, request, g
from sqlalchemy import desc, true, asc
from store.config import cfg, _env
from store.database import db
from store.domain.cache import CourseCache, CustomerCache, StoreBizCache, GroupCoursesCache, CoachCache, PlaceCache
from store.domain.middle import permission_required, roles_required, hide_place_videos
from store.domain.models import Place, Video, Thumb, WxOpenUser, Course, Qrcode, GroupTime
from store.domain.permission import ViewBizPermission, ManagePlacePermission
from store.places.utils import generate_place_base
from store.domain.wxapp import PlaceQrcode
from store.group_course_v2.apis import get_group_times_brief, get_active, formatting_time
from store.utils.oss import encode_app_id, bucket
from store.utils import time_processing as tp
from store.videos.utils import check_video_info, get_uploader, get_mini_tags_data, get_thumb_count

blueprint = Blueprint('_places', __name__)


@blueprint.route('', methods=['GET'])
@permission_required(ViewBizPermission())
def get_places():
    biz_id = g.get('biz_id')
    places = Place.get_biz_places(biz_id)

    return jsonify({
        "places": places
    })


@blueprint.route('/<string:p_id>', methods=['GET'])
@permission_required(ViewBizPermission())
def get_place(p_id):
    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND

    return jsonify({
        'name': place.get_name()['name']
    })


@blueprint.route('', methods=['POST'])
@permission_required(ManagePlacePermission())
def post_place():
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    store_biz_cache = StoreBizCache(biz_id)
    customer_app_id = store_biz_cache.get('customer_app_id')
    if not customer_app_id:
        # 不授权则无法生成场地码因此直接拒绝其添加场地
        return jsonify(msg='没有授权的小程序'), HTTPStatus.NOT_FOUND

    name = json_data.get('name')
    if not name:
        return jsonify(msg='请输入场地名'), HTTPStatus.BAD_REQUEST

    old_place: Place = Place.query.filter(
        Place.biz_id == biz_id,
        Place.name == name
    ).first()
    if old_place:
        return jsonify(msg='该场地已存在'), HTTPStatus.BAD_REQUEST

    place = Place(
        biz_id=biz_id,
        name=name,
        created_at=datetime.now()
    )

    db.session.add(place)
    db.session.commit()
    db.session.refresh(place)

    # 为新添加的场地生成场地小程序码
    PlaceQrcode(place_name=place.name, place_hid=place.encode_id(place.id), app_id=customer_app_id).generate()

    return jsonify(msg='新增成功')


@blueprint.route('/<string:p_id>', methods=['PUT'])
@permission_required(ManagePlacePermission())
def put_place(p_id):
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    store_biz_cache = StoreBizCache(biz_id)
    customer_app_id = store_biz_cache.get('customer_app_id')
    if not customer_app_id:
        # 不授权则无法生成场地码因此直接拒绝其修改场地
        return jsonify(msg='没有授权的小程序'), HTTPStatus.NOT_FOUND

    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND

    name = json_data.get('name')
    place.name = name
    db.session.commit()

    # 重新生成带场地名称的场地码
    qrcode = PlaceQrcode(place_name=place.name, place_hid=place.encode_id(place.id), app_id=customer_app_id).get()
    generate_place_base(qrcode=qrcode, place_name=place.name, place_hid=place.get_hash_id(),
                        app_hid=encode_app_id(customer_app_id))

    place_cache = PlaceCache(place.id)
    place_cache.reload()

    return jsonify(msg='修改成功')


# @blueprint.route('/places/<string:p_id>', methods=['DELETE'])
# @permission_required(EditStorePermission())
# def delete_place(p_id):
#
#     return


@blueprint.route('/<string:p_id>/courses', methods=['GET'])
@permission_required(ViewBizPermission())
def get_place_courses(p_id):
    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND

    courses = []
    if place.courses:
        courses = [CourseCache(course).get('brief') for course in place.courses]
    return jsonify({
        'courses': courses
    })


@blueprint.route('/<string:p_id>/courses', methods=['POST'])
@permission_required(ManagePlacePermission())
def post_place_courses(p_id):
    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    courses = json_data.get('courses')
    try:
        courses = [Course.find(course_hid).id for course_hid in courses]
    except Exception as e:
        return jsonify(msg='添加课程失败'), HTTPStatus.BAD_REQUEST
    place.courses = courses
    db.session.commit()

    return jsonify(msg='添加成功')


@blueprint.route('/<string:p_id>/courses/<c_id>', methods=['DELETE'])
@permission_required(ManagePlacePermission())
def delete_place_course(p_id, c_id):
    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND
    course: Course = Course.find(c_id)
    if not course:
        return jsonify(msg='课程不存在'), HTTPStatus.BAD_REQUEST
    if course.id not in place.courses:
        return jsonify(msg='该课程不存在于该场地中'), HTTPStatus.BAD_REQUEST
    new_place_courses = copy.deepcopy(place.courses)
    new_place_courses.remove(course.id)
    place.courses = new_place_courses
    db.session.commit()

    return jsonify(msg='删除成功')


@blueprint.route('/<string:p_id>/videos', methods=['GET'])
@permission_required(ViewBizPermission())
@hide_place_videos()
def get_place_videos(p_id):
    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND

    page = request.args.get('page', default=1, type=int)
    page_size = request.args.get('page_size', default=10, type=int)

    videos = place.get_videos()
    total_page = math.ceil(len(videos) / page_size)
    if page > total_page:
        return jsonify({'videos': []})
    if page == 1:
        if not videos:
            # 第一页没有数据说明没有发布过视频
            return jsonify({'videos': []})
        videos = videos[:page_size]
    else:
        videos = videos[(page - 1) * page_size: (page - 1) * page_size + page_size]

    res = []
    w_id = g.get('w_id')
    if w_id:
        # 移动端
        w_user: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.id == w_id
        ).first()
        if not w_user:
            return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND
        customer_id = w_user.customer_id
        if videos:
            for video in videos:
                video = check_video_info(video)  # 校验视频信息(封面图等)
                thumb = get_thumb(video, customer_id)
                uploader = get_uploader(video)
                res.append({
                    'video': video.get_brief(),
                    'thumb': thumb,
                    'uploader': uploader,
                })
        return jsonify({
            'videos': res,
            'page_count': total_page,  # 总页数
            # 'next': videos.has_next
        })

    if videos:
        for video in videos:
            check_video_info(video)
            thumbs = get_thumb_count(video)
            uploader = get_uploader(video)
            uploader_name = uploader.get('name')
            upload_time = uploader.get('upload_time')
            size = "%.1fM" % video.size
            duration = video.get_duration()
            res.append({
                "video": {
                    'title': video.title,
                    'url': video.url,
                    'file_id': video.file_id,
                    'poster': video.poster
                },
                'uploader': uploader_name,
                'uploadTime': upload_time,
                'duration': duration,
                'size': size,
                'thumbs': thumbs
            })
    return jsonify({
        'videos': res,
        'page_count': total_page,  # 总页数
        # 'next': videos.has_next
    })


@blueprint.route('/<string:p_id>/qrcode', methods=['GET'])
@roles_required()
def get_place_qrcode(p_id):
    biz_id = g.get('biz_id')
    store_biz_cache = StoreBizCache(biz_id)
    customer_app_id = store_biz_cache.get('customer_app_id')
    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND

    qrcode: Qrcode = PlaceQrcode(place_name=place.name, place_hid=p_id, app_id=customer_app_id).get()

    file_name = 'place_{place_hid}.png'.format(place_hid=place.get_hash_id())
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=encode_app_id(customer_app_id), file_name=file_name)
    if _env == 'dev':
        key = 'dev/' + key
    image_url = cfg['aliyun_oss']['host'] + '/' + key

    exist = bucket.object_exists(key)  # 查看文件是否存在
    if not exist:
        image_url = generate_place_base(qrcode=qrcode, place_name=place.name, place_hid=place.get_hash_id(),
                                        app_hid=encode_app_id(customer_app_id))

    return jsonify({
        'place_qrcode': qrcode.get_brief()['url'],
        'place_qrcode_cover': image_url
    })


@blueprint.route('/<string:p_id>/qrcode', methods=['PUT'])
@roles_required()
def put_place_qrcode(p_id):
    biz_id = g.get('biz_id')
    store_biz_cache = StoreBizCache(biz_id)
    customer_app_id = store_biz_cache.get('customer_app_id')
    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND

    qrcode: Qrcode = PlaceQrcode(place_name=place.name, place_hid=p_id, app_id=customer_app_id).generate()
    cover_url = generate_place_base(qrcode, place.name, place.get_hash_id(), encode_app_id(customer_app_id))

    return jsonify({
        'place_qrcode': qrcode.get_brief()['url'],
        'place_qrcode_cover': cover_url
    })


@blueprint.route('/<string:p_id>/detail', methods=['GET'])
@permission_required(ViewBizPermission())
@hide_place_videos()
def get_place_detail(p_id):
    # 获取场地视频列表以及团课课表
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    page = request.args.get('page', 1, type=int)  # 默认显示第一页的数据
    page_size = request.args.get('page_size', 10, type=int)  # 每页显示条数(pc端与小程序不同)

    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND

    w_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.id == w_id
    ).first()
    if not w_user:
        return jsonify(msg='账号异常'), HTTPStatus.BAD_REQUEST

    group_times: List[GroupTime] = GroupTime.query.filter(
        GroupTime.biz_id == biz_id
    ).order_by(desc(GroupTime.start_date)).all()

    group_times_brief = get_group_times_brief(group_times)
    active_group_time_id = get_active(group_times_brief)
    if not active_group_time_id:
        return jsonify(msg='尚无团课信息'), HTTPStatus.NOT_FOUND

    group_courses_cache = GroupCoursesCache(biz_id, active_group_time_id)
    group_courses = group_courses_cache.get('group_courses')
    if not group_courses:
        group_courses_cache.reload()
        group_courses = group_courses_cache.get('group_courses')

    group_courses = [group_course for group_course in group_courses if group_course.get('place_id') == place.id]

    nearest_course = get_nearest_course(group_courses)
    videos = place.get_videos()
    total_page = math.ceil(len(videos) / page_size)
    if page > total_page:
        return jsonify({
            'videos': [],
            'page_count': total_page,
            'nearest_course': nearest_course,
        })
    if page == 1:
        if not videos:
            # 第一页没有数据说明没有发布过视频
            return jsonify({
                'videos': [],
                'page_count': total_page,
                'nearest_course': nearest_course,
            })
        videos = videos[:page_size]
    else:
        videos = videos[(page - 1) * page_size: (page - 1) * page_size + page_size]

    res = []
    for video in videos:
        brief = video.get_brief()
        tags = get_mini_tags_data(video)
        thumb = get_thumb(video, w_user.customer_id)
        brief.update({'tags': tags})
        res.append({
            'video': brief,
            'thumb': thumb,
        })
    return jsonify({
        'videos': res,
        'nearest_course': nearest_course,
        'page_count': total_page
    })


@blueprint.route('/<string:p_id>/group_course', methods=['GET'])
@permission_required(ViewBizPermission())
def get_place_group_course(p_id):
    biz_id = g.get('biz_id')
    place: Place = Place.find(p_id)
    if not place:
        return jsonify(msg='场地不存在'), HTTPStatus.NOT_FOUND

    group_times: List[GroupTime] = GroupTime.query.filter(
        GroupTime.biz_id == biz_id
    ).order_by(desc(GroupTime.start_date)).all()

    group_times_brief = get_group_times_brief(group_times)
    active_group_time_id = get_active(group_times_brief)
    if not active_group_time_id:
        return jsonify(msg='尚无团课信息'), HTTPStatus.NOT_FOUND

    group_courses_cache = GroupCoursesCache(biz_id, active_group_time_id)
    group_courses = group_courses_cache.get('group_courses')
    if not group_courses:
        group_courses_cache.reload()
        group_courses = group_courses_cache.get('group_courses')

    group_courses = [group_course for group_course in group_courses if group_course.get('place_id') == place.id]
    place_courses = dict()
    for i in range(0, 7):
        courses = get_courses_dict(group_courses, i)
        place_courses.update({'week%d' % i: courses})

    return jsonify({
        'place_courses': place_courses
    })


def get_nearest_course(group_courses):
    now = datetime.now()
    today_min = tp.get_day_min(datetime.today())
    now_int = now.hour * 60 + now.minute
    week = tp.get_week(now)
    # 正在上的课
    now_courses = [g_course for g_course in group_courses if
                   g_course.get('start_time') <= now_int <= g_course.get('end_time') and
                   g_course.get('week') == week]
    # 即将要上的课
    next_courses = []
    for g_course in group_courses:
        g_course_date = tp.transform_week_to_date(g_course.get('week'))
        if g_course_date == today_min and g_course.get('start_time') > now_int:
            next_courses.append(g_course)
        elif g_course_date > today_min:
            next_courses.append(g_course)

    # 按照距离当下最近的一天排序,同天的情况下按照课程的开始时间排序
    next_courses.sort(key=lambda x: (tp.transform_week_to_date(x['week'])-today_min, x['start_time']))

    if len(now_courses) > 0:
        course = now_courses[0]
        coach_cache = CoachCache(course.get('coach_id'))
        course_cache = CourseCache(course.get('course_id'))

        course_brief = course_cache.get('brief')
        coach_brief = coach_cache.get('brief')

        start_time = formatting_time(course.get('start_time'))
        end_time = formatting_time(course.get('end_time'))
        date_str = "今天 " + start_time + "-" + end_time
        return {
            "title": course_brief.get('title'),
            "image": course_brief.get('image'),
            "coach_name": coach_brief.get('name'),
            "date_str": date_str,
            "action": '正在上课'
        }

    if len(next_courses) == 0:
        return {}
    course = next_courses[0]
    coach_cache = CoachCache(course.get('coach_id'))
    course_cache = CourseCache(course.get('course_id'))

    course_brief = course_cache.get('brief')
    coach_brief = coach_cache.get('brief')

    start_time = formatting_time(course.get('start_time'))
    end_time = formatting_time(course.get('end_time'))
    if tp.transform_week_to_date(course.get('week')) - today_min == 1:
        date_str = "明天 " + start_time + "-" + end_time
    else:
        date_str = "周{week} ".format(week=tp.transform_week_chstr(course.get('week'))) + start_time + "-" + end_time
    return {
        "title": course_brief.get('title'),
        "image": course_brief.get('image'),
        "coach_name": coach_brief.get('name'),
        "date_str": date_str,
        "action": '即将上课'
    }


def get_courses_dict(group_courses, week):
    group_courses = [group_course for group_course in group_courses if group_course.get('week') == week]
    courses = []
    for g_course in group_courses:
        coach_id = g_course.get('coach_id')
        course_id = g_course.get('course_id')
        coach_cache = CoachCache(coach_id)
        course_cache = CourseCache(course_id)
        start_time = formatting_time(g_course.get('start_time'))
        end_time = formatting_time(g_course.get('end_time'))
        time_str = start_time + "-" + end_time
        coach_brief = coach_cache.get('brief')
        course_brief = course_cache.get('brief')
        course_dict = {
            "coach": {
                "name": coach_brief.get('name'),
                "avatar": coach_brief.get('image'),
            },
            "course": {
                "title": course_brief.get('title'),
                "id": course_brief.get('id'),
                "type": course_brief.get('type'),
                "price": course_brief.get('price')
            },
            "time": time_str,
            "desc": course_brief.get('content')[0]['text'] if course_brief.get('content') else ''
        }
        courses.append(course_dict)
    return courses


def get_thumb(video, customer_id):
    thumbs: List[Thumb] = Thumb.query.filter(
        Thumb.video_id == video.id
    ).order_by(asc(Thumb.created_at)).all()
    if not thumbs:
        return {
            'avatars': [],
            'thumb_count': 0,
            'is_thumb': False
        }

    res = {'thumb_count': len(thumbs), 'is_thumb': False}
    avatars = []
    nick_names = []
    for thumb in thumbs:
        c_cache = CustomerCache(thumb.customer_id)
        avatar, nick_name = c_cache.get('avatar', 'nick_name')
        avatars.append(avatar)
        nick_names.append(nick_name)
        if thumb.customer_id == customer_id:
            res.update({'is_thumb': True})
    res.update({'avatars': avatars, 'nick_names': nick_names})
    return res
