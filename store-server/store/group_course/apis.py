from flask import Blueprint
from flask import jsonify, request, g
from http import HTTPStatus
from sqlalchemy import desc, and_, asc

from store.domain.cache import StoreBizCache, CoachCache, CourseCache, GroupCoursesCache
from store.domain.models import GroupTime, Course, Coach, GroupCourse, StoreBiz, Place
from store.domain.middle import roles_required, permission_required
from store.domain.permission import ViewBizPermission, ManageGroupCoursePermission
from store.database import db
from typing import List
from datetime import datetime, timedelta, date, time
from store.utils import time_processing as tp


blueprint = Blueprint('_group_course', __name__)


@blueprint.route('', methods=['GET'])
@permission_required(ViewBizPermission())
def get_group_course_list():
    """
    团课列表页面
    """
    biz_id = g.get('biz_id')
    if not biz_id:
        biz_hid = request.headers.get('biz_id')
        biz_id = StoreBiz.find(biz_hid).id

    # 判断是否是小程序
    w_id = g.get('w_id')
    if w_id:
        return mini_get_group_courses()

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

    group_time_list: List[GroupTime] = GroupTime.query.filter(and_(
        GroupTime.biz_id == biz_id,
    )).order_by(desc(GroupTime.start_date)).all()

    if group_time_list:
        group_courses = get_active(group_time_list)
    else:
        group_courses = []
    return jsonify({
        'group_courses_list': group_courses
    })


def get_active(group_time_list):
    flag = 0
    end_date_dict = dict()
    group_courses = list()
    now = datetime.now()
    for group_time in group_time_list:

        date_dict = dict()

        start_date = group_time.start_date

        if flag == 0:
            date_dict['end_date'] = '开始生效'
            flag += 1
            end_date = group_time.start_date - timedelta(days=1)
            end_date_dict['last_end_date'] = datetime.strftime(end_date, '%Y.%m.%d')

        else:
            date_dict['end_date'] = end_date_dict['last_end_date']

        date_dict['start_date'] = datetime.strftime(start_date, '%Y.%m.%d')
        date_dict['group_course_id'] = group_time.get_hash_id()
        date_dict['active'] = active(start_date, date_dict['end_date'], now)
        # 将本次的结束时间保存到last_end_dict
        end_date = group_time.start_date - timedelta(days=1)
        end_date_dict['last_end_date'] = datetime.strftime(end_date, '%Y.%m.%d')
        group_courses.append(date_dict)

    return group_courses


def active(start_date, end_date, now):
    start_date = datetime(year=start_date.year, month=start_date.month, day=start_date.day)
    if end_date == "开始生效":
        end_date = datetime.combine(date.today(), time.max)
    else:
        end_date = datetime.strptime(end_date, '%Y.%m.%d')
        end_date = tp.get_day_max(end_date)

    if start_date <= now <= end_date:
        return True
    else:
        return False


def formatting_time(start_time, end_time):

    start_hour = start_time // 60
    end_hour = end_time // 60

    if start_hour < 10:
        start_hour = "%02d" % start_hour
    if end_hour < 10:
        end_hour = "%02d" % end_hour

    start_min = start_time % 60
    end_min = end_time % 60

    if start_min < 10:
        start_min = "%02d" % start_min
    if end_min < 10:
        end_min = "%02d" % end_min

    start_time = str(start_hour) + ":" + str(start_min)
    end_time = str(end_hour) + ":" + str(end_min)

    return start_time, end_time


def compare_time(tableDatas, table_dates_dict, week):
    for i, j in enumerate(tableDatas[0]):
        if j["time"] == table_dates_dict["time"]:
            j["week" + str(week)] = table_dates_dict["week" + str(week)]
            return "kill"


def get_group_course_info(group_course, global_time_list):

    # {"start_date": Datetime, "g_c_l":[{"place":"yoga",T_D:[[{"time":[s_t,e_t], "week1":{"coach":xx, "course":xx}},
    #   {"time":[s_t, e_t], "week2":{}, ... }, {...}, {...},]]}]}

    group_course_dict = dict()  # g_c_l dict
    table_dates_list = list()  # inside list
    table_dates_dict = dict()
    time_list = list()
    week_dict = dict()
    group_course_dict["place"] = group_course.place
    group_course_dict["tableDatas"] = list()
    group_course_dict["tableDatas"].append(table_dates_list)
    table_dates_dict["time"] = time_list

    for i in range(0, 7):
        table_dates_dict["week"+str(i)] = week_dict
        week_dict["coach"] = ""
        week_dict["course"] = ""
        week_dict["coach_id"] = ""
        week_dict["course_id"] = ""

    start_time, end_time = formatting_time(group_course.start_time, group_course.end_time)
    week = group_course.week
    coach_cache = CoachCache(group_course.coach_id)
    course_cache = CourseCache(group_course.course_id)
    time_list.append(start_time.strip("%H:%M"))
    time_list.append(end_time)

    if time_list not in global_time_list:
        global_time_list.append(time_list)
    coach_brief = coach_cache.get('brief')
    course_brief = course_cache.get('brief')
    week_dict = {
        'coach': coach_brief.get('name'),
        'coach_id': coach_brief.get('id'),
        'course': course_brief.get('title'),
        'course_id': course_brief.get('id')
    }
    table_dates_dict["week" + str(week)] = week_dict
    table_dates_list.append(table_dates_dict)

    return group_course_dict, table_dates_dict


@blueprint.route('/<string:g_t_id>', methods=['GET'])
@permission_required(ViewBizPermission())
def show_group_course(g_t_id):
    """
    团课详情页面
    :param g_t_id: group_time_id
    :return:
    """
    biz_id = g.get('biz_id')

    w_id = g.get('w_id')
    if w_id:
        return mini_get_course_list(g_t_id)

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

    all_dict = dict()
    g_c_l = list()
    place_list = list()
    global_time_list = list()

    all_dict['start_date'] = group_time.start_date.strftime("%Y-%m-%d")
    for group_course in group_courses:

        group_course_dict, table_dates_dict = get_group_course_info(group_course, global_time_list)

        if group_course.place not in place_list:
            place_list.append(group_course.place)
            g_c_l.append(group_course_dict)
        else:
            for i, j in enumerate(g_c_l):
                if j["place"] == group_course.place:
                    flag = compare_time(j["tableDatas"], table_dates_dict, group_course.week)
                    g_c_l[i]["tableDatas"][0].append(table_dates_dict)
                    if flag == "kill":
                        del g_c_l[i]["tableDatas"][0][-1]

    all_dict["g_c_l"] = g_c_l
    return jsonify(all_dict)


@blueprint.route('', methods=['POST'])
@permission_required(ManageGroupCoursePermission())
def post_group_course():
    """提交团课"""
    biz_id = g.get('biz_id')

    all_dict = request.get_json()
    # 获取数据
    if not all_dict:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    # {"start_date": Datetime, "g_c_l":[{"place":"yoga",T_D:[[{"time":[s_t,e_t], "week0~6":{"coach":xx, "course":xx},..}
    # ,{"time":[s_t, e_t], "week0~6":{}, ... }, {...}, {...},]]}]}

    start_date = all_dict["start_date"]
    group_courses = all_dict["group_courses_list"]
    group_time = GroupTime(
        biz_id=biz_id,
        start_date=start_date,
        created_at=datetime.now()
    )

    if not all([start_date, group_courses]):
        # 校验参数是否完整
        return jsonify(msg="课表不能为空"), HTTPStatus.BAD_REQUEST

    # 拆包
    try:
        db.session.add(group_time)
        db.session.flush()
        db.session.refresh(group_time)
        for group_course_info in group_courses:
            place = group_course_info["place"]
            if place == "":
                return jsonify(msg="场地不能为空"), HTTPStatus.BAD_REQUEST
            tableDatas = group_course_info["tableDatas"]
            for table_dates_dict in tableDatas[0]:
                # 排序
                time_list = table_dates_dict["time"]
                start_time = int(time_list[0][0:2]) * 60 + int(time_list[0][3:])
                end_time = int(time_list[-1][0:2]) * 60 + int(time_list[-1][3:])
                i = 0
                while i < 7:
                    week_dict = table_dates_dict["week" + str(i)]
                    group_course = GroupCourse()
                    course_id = week_dict.get("course_id")
                    coach_id = week_dict.get("coach_id")
                    if course_id and coach_id:
                        course: Course = Course.find(course_id)
                        coach: Coach = Coach.find(coach_id)

                        if not course:
                            return jsonify(msg='请为当前的教练选择课程'), HTTPStatus.BAD_REQUEST
                        if not coach:
                            return jsonify(msg='请为当前的课程选择教练'), HTTPStatus.BAD_REQUEST

                        group_course.biz_id = biz_id
                        group_course.group_time_id = group_time.id
                        group_course.place = place
                        group_course.start_time = start_time
                        group_course.end_time = end_time
                        group_course.week = i
                        group_course.course_id = course.id
                        group_course.coach_id = coach.id
                        group_course.created_at = datetime.now()

                        db.session.add(group_course)
                    i += 1
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e

    # 将生效的课表重新存入缓存
    group_time_list: List[GroupTime] = GroupTime.query.filter(and_(
        GroupTime.biz_id == biz_id,
    )).order_by(desc(GroupTime.start_date)).all()
    active_list = get_active(group_time_list)
    active_group_time_id = mini_get_active(active_list)
    group_courses_cache = GroupCoursesCache(biz_id, active_group_time_id)
    group_courses_cache.reload()

    return jsonify(msg="发布成功")


@blueprint.route('/<string:g_t_id>', methods=['PUT'])
@permission_required(ManageGroupCoursePermission())
def put_group_course(g_t_id):
    biz_id = g.get('biz_id')

    all_dict = request.get_json()
    if not all_dict:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    group_courses_info = all_dict["group_courses_list"]
    start_date = all_dict.get('start_date')
    # 校验团课ID是否为New
    if g_t_id == "New":
        return jsonify(msg='Error request'), HTTPStatus.BAD_REQUEST

    # 根据团课ID查询课表
    group_time: GroupTime = GroupTime.find(g_t_id)
    if not group_time:
        return jsonify(msg='课表不存在'), HTTPStatus.NOT_FOUND

    if start_date:
        group_time.start_date = datetime.strptime(start_date, '%Y-%m-%d')
        db.session.commit()
    group_courses: List[GroupCourse] = GroupCourse.query.filter(
        GroupCourse.group_time_id == group_time.id
    ).all()

    try:
        for group_course in group_courses:
            db.session.delete(group_course)
        now = datetime.now()
        for group_course_info in group_courses_info:
            place = group_course_info["place"]
            if place == "":
                return jsonify(msg="场地不能为空"), HTTPStatus.BAD_REQUEST
            tableDatas = group_course_info["tableDatas"]
            for table_dates_dict in tableDatas[0]:
                # 排序
                time_list = table_dates_dict["time"]
                start_time = int(time_list[0][0:2]) * 60 + int(time_list[0][3:])
                end_time = int(time_list[-1][0:2]) * 60 + int(time_list[-1][3:])
                i = 0
                while i < 7:
                    week_dict = table_dates_dict["week" + str(i)]
                    course_id = week_dict.get("course_id")
                    coach_id = week_dict.get("coach_id")
                    if course_id and coach_id:

                        course: Course = Course.find(week_dict.get("course_id"))
                        coach: Coach = Coach.find(week_dict.get("coach_id"))

                        if not course:
                            return jsonify(msg='请为当前的教练选择课程'), HTTPStatus.BAD_REQUEST
                        if not coach:
                            return jsonify(msg='请为当前的课程选择教练'), HTTPStatus.BAD_REQUEST

                        # 修改
                        group_course = GroupCourse(
                            biz_id=biz_id,
                            group_time_id=group_time.id,
                            place=place,
                            start_time=start_time,
                            end_time=end_time,
                            week=i,
                            course_id=course.id,
                            coach_id=coach.id,
                            created_at=now
                        )

                        db.session.add(group_course)
                    i += 1
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e

    # 将生效的课表重新存入缓存
    group_time_list: List[GroupTime] = GroupTime.query.filter(and_(
        GroupTime.biz_id == biz_id,
    )).order_by(desc(GroupTime.start_date)).all()
    active_list = get_active(group_time_list)
    active_group_time_id = mini_get_active(active_list)
    # 如果没有课表则获取不到id
    if active_group_time_id:
        group_courses_cache = GroupCoursesCache(biz_id, active_group_time_id)
        group_courses_cache.reload()
    return jsonify(msg="修改成功")


@blueprint.route('/<string:g_t_id>', methods=['DELETE'])
@permission_required(ManageGroupCoursePermission())
def delete_group_course(g_t_id):
    biz_id = g.get('biz_id')

    group_time: GroupTime = GroupTime.find(g_t_id)

    if not group_time:
        return jsonify(msg='课表不存在'), HTTPStatus.BAD_REQUEST

    group_courses: List[GroupCourse] = GroupCourse.query.filter(and_(
        GroupCourse.group_time_id == group_time.id,
        GroupCourse.biz_id == biz_id)).all()

    if group_courses:
        for group_course in group_courses:
            db.session.delete(group_course)

    db.session.delete(group_time)
    db.session.commit()

    # 将生效的课表重新存入缓存
    group_time_list: List[GroupTime] = GroupTime.query.filter(and_(
        GroupTime.biz_id == biz_id,
    )).order_by(desc(GroupTime.start_date)).all()
    active_list = get_active(group_time_list)
    active_group_time_id = mini_get_active(active_list)
    # 如果没有课表则获取不到id
    if active_group_time_id:
        group_courses_cache = GroupCoursesCache(biz_id, active_group_time_id)
        group_courses_cache.reload()

    return jsonify(msg="删除课程成功")


def mini_get_group_courses():
    biz_id = g.get('biz_id')

    # 获取课表
    group_time_list: List[GroupTime] = GroupTime.query.filter(
        GroupTime.biz_id == biz_id
    ).order_by(desc(GroupTime.start_date)).all()

    active_list = get_active(group_time_list=group_time_list)
    group_time_id = mini_get_active(active_list=active_list)
    if not group_time_id:
        return jsonify(msg='尚无团课信息'), HTTPStatus.NOT_FOUND

    group_courses_cache = GroupCoursesCache(biz_id, group_time_id)
    group_courses = group_courses_cache.get('group_courses')
    if not group_courses:
        group_courses_cache.reload()
        group_courses = group_courses_cache.get('group_courses')
    # [[{"place":xx, "tableDatas":[{"avatar":教练头像url, "courseTitle":"xx", "coachName":"xx",
    # "courseDesc":"xx", "courseID":"xx", "time":"start_time-end_time"},{...},...]}], [], [], [], [], [], []]
    all_list = list()
    place_list = list()
    all_week_list = list()
    for group_course in group_courses:
        course_dict = mini_get_course_dict(group_course)
        if group_course.get('week') not in all_week_list:
            week_list = mini_get_week_list(all_list, all_week_list, group_course)
            del place_list[:]
            mini_merge_place(place_list, week_list, group_course, course_dict)
        else:
            mini_merge_place(place_list, week_list, group_course, course_dict)

    if len(all_week_list) != 7:
        # 如果7天内出现没有课的情况下插入一个空的列表
        i = 0
        while i < 7:
            if i not in all_week_list:
                all_list.insert(i, list())
            i += 1

    return jsonify(all_list)


def mini_get_course_list(course_id):
    biz_id = g.get('biz_id')

    # 根据课程ID获取所有课程列表
    course: Course = Course.find(course_id)
    if not course:
        return jsonify("课程不存在"), HTTPStatus.NOT_FOUND

    group_time_list: List[GroupTime] = GroupTime.query.filter(
        GroupTime.biz_id == biz_id
    ).order_by(desc(GroupTime.start_date)).all()
    active_list = get_active(group_time_list=group_time_list)
    group_time_id = mini_get_active(active_list=active_list)

    group_course_list: List[GroupCourse] = GroupCourse.query.filter(and_(
        GroupCourse.course_id == course.id,
        GroupCourse.biz_id == biz_id,
        GroupCourse.group_time_id == group_time_id
    )).order_by(asc(GroupCourse.week), desc(GroupCourse.place), asc(GroupCourse.start_time)).all()

    # 遍历列表取出每节课
    courses = list()
    for group_course in group_course_list:
        group_course_info = mini_get_course_info(group_course)
        courses.append(group_course_info)

    return jsonify(courses)


def mini_get_active(active_list):
    for active_dict in active_list:
        if active_dict['active']:
            group_course_id = active_dict['group_course_id']
            group_time = GroupTime.find(group_course_id)
            group_time_id = group_time.id
            return group_time_id
    return None


def mini_get_course_dict(group_course):
    coach_cache = CoachCache(group_course.get('coach_id'))
    course_cache = CourseCache(group_course.get('course_id'))
    start_time, end_time = formatting_time(group_course.get('start_time'), group_course.get('end_time'))
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

    return course_dict


def mini_get_week_list(all_list, all_week_list, group_course):
    # 创建week_list
    week_list = list()
    # 将新的week添加到all_week_list中
    all_week_list.append(group_course.get('week'))
    # 将新的week_list添加到all_list中
    all_list.append(week_list)

    return week_list


def mini_merge_place(place_list, week_list, group_course, course_dict):

    if group_course.get('place') not in place_list:
        # 创建新的group_course_dict
        group_course_dict = {
            "place": group_course.get('place'),
            "tableDatas": []
        }
        # 将新的地点添加到place_list中
        place_list.append(group_course.get('place'))
        group_course_dict["tableDatas"].append(course_dict)
        week_list.append(group_course_dict)
    else:
        # 遍历已有的week_list
        for group_course_dict in week_list:
            if group_course_dict["place"] == group_course.get('place'):
                group_course_dict["tableDatas"].append(course_dict)


def mini_get_course_info(group_course):
    coach_cache = CoachCache(group_course.coach_id)
    start_time, end_time = formatting_time(group_course.start_time, group_course.end_time)
    time_str = start_time + "-" + end_time
    coach_brief = coach_cache.get('brief')
    group_course_info = {
        "place": group_course.place,
        "coach": {
            "name": coach_brief.get('name'),
            "avatar": coach_brief.get('image'),
        },
        "day": group_course.week,
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
