from flask import Blueprint
from flask import jsonify, request, g
from http import HTTPStatus
from sqlalchemy import desc, and_, asc

from store.domain.cache import StoreBizCache, CoachCache, CourseCache, GroupCoursesCache, PlaceCache
from store.domain.models import GroupTime, Course, Coach, GroupCourse, StoreBiz, Place
from store.domain.middle import roles_required, permission_required
from store.domain.permission import ViewBizPermission, ManageGroupCoursePermission
from store.database import db
from typing import List
from datetime import datetime, timedelta, date, time
from store.utils import time_processing as tp

blueprint = Blueprint('_group_course_v2', __name__)


@blueprint.route('', methods=['GET'])
@permission_required(ViewBizPermission())
def get_group_times():
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    if w_id:
        # 直接访问当前生效的课表详情
        return mini_get_group_courses(biz_id)

    public_courses: Course = Course.query.filter(and_(
        Course.biz_id == biz_id,
        Course.course_type == 'public'
    )).first()
    public_coaches: Coach = Coach.query.filter(and_(
        Coach.biz_id == biz_id,
        Coach.coach_type == 'public'
    )).first()
    if not public_courses:
        return jsonify(msg='请至-->团课编辑进行团课录入'), HTTPStatus.NOT_FOUND
    if not public_coaches:
        return jsonify(msg='请至-->教练编辑进行团课教练录入'), HTTPStatus.NOT_FOUND

    group_times: List[GroupTime] = GroupTime.query.filter(
        GroupTime.biz_id == biz_id
    ).order_by(desc(GroupTime.start_date)).all()
    if not group_times:
        return jsonify({
            "group_times": []
        })

    group_times_brief = get_group_times_brief(group_times)

    return jsonify({
        'group_times': group_times_brief
    })


@blueprint.route('/<string:g_t_id>', methods=['GET'])
@permission_required(ViewBizPermission())
def get_group_time(g_t_id):
    biz_id = g.get('biz_id')
    # 获取该用户点击的课表以及对应的时间表
    group_time: GroupTime = GroupTime.find(g_t_id)
    if not group_time:
        return jsonify(msg='团课课表不存在'), HTTPStatus.NOT_FOUND

    group_courses: List[GroupCourse] = GroupCourse.query.filter(and_(
        GroupCourse.biz_id == biz_id,
        GroupCourse.group_time_id == group_time.id
    )).order_by(GroupCourse.start_time).all()

    if not group_courses:
        return jsonify(msg='课程列表不存在'), HTTPStatus.NOT_FOUND

    res = get_place_courses(group_courses)
    start_date = group_time.start_date.strftime("%Y-%m-%d")
    return jsonify({
        'start_date': start_date,
        'g_c_l': res
    })


@blueprint.route('', methods=['POST'])
@permission_required(ManageGroupCoursePermission())
def post_group_time():
    biz_id = g.get('biz_id')
    group_time_data = request.get_json()
    if not group_time_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    start_date = group_time_data.get('start_date')
    group_courses_list = group_time_data.get('group_courses_list')
    if not all([start_date, group_courses_list]):
        return jsonify(msg='课表不能为空'), HTTPStatus.BAD_REQUEST

    group_time: GroupTime = GroupTime.query.filter(
        GroupTime.biz_id == biz_id,
        GroupTime.start_date == start_date
    ).first()
    if group_time:
        return jsonify(msg='所选生效日期已存在'), HTTPStatus.BAD_REQUEST
    try:
        group_time = GroupTime(
            biz_id=biz_id,
            start_date=start_date,
            created_at=datetime.now()
        )
        db.session.add(group_time)
        db.session.flush()
        db.session.refresh(group_time)
        # 拆包
        for gc in group_courses_list:
            # gc: {"place":"yoga",T_D:[[{"time":[s_t,e_t], "week0~6":{"coach":xx, "course":xx},..}]]
            # 获取每个场地的课程
            place_hid, group_courses = get_place_and_group_courses(gc)
            is_ok, msg = post_group_courses(biz_id, place_hid, group_courses, group_time.id)
            if not is_ok:
                return jsonify(msg='添加失败 {msg}'.format(msg=msg)), HTTPStatus.BAD_REQUEST

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e

    # 将生效的课表重新存入缓存
    group_time_list: List[GroupTime] = GroupTime.query.filter(and_(
        GroupTime.biz_id == biz_id,
    )).order_by(desc(GroupTime.start_date)).all()
    group_times_brief = get_group_times_brief(group_time_list)
    active_group_time_id = get_active(group_times_brief)
    if active_group_time_id:
        group_courses_cache = GroupCoursesCache(biz_id, active_group_time_id)
        group_courses_cache.reload()

    return jsonify(msg="发布成功")


@blueprint.route('/<string:g_t_id>', methods=['PUT'])
@permission_required(ManageGroupCoursePermission())
def put_group_time(g_t_id):
    biz_id = g.get('biz_id')
    group_time: GroupTime = GroupTime.find(g_t_id)
    if not group_time:
        return jsonify(msg='课表不存在'), HTTPStatus.BAD_REQUEST

    group_time_data = request.get_json()
    if not group_time_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    start_date = group_time_data.get('start_date')
    group_courses_list = group_time_data.get('group_courses_list')
    if not all([start_date, group_courses_list]):
        return jsonify(msg='课表不能为空'), HTTPStatus.BAD_REQUEST

    try:
        if datetime.strptime(start_date, '%Y-%m-%d') <= datetime.today():
            group_time.start_date = start_date
            GroupCourse.query.filter(GroupCourse.group_time_id == group_time.id).delete()
            # 拆包
            for gc in group_courses_list:
                # gc: {"place":"yoga",T_D:[[{"time":[s_t,e_t], "week0~6":{"coach":xx, "course":xx},..}]]
                # 获取每个场地的课程
                place_hid, group_courses = get_place_and_group_courses(gc)
                is_ok, msg = post_group_courses(biz_id, place_hid, group_courses, group_time.id)
                if not is_ok:
                    return jsonify(msg='修改失败 {msg}'.format(msg=msg)), HTTPStatus.BAD_REQUEST
        else:
            # 修改的生效日期大于今日, 则将新生成一张课表
            new_group_time = GroupTime(
                biz_id=biz_id,
                start_date=start_date,
                created_at=datetime.now()
            )
            db.session.add(new_group_time)
            db.session.flush()
            db.session.refresh(new_group_time)
            for gc in group_courses_list:
                # gc: {"place":"yoga",T_D:[[{"time":[s_t,e_t], "week0~6":{"coach":xx, "course":xx},..}]]
                # 获取每个场地的课程
                place_hid, group_courses = get_place_and_group_courses(gc)
                is_ok, msg = post_group_courses(biz_id, place_hid, group_courses, new_group_time.id)
                if not is_ok:
                    return jsonify(msg='修改失败 {msg}'.format(msg=msg)), HTTPStatus.BAD_REQUEST

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e

    # 将生效的课表重新存入缓存
    group_time_list: List[GroupTime] = GroupTime.query.filter(and_(
        GroupTime.biz_id == biz_id,
    )).order_by(desc(GroupTime.start_date)).all()
    group_times_brief = get_group_times_brief(group_time_list)
    active_group_time_id = get_active(group_times_brief)
    if active_group_time_id:
        group_courses_cache = GroupCoursesCache(biz_id, active_group_time_id)
        group_courses_cache.reload()

    return jsonify(msg='修改成功')


@blueprint.route('/<string:g_t_id>', methods=['DELETE'])
@permission_required(ManageGroupCoursePermission())
def delete_group_time(g_t_id):
    biz_id = g.get('biz_id')
    group_time: GroupTime = GroupTime.find(g_t_id)
    if not group_time:
        return jsonify(msg='课表不存在'), HTTPStatus.BAD_REQUEST

    group_time_list: List[GroupTime] = GroupTime.query.filter(and_(
        GroupTime.biz_id == biz_id,
    )).order_by(desc(GroupTime.start_date)).all()
    group_times_brief = get_group_times_brief(group_time_list)
    active_group_time_id = get_active(group_times_brief)

    if group_time.id == active_group_time_id:
        return jsonify(msg='该课表正在生效,无法删除'), HTTPStatus.BAD_REQUEST

    group_courses: List[GroupCourse] = GroupCourse.query.filter(and_(
        GroupCourse.group_time_id == group_time.id,
        GroupCourse.biz_id == biz_id
    )).all()

    if group_courses:
        for group_course in group_courses:
            db.session.delete(group_course)

    db.session.delete(group_time)
    db.session.commit()

    # # 将生效的课表重新存入缓存
    group_time_list: List[GroupTime] = GroupTime.query.filter(and_(
        GroupTime.biz_id == biz_id,
    )).order_by(desc(GroupTime.start_date)).all()
    group_times_brief = get_group_times_brief(group_time_list)
    active_group_time_id = get_active(group_times_brief)
    # 如果没有课表则获取不到id
    if active_group_time_id:
        group_courses_cache = GroupCoursesCache(biz_id, active_group_time_id)
        group_courses_cache.reload()

    return jsonify(msg="删除课程成功")


@blueprint.route('/courses/<string:course_id>', methods=['GET'])
@permission_required(ViewBizPermission())
def get_group_course_detail(course_id):
    biz_id = g.get('biz_id')
    course: Course = Course.find(course_id)
    if not course:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND

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

    group_courses = [group_course for group_course in group_courses if group_course.get('course_id') == course.id]
    group_courses.sort(key=lambda x: (x['week'], x['start_time']))

    res = [get_course_info(group_course) for group_course in group_courses]

    return jsonify(res)


@blueprint.route('/<string:g_t_id>/excel', methods=['GET'])
@permission_required(ViewBizPermission())
def get_excel(g_t_id):
    biz_id = g.get('biz_id')
    # 获取该用户点击的课表以及对应的时间表
    group_time: GroupTime = GroupTime.find(g_t_id)
    if not group_time:
        return jsonify(msg='团课课表不存在'), HTTPStatus.NOT_FOUND

    group_courses: List[GroupCourse] = GroupCourse.query.filter(and_(
        GroupCourse.biz_id == biz_id,
        GroupCourse.group_time_id == group_time.id
    )).order_by(GroupCourse.start_time).all()

    if not group_courses:
        return jsonify(msg='课程列表不存在'), HTTPStatus.NOT_FOUND
    res = get_place_courses_excel(group_courses)
    return jsonify(res)


def get_place_courses_excel(group_courses: list):
    res = []
    all_place = []
    for group_course in group_courses:
        if group_course.place_id not in all_place:
            all_place.append(group_course.place_id)

    for place_id in all_place:
        result = get_place_and_table_data_excel(place_id, group_courses)
        res.extend(result)
    return res


def get_place_and_table_data_excel(place_id, group_courses):
    place: Place = Place.query.filter(
        Place.id == place_id
    ).first()
    g_c = [group_course for group_course in group_courses if group_course.place_id == place_id]
    table_data = get_table_data_excel(g_c, place.name)
    return table_data


def get_table_data_excel(group_courses: list, place_name):
    res = []
    all_time_list = []
    for group_course in group_courses:
        if [group_course.start_time, group_course.end_time] not in all_time_list:
            all_time_list.append([group_course.start_time, group_course.end_time])

    for time_list in all_time_list:
        group_course_dict = get_group_course_dict_excel(time_list[0], time_list[1], group_courses)
        group_coach_dict = get_group_coach_dict_excel(time_list[0], time_list[1], group_courses)
        group_course_dict.update({'place': place_name})
        group_coach_dict.update({'place': place_name})
        res.append(group_course_dict)
        res.append(group_coach_dict)
    return res


def get_group_course_dict_excel(start_time, end_time, group_courses):
    w_id = g.get('w_id')
    courses = [group_course for group_course in group_courses if
               group_course.start_time == start_time and group_course.end_time == end_time]

    group_course_dict = {'time': formatting_time(start_time, w_id)+'-'+formatting_time(end_time, w_id)}
    for i in range(0, 7):
        group_course_dict.update({"week" + str(i): ''})

    for course in courses:
        course_cache = CourseCache(course.course_id)
        course_brief = course_cache.get('brief')
        week = course.week
        group_course_dict["week" + str(week)] = course_brief.get('title')

    return group_course_dict


def get_group_coach_dict_excel(start_time, end_time, group_courses):
    w_id = g.get('w_id')
    courses = [group_course for group_course in group_courses if
               group_course.start_time == start_time and group_course.end_time == end_time]

    group_coach_dict = {'time': formatting_time(start_time, w_id)+'-'+formatting_time(end_time, w_id)}
    for i in range(0, 7):
        group_coach_dict.update({"week" + str(i): ''})

    for course in courses:
        coach_cache = CoachCache(course.coach_id)
        coach_brief = coach_cache.get('brief')
        week = course.week
        group_coach_dict["week" + str(week)] = coach_brief.get('name')

    return group_coach_dict


def get_place_courses(group_courses: list):
    res = []
    all_place = []
    for group_course in group_courses:
        if group_course.place_id not in all_place:
            all_place.append(group_course.place_id)

    for place_id in all_place:
        result = get_place_and_table_data(place_id, group_courses)
        res.append(result)
    return res


def get_place_and_table_data(place_id, group_courses: list):
    place: Place = Place.query.filter(
        Place.id == place_id
    ).first()
    g_c = [group_course for group_course in group_courses if group_course.place_id == place_id]
    table_data = get_table_data(g_c)
    return {
        'place': place.get_name(),
        'tableDatas': table_data
    }


def get_table_data(group_courses: list):
    res = []
    all_time_list = []
    for group_course in group_courses:
        if [group_course.start_time, group_course.end_time] not in all_time_list:
            all_time_list.append([group_course.start_time, group_course.end_time])

    for time_list in all_time_list:
        group_course_dict = get_group_course_dict(time_list[0], time_list[1], group_courses)
        res.append(group_course_dict)
    return [res]


def get_group_course_dict(start_time, end_time, group_courses):
    w_id = g.get('w_id')
    courses = [group_course for group_course in group_courses if
               group_course.start_time == start_time and group_course.end_time == end_time]

    group_course_dict = {'time': [formatting_time(start_time, w_id), formatting_time(end_time, w_id)]}
    week_dict = dict()
    for i in range(0, 7):
        group_course_dict.update({"week" + str(i): week_dict})
        week_dict["coach"] = ""
        week_dict["course"] = ""
        week_dict["coach_id"] = ""
        week_dict["course_id"] = ""

    for course in courses:
        coach_cache = CoachCache(course.coach_id)
        course_cache = CourseCache(course.course_id)
        coach_brief = coach_cache.get('brief')
        course_brief = course_cache.get('brief')
        week = course.week
        week_dict = {
            'coach': coach_brief.get('name'),
            'coach_id': coach_brief.get('id'),
            'course': course_brief.get('title'),
            'course_id': course_brief.get('id')
        }
        group_course_dict["week" + str(week)] = week_dict

    return group_course_dict


def get_place_and_group_courses(gc: dict):
    # gc: {"place":"yoga",T_D:[[{"time":[s_t,e_t], "week0~6":{"coach":xx, "course":xx},..}]]
    w_id = g.get('w_id')
    place = gc.get('place')
    place_hid = place.get('id')
    table_datas = gc.get('tableDatas')[0]
    group_courses = []
    for table_data in table_datas:
        course_time_list = table_data.get('time')
        if not course_time_list:
            # TODO 如果用户不小心把时间去掉
            continue
        start_time = get_course_time(course_time_list[0])
        end_time = get_course_time(course_time_list[1])
        i = 0
        while i < 7:
            week_dict = table_data.get('week' + str(i))
            coach_hid = week_dict.get('coach_id')
            course_hid = week_dict.get('course_id')
            group_course = {
                'start_time': formatting_time(start_time, w_id),
                'end_time': formatting_time(end_time, w_id),
                'week': i,
                'coach_hid': coach_hid,
                'course_hid': course_hid,
            }
            group_courses.append(group_course)
            i += 1

    return place_hid, group_courses


def formatting_time(t, w_id=None):
    t_hour = t // 60
    if t_hour < 10:
        # 小程序中与pc端显示不同
        if w_id:
            t_hour = "%d" % t_hour
        else:
            t_hour = '%02d' % t_hour
    t_min = t % 60
    if t_min < 10:
        t_min = "%02d" % t_min
    t = str(t_hour) + ":" + str(t_min)
    return t


def post_group_courses(biz_id, place_hid, group_courses, group_time_id):
    now = datetime.now()
    place: Place = Place.find(place_hid)
    if not place:
        return False, '场地不存在'
    for group_course in group_courses:
        start_time = group_course.get('start_time')
        end_time = group_course.get('end_time')
        week = group_course.get('week')
        coach_hid = group_course.get('coach_hid')
        course_hid = group_course.get('course_hid')
        if course_hid or coach_hid:
            course: Course = Course.find(course_hid)
            coach: Coach = Coach.find(coach_hid)
            if not course:
                return False, '请为当前的教练选择课程'
            if not coach:
                return False, '请为当前的课程选择教练'
            g_c = GroupCourse()
            g_c.biz_id = biz_id
            g_c.group_time_id = group_time_id
            g_c.place_id = place.id
            g_c.start_time = get_course_time(start_time)
            g_c.end_time = get_course_time(end_time)
            g_c.week = week
            g_c.course_id = course.id
            g_c.coach_id = coach.id
            g_c.created_at = now
            db.session.add(g_c)
    db.session.commit()
    return True, '添加成功'


def get_course_time(time_str):
    c_time = int(time_str[0:2]) * 60 + int(time_str[3:])
    return c_time


def get_group_times_brief(group_times):
    first_end_date = '开始生效'
    last_start_date = ''  # 上一个开始时间
    res = []
    now = datetime.now()
    for i, group_time in enumerate(group_times):
        if i == 0:
            end_date = first_end_date
        else:
            end_date = last_start_date

        last_start_date = group_time.start_date - timedelta(days=1)
        group_time_brief = get_group_time_brief(group_time, end_date, now)
        res.append(group_time_brief)
    return res


def get_active(group_times_brief):
    """ 获取正在生效的课表 """
    for group_time_brief in group_times_brief:
        if group_time_brief.get('is_active'):
            group_course_id = group_time_brief['id']
            group_time = GroupTime.find(group_course_id)
            group_time_id = group_time.id
            return group_time_id
    return None


def get_group_time_brief(group_time, end_date, now):
    start_date = tp.get_day_min(group_time.start_date)
    if end_date == "开始生效":
        end_date = tp.get_day_max(datetime.today())
        end_date_str = "开始生效"
    else:
        end_date = tp.get_day_max(end_date)
        end_date_str = datetime.strftime(end_date, '%Y.%m.%d')

    if start_date <= now <= end_date:
        is_active = True
    else:
        is_active = False

    # 转换为str给前端显示

    return {
        'id': group_time.get_hash_id(),
        'start_date': datetime.strftime(group_time.start_date, '%Y.%m.%d'),
        'end_date': end_date_str,
        'is_active': is_active
    }


def mini_get_group_courses(biz_id):
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

    res = [[] for i in range(0, 7)]
    for week, week_list in enumerate(res):
        mini_get_week_group_courses(group_courses, week, week_list)

    return jsonify(res)


def mini_get_week_group_courses(group_courses, week, week_list):
    # 每周的课程
    places_list = list()
    for group_course in group_courses:
        place = group_course.get('place_id')
        if place not in places_list:
            places_list.append(place)

    for place_id in places_list:
        place_courses = [group_course for group_course in group_courses if
                         group_course.get('place_id') == place_id and group_course.get('week') == week]

        has_courses, week_courses = get_week_courses(place_id, place_courses)
        if has_courses:
            week_list.append(week_courses)

    return


def get_week_courses(place_id, place_courses):
    w_id = g.get('w_id')
    place_cache = PlaceCache(place_id)
    place = place_cache.get('name')
    table_datas = []
    now = datetime.now()
    week = tp.get_week(now)
    for g_course in place_courses:
        g_week = g_course.get('week')
        coach_id = g_course.get('coach_id')
        course_id = g_course.get('course_id')
        coach_cache = CoachCache(coach_id)
        course_cache = CourseCache(course_id)
        start_time = formatting_time(g_course.get('start_time'), w_id)
        end_time = formatting_time(g_course.get('end_time'), w_id)
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
                "price": course_brief.get('price'),
                "image": course_brief.get('image')
            },
            "time": time_str,
            "desc": course_brief.get('content')[0]['text'] if course_brief.get('content') else '',
            "is_action": bool(week == g_week and g_course.get('start_time') <= (now.hour * 60 + now.minute) <= g_course.get('end_time'))
        }
        table_datas.append(course_dict)
    if table_datas:
        res = {
            "place": {
                'id': Place.encode_id(place_id),
                'name': place
            },
            "tableDatas": table_datas
        }
        return True, res

    return False, None


def get_course_info(group_course):
    w_id = g.get('w_id')
    coach_cache = CoachCache(group_course.get('coach_id'))
    start_time = formatting_time(group_course.get('start_time'), w_id)
    end_time = formatting_time(group_course.get('end_time'), w_id)
    time_str = start_time + "-" + end_time
    coach_brief = coach_cache.get('brief')
    place_id = group_course.get('place_id')
    place_cache = PlaceCache(place_id)
    group_course_info = {
        "place": place_cache.get('name'),
        "coach": {
            "name": coach_brief.get('name'),
            "avatar": coach_brief.get('image'),
        },
        "day": group_course.get('week'),
        "time": time_str,
    }
    return group_course_info


@blueprint.route('/upgrade', methods=['PUT'])
@permission_required(ManageGroupCoursePermission())
def upgrade_group_courses():
    # 此接口只用于旧版本的团课场地迁移
    biz_id = g.get('biz_id')
    group_times: List[GroupTime] = GroupTime.query.filter(
        GroupTime.biz_id == biz_id
    ).filter()

    for group_time in group_times:
        group_courses: List[GroupCourse] = GroupCourse.query.filter(
            GroupCourse.group_time_id == group_time.id
        ).all()
        for group_course in group_courses:
            place_id = get_place_id(biz_id, group_course.place)
            group_course.place_id = place_id

            db.session.commit()
    return jsonify()


def get_place_id(biz_id, name):
    place: Place = Place.query.filter(
        Place.biz_id == biz_id,
        Place.name == name
    ).first()
    if place:
        return place.id
    return -1
