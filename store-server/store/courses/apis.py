import math

import copy
from flask import Blueprint
from flask import jsonify, request, g
from http import HTTPStatus
from sqlalchemy import and_
from sqlalchemy.sql.expression import false, true, desc, asc
from datetime import datetime
from store.database import db
from store.domain.middle import roles_required, permission_required, hide_course_videos
from store.domain.permission import ViewBizPermission, EditStorePermission
from store.domain.role import CustomerRole, CoachRole, AdminRole, UNDEFINED_BIZ_ID
from typing import List
from store.domain.models import Course, Store, StoreBiz, GroupTime, GroupCourse, Place
from store.domain.cache import StoreBizCache, CourseCache
from store.domain.helper import CourseIndex
from store.videos.utils import check_video_info, get_mini_tags_data, get_thumb_count, get_thumbs_brief

blueprint = Blueprint('_course', __name__)


@blueprint.route('/admin', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def admin_course():
    c_data = request.get_json()
    if not c_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    c_id = c_data['id']

    course: Course = Course.query.filter(and_(
        Course.id == c_id
    )).first()

    now = datetime.now()

    if not course:
        course = Course(
            id=c_id,
            created_at=now
        )
        db.session.add(course)
    course.biz_id = c_data['biz_id']
    course.title = c_data['title']
    course.price = c_data.get('price')
    course.images = c_data['images']
    course.content = c_data['content']
    course.modified_at = now
    if c_data.get('type'):
        course.course_type = c_data['type']
    db.session.commit()

    course_cache = CourseCache(c_id)
    course_cache.reload()
    return jsonify()


@blueprint.route('', methods=['GET'])
@permission_required(ViewBizPermission())
def get_courses():
    biz_id = g.get('biz_id')
    course_type = request.args.get('type')
    if course_type == 'public':
        group_courses: List[Course] = Course.query.filter(and_(
            Course.biz_id == biz_id,
            Course.course_type == course_type,
        )).order_by(asc(Course.created_at)).all()
        courses = [group_course.get_brief() for group_course in group_courses]
        return jsonify({
            'courses': courses
        })

    biz_cache = StoreBizCache(biz_id)
    return jsonify({
        'courses': biz_cache.courses
    })


@blueprint.route('/<string:c_id>', methods=['GET'])
@permission_required(ViewBizPermission())
def get_course(c_id):
    biz_id = g.get('biz_id')
    course: Course = Course.find(c_id)
    if not course:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND

    course_type = course.course_type
    if course_type == 'public':
        return jsonify({
            'course': course.get_page()
        })
    index = CourseIndex(biz_id=biz_id).find(course.id)
    page = course.get_page()
    page.update({'index': index})
    return jsonify({
        'course': page
    })


@blueprint.route('', methods=['POST'])
@permission_required(EditStorePermission())
def post_courses():
    biz_id = g.get('biz_id')
    c_data = request.get_json()
    if not c_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    if 'title' not in c_data:
        return jsonify(msg='missing title'), HTTPStatus.BAD_REQUEST

    if 'images' not in c_data or c_data.get('images') is False:
        return jsonify(msg='missing images'), HTTPStatus.BAD_REQUEST

    now = datetime.now()
    course = Course(
        biz_id=biz_id,
        created_at=now,
        title=c_data['title'],
        price=c_data.get('price'),
        images=c_data['images'],
        content=c_data.get('content'),
        course_type=c_data.get('type'),
        modified_at=now
    )

    db.session.add(course)
    db.session.commit()

    db.session.refresh(course)
    course_cache = CourseCache(course.id)
    course_cache.reload()
    if c_data.get('type') == 'private':  # 只对私教课进行排序
        n_index = CourseIndex(biz_id=biz_id).add(course.id)
    else:
        return jsonify({
            'course': course.get_page()
        })
    page = course.get_page()
    page.update({'index': n_index})
    return jsonify({
        'course': page
    })


@blueprint.route('/<string:c_id>', methods=['PUT'])
@permission_required(EditStorePermission())
def put_course(c_id):
    biz_id = g.get('biz_id')
    c_data = request.get_json()
    if not c_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    course: Course = Course.find(c_id)
    if not course:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND

    now = datetime.now()
    if 'title' in c_data:
        course.title = c_data['title']
    if 'price' in c_data:
        course.price = c_data['price']
    if 'images' in c_data:
        course.images = c_data['images']
    if 'content' in c_data:
        course.content = c_data['content']
    if 'type' in c_data:
        course.course_type = c_data['type']

    course.modified_at = now
    db.session.commit()
    db.session.refresh(course)

    course_cache = CourseCache(course.id)
    course_cache.reload()
    store_biz_cache = StoreBizCache(biz_id=biz_id)
    store_biz_cache.reload()
    if course.course_type == 'public':
        return jsonify({
            'course': course.get_page()
        })

    index = CourseIndex(biz_id=biz_id).find(course.id)
    page = course.get_page()
    page.update({'index': index})
    return jsonify({
        'course': page
    })


@blueprint.route('/<string:c_id>', methods=['DELETE'])
@permission_required(EditStorePermission())
def delete_course(c_id):
    biz_id = g.get('biz_id')
    course: Course = Course.find(c_id)
    if not course:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND

    if course.course_type == 'public':
        try:
            # 若当前删除的课程存在于课表中时允许删除,但是要提示用户
            # 删除该课程会将所有团课课表中的该课程删除
            group_times: List[GroupTime] = GroupTime.query.filter(
                GroupTime.biz_id == biz_id
            ).order_by(desc(GroupTime.start_date)).all()
            for group_time in group_times:
                GroupCourse.query.filter(
                    GroupCourse.group_time_id == group_time.id,
                    GroupCourse.course_id == course.id
                ).delete()

            # 将所有场地中的这节课删除
            delete_place_course(biz_id, course.id)
            # 删除所有视频中该课程的tag
            delete_course_video_tags(course)
            # 最后 将这节课程从course表中删除
            db.session.delete(course)
        except Exception as e:
            db.session.rollback()
            raise e
    else:
        # 删除所有视频中该课程的tag
        delete_course_video_tags(course)
        course_cache = CourseCache(course.id)
        course_cache.delete()
        CourseIndex(biz_id=biz_id).delete(course.id)
        # 最后 将这节课程从course表中删除
        db.session.delete(course)
    db.session.commit()
    return jsonify({
        "page": course.get_page()
    })


@blueprint.route('/<string:c_id>/index/<int:n_index>', methods=['POST'])
@permission_required(EditStorePermission())
def post_course_index(c_id, n_index):
    biz_id = g.get('biz_id')
    course: Course = Course.find(c_id)
    if not course:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND
    try:
        CourseIndex(biz_id=biz_id).update(course.id, n_index)
        return jsonify()
    except IndexError:
        return jsonify(msg='invalid index range'), HTTPStatus.BAD_REQUEST


@blueprint.route('/<string:c_id>/videos', methods=['GET'])
@roles_required()
@hide_course_videos()
def get_course_videos(c_id):
    course: Course = Course.find(c_id)
    if not course:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND
    page = request.args.get('page', default=1, type=int)
    page_size = request.args.get('page_size', default=10, type=int)
    # 抓取所有带有该课程标签的视频
    videos = course.get_videos()
    total_page = math.ceil(len(videos) / page_size)
    if page > total_page:
        return jsonify({
            'videos': [],
            'page_count': total_page
        })
    if page == 1:
        if not videos:
            # 第一页没有数据说明没有发布过视频
            return jsonify({'videos': []})
        videos = videos[:page_size]
    else:
        videos = videos[(page - 1) * page_size: (page - 1) * page_size + page_size]

    res = []
    for video in videos:
        video = check_video_info(video)  # 校验视频信息(封面图等)
        video_brief = video.get_brief()
        tags = get_mini_tags_data(video)
        thumb_count = get_thumb_count(video)
        avatars, nick_names = get_thumbs_brief(video)
        video_brief.update({'tags': tags})
        res.append({
            'video': video_brief,
            'thumb_count': thumb_count,
            'avatars': avatars,
            'nick_names': nick_names,
        })

    return jsonify({
        'videos': res,
        'page_count': total_page
    })


def delete_course_video_tags(course):
    # 抓取所有带有该课程标签的视频
    videos = course.get_videos()
    for v in videos:
        new_tags = copy.deepcopy(v.tags)
        new_video_courses = copy.deepcopy(v.courses)
        if course.id in new_video_courses:
            new_video_courses.remove(course.id)
        for t in new_tags:
            if t.get('type') == 'course':
                t.get('ids').remove(course.get_hash_id())
        v.tags = new_tags
        v.coaches = new_video_courses
    db.session.commit()


def delete_place_course(biz_id, course_id):
    places: List[Place] = Place.query.filter(
        Place.biz_id == biz_id
    ).all()
    courses = [place.courses for place in places]
    for index, c in enumerate(courses):
        if c:
            if course_id in c:
                place_courses = copy.deepcopy(places[index].courses)
                place_courses.remove(course_id)
                places[index].courses = place_courses
    return
