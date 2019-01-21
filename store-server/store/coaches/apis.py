import math
from flask import Blueprint, current_app
from flask import jsonify, request, g
from http import HTTPStatus
from sqlalchemy import and_, desc, true, func, false, asc, or_
from datetime import datetime, timedelta
from store.database import db
from store.domain.middle import roles_required, permission_required, hide_coach_videos
from store.domain.permission import ViewBizPermission, ManagePrivateCoachPermission, ManagePublicCoachPermission, \
    EditCoachItemPermission, get_permissions_name, ViewBizWebPermission
from store.domain.role import AdminRole, UNDEFINED_BIZ_ID, CustomerRole, CoachRole, ManagerRole
from store.group_course.apis import get_active, mini_get_active
from store.domain.models import Store, Coach, Course, StoreBiz, GroupTime, GroupCourse, Trainee, MonthReport, Seat, \
    SeatStatus, SeatPriority, BizUser, BizStaff, WxOpenUser, PhotoWall
from store.domain.cache import StoreBizCache, CoachCache, TraineeCache, CustomerCache, get_default_coach_permission, \
    WxOpenUserCache, BizUserCache
from typing import List
import copy
from store.domain.helper import CoachIndex
import re
from store.utils import time_processing as tp
from store.utils.time_formatter import get_yymmdd, yymm_to_datetime
from store.videos.utils import get_thumb_count, get_thumbs_brief, check_video_info, get_mini_tags_data

blueprint = Blueprint('_coaches', __name__)


@blueprint.route('/admin', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def admin_coach():
    c_data = request.get_json()
    if not c_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    c_id = c_data['id']

    coach: Coach = Coach.query.filter(and_(
        Coach.id == c_id
    )).first()

    now = datetime.now()

    if not coach:
        coach = Coach(
            id=c_id,
            created_at=now
        )
        db.session.add(coach)
    coach.biz_id = c_data['biz_id']
    coach.name = c_data['name']
    coach.images = c_data['images']
    coach.good_at = c_data['good_at']
    coach.content = c_data['content']
    coach.trainer_cases = c_data.get('trainer_cases')
    coach.courses = c_data.get('courses')
    coach.modified_at = now
    db.session.commit()

    coach_cache = CoachCache(c_id)
    coach_cache.reload()
    return jsonify()


@blueprint.route('', methods=['GET'])
@permission_required(ViewBizPermission())
def get_coaches():
    biz_id = g.get('biz_id')
    coach_type = request.args.get('type')
    service_type = request.args.get('service_type')
    if service_type == 'not_in_service':
        coaches: List[Coach] = Coach.query.filter(and_(
            Coach.biz_id == biz_id,
            Coach.in_service == false()
        )).all()
        return jsonify({
            'coaches': [coach.get_brief() for coach in coaches]
        })
    if coach_type == 'public':
        public_coaches: List[Coach] = Coach.query.filter(and_(
            Coach.coach_type == coach_type,
            Coach.biz_id == biz_id,
            Coach.in_service == true()
        )).order_by(Coach.created_at).all()
        coaches = [public_coach.get_brief() for public_coach in public_coaches]
        return jsonify({
            'coaches': coaches
        })

    # 私教直接读缓存
    # 缓存中只有在职教练
    biz_cache = StoreBizCache(biz_id)
    return jsonify({
        'coaches': biz_cache.coaches
    })


@blueprint.route('/<string:c_id>', methods=['GET'])
@permission_required(ViewBizPermission())
def get_coach(c_id):
    biz_id = g.get('biz_id')

    if g.get('biz_user_id'):
        service_type = request.args.get('service_type')
        # 网页端
        coach: Coach = Coach.find(c_id)
        if not coach:
            return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
        coach_type = coach.coach_type
        if coach_type == 'public':
            page = coach.get_page()
        else:
            page = coach.get_page()
            if service_type != 'not_in_service':
                index = CoachIndex(biz_id=biz_id).find(coach.id)
                page.update({'index': index})
        return jsonify({
            'coach': page
        })

    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)  # 小助手端角色为教练
    if customer_id or coach_id:
        if c_id == '0':
            true_id = CoachIndex(biz_id=biz_id).get_first()
            if not true_id:
                return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
            coach: Coach = Coach.get(true_id)
            page = coach.get_page()
            page.update({'index': 0})
        else:
            coach: Coach = Coach.find(c_id)
            if not coach:
                return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
            coach_type = coach.coach_type
            if coach_type == 'public':
                page = coach.get_page()
            else:
                index = CoachIndex(biz_id=biz_id).find(coach.id)
                page = coach.get_page()
                page.update({'index': index})

        # 获取用户是否可以约体验课
        # 只要有绑定过的私教就不算体验会员
        trainee: Trainee = Trainee.query.filter(and_(
            Trainee.customer_id == customer_id,
            Trainee.is_bind == true(),
        )).first()
        on = coach.exp_reservation
        if trainee:
            # 绑定了教练说明是私教会员
            # 查询是否是该教练的私教会员
            trainee: Trainee = Trainee.query.filter(and_(
                Trainee.customer_id == customer_id,
                Trainee.is_bind == true(),
                Trainee.coach_id == coach.id
            )).first()
            if trainee:
                # 私教会员
                reservation = 'private'
            else:
                reservation = 'null'
        else:
            if on:
                reservation = 'exp'
            else:
                reservation = 'null'
        # 显示照片墙前八张图片
        photo_wall: List[PhotoWall] = PhotoWall.query.filter(
            PhotoWall.coach_id == coach.id
        ).order_by(desc(PhotoWall.created_at)).all()
        photos = [p.photo for p in photo_wall]
        page.update({"photo_wall": photos[:8]})
        return jsonify({
            'coach': page,
            'reservation': reservation
        })
    else:
        return jsonify(msg='unknown role'), HTTPStatus.BAD_REQUEST


@blueprint.route('', methods=['POST'])
@roles_required()
def post_coaches():
    biz_id = g.get('biz_id')

    c_data = request.get_json()
    if not c_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST
    coach_type = c_data.get('type')
    name = c_data.get('name')
    images = c_data.get('images')
    if not coach_type or coach_type == "":
        return jsonify(msg='missing type'), HTTPStatus.BAD_REQUEST

    if not name or name == "":
        return jsonify(msg='missing name'), HTTPStatus.BAD_REQUEST

    # if not images or images == "":
    #     return jsonify(msg='missing images'), HTTPStatus.BAD_REQUEST

    permission: set = g.get('permission')
    if coach_type == 'private':
        manage_private = ManagePrivateCoachPermission(biz_id=biz_id).to_tuple()
        if manage_private not in permission:
            return jsonify(), HTTPStatus.FORBIDDEN
        # 非团课的时候需要以下参数
        good_at = c_data.get('good_at')
        phone_number = c_data.get('phone_number')
        content = c_data.get('content')
        avatar = c_data.get('avatar')
        cover = c_data.get('cover')

        if not avatar or avatar == "":
            return jsonify(msg='missing avatar'), HTTPStatus.BAD_REQUEST

        if not cover or cover == "":
            return jsonify(msg='missing cover'), HTTPStatus.BAD_REQUEST

        if not phone_number or phone_number == "":
            return jsonify(msg='missing phone_number'), HTTPStatus.BAD_REQUEST

        if phone_number:
            m = re.match('^\d{11}$', str(phone_number))
            if not m:
                return jsonify(msg='手机号码格式错误'), HTTPStatus.BAD_REQUEST

        old_coach: Coach = Coach.query.filter(and_(
            Coach.biz_id == biz_id,
            Coach.coach_type == 'private',
            or_(
                Coach.name == name,
                Coach.phone_number == phone_number
            )
        )).first()
        if old_coach:
            return jsonify(msg='姓名或电话号码重复'), HTTPStatus.BAD_REQUEST

        now = datetime.now()
        coach = Coach(
            biz_id=biz_id,
            created_at=now,
            in_service=True,
            coach_type=coach_type
        )

        coach.name = name
        coach.images = images
        coach.avatar = avatar
        coach.cover = cover
        coach.good_at = good_at
        coach.content = content
        coach.phone_number = phone_number

        coach.trainer_cases = c_data.get('trainer_cases')
        courses = c_data.get('courses')
        courses_data = []
        if courses:
            for c in courses:
                h_id = c.get('id')
                course: Course = Course.find(h_id)
                if course:
                    courses_data.append({'id': course.id})

        coach.courses = courses_data
        coach.modified_at = now

        db.session.add(coach)
        db.session.flush()
        db.session.refresh(coach)

        # 新增教练的时候赋予默认权限
        permissions = get_default_coach_permission(biz_id=biz_id, coach_id=coach.id)
        coach.permission_list = get_permissions_name(permissions, coach.biz_id)
        db.session.commit()
        db.session.refresh(coach)

        coach_cache = CoachCache(coach.id)
        coach_cache.reload()
        # 进行排序
        n_index = CoachIndex(biz_id=biz_id).add(coach.id)
        # 添加的是私教,同步添加一条staff数据
        add_staff(coach)
        page = coach.get_page()
        page.update({'index': n_index})

        return jsonify({
            'coach': page
        })

    elif coach_type == 'public':
        manage_public = ManagePublicCoachPermission(biz_id=biz_id).to_tuple()
        if manage_public not in permission:
            return jsonify(), HTTPStatus.FORBIDDEN
        now = datetime.now()
        coach = Coach(
            biz_id=biz_id,
            created_at=now,
            in_service=True,
            coach_type=coach_type
        )

        coach.name = name
        coach.images = images
        db.session.add(coach)
        db.session.commit()
        db.session.refresh(coach)

        return jsonify({
            'coach': coach.get_page()
        })

    else:
        return jsonify(msg='非法的type'), HTTPStatus.BAD_REQUEST


@blueprint.route('/<string:c_id>', methods=['PUT'])
@roles_required()
def put_coach(c_id):
    coach: Coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND

    biz_id = g.get('biz_id')

    permission: set = g.get('permission')
    if coach.coach_type == 'private':
        manage_coach_permission = ManagePrivateCoachPermission(biz_id=biz_id).to_tuple()
    elif coach.coach_type == 'public':
        manage_coach_permission = ManagePublicCoachPermission(biz_id=biz_id).to_tuple()
    else:
        return jsonify(msg='wrong type'), HTTPStatus.BAD_REQUEST

    edit_coach_item_permission = EditCoachItemPermission(biz_id=biz_id, object_id=coach.id).to_tuple()

    if not(manage_coach_permission in permission or edit_coach_item_permission in permission):
        return jsonify(), HTTPStatus.FORBIDDEN

    c_data = request.get_json()
    if not c_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    now = datetime.now()
    old_name = coach.name
    old_phone_number = coach.phone_number

    if 'name' in c_data:
        if c_data['name'] != old_name:
            new_name = c_data['name']
            same_name_coach: Coach = Coach.query.filter(
                Coach.biz_id == biz_id,
                Coach.name == new_name,
                Coach.in_service == true()
            ).first()
            if same_name_coach:
                return jsonify(msg='该姓名已经被录入过了'), HTTPStatus.BAD_REQUEST
            coach.name = new_name
    if 'images' in c_data:
        coach.images = c_data['images']
    if 'good_at' in c_data:
        coach.good_at = c_data['good_at']
    if 'content' in c_data:
        coach.content = c_data['content']
    if 'trainer_cases' in c_data:
        coach.trainer_cases = c_data['trainer_cases']
    if 'phone_number' in c_data:
        new_phone_number = c_data['phone_number']
        if new_phone_number:
            m = re.match('^\d{11}$', str(new_phone_number))
            if not m:
                return jsonify(msg='手机号码格式错误'), HTTPStatus.BAD_REQUEST
        if new_phone_number != old_phone_number:
            same_phone_coach: Coach = Coach.query.filter(
                Coach.biz_id == biz_id,
                Coach.phone_number == new_phone_number,
                Coach.in_service == true()
            ).first()
            if same_phone_coach:
                return jsonify(msg='该电话号码已经被录入过了'), HTTPStatus.BAD_REQUEST
            change_staff_phone_number(biz_id, coach.phone_number, new_phone_number)
            coach.phone_number = new_phone_number
    if 'type' in c_data:
        coach.coach_type = c_data['type']

    if c_data.get('courses'):
        courses = c_data.get('courses')
        courses_data = []
        for c in courses:
            h_id = c.get('id')
            course: Course = Course.find(h_id)
            if course:
                courses_data.append({'id': course.id})

        coach.courses = courses_data

    if 'avatar' in c_data:
        coach.avatar = c_data.get('avatar')

    if 'cover' in c_data:
        coach.cover = c_data.get('cover')

    coach.modified_at = now
    db.session.commit()

    db.session.refresh(coach)
    coach_cache = CoachCache(coach.id)
    coach_cache.reload()
    if coach.coach_type == 'public':
        return jsonify({
            'coach': coach.get_page()
        })

    page = coach.get_page()
    if coach.in_service:
        index = CoachIndex(biz_id=biz_id).find(coach.id)
        page.update({'index': index})
    return jsonify({
        'coach': page
    })


@blueprint.route('/<string:c_id>', methods=['DELETE'])
@roles_required()
def delete_coach(c_id):
    biz_id = g.get('biz_id')

    coach: Coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND

    permission: set = g.get('permission')

    if coach.coach_type == 'public':
        manage_public = ManagePublicCoachPermission(biz_id=biz_id).to_tuple()
        if manage_public not in permission:
            return jsonify(), HTTPStatus.FORBIDDEN
    if coach.coach_type == 'private':
        manage_private = ManagePrivateCoachPermission(biz_id=biz_id).to_tuple()
        if manage_private not in permission:
            return jsonify(), HTTPStatus.FORBIDDEN

    # 若当前删除的教练存在于正在使用的课表中时不能删除
    # 获取正在生效的课表
    group_time_list: GroupTime = GroupTime.query.filter(
        GroupTime.biz_id == biz_id). \
        order_by(desc(GroupTime.start_date)).all()
    active_list = get_active(group_time_list=group_time_list)
    group_time_id = mini_get_active(active_list=active_list)

    group_course: GroupCourse = GroupCourse.query.filter(and_(
        GroupCourse.group_time_id == group_time_id,
        GroupCourse.coach_id == coach.id
    )).first()

    if group_course:
        return jsonify(msg='该教练正在授课中,无法删除'), HTTPStatus.BAD_REQUEST
    delete_staff(coach)  # 去除该成员的私教角色
    coach.in_service = False  # 改为离职
    # delete permissions
    coach.permission_list = [ViewBizPermission.name]
    coach.not_in_service_at = datetime.now()

    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.coach_id == coach.id
    ).first()
    if wx_open_user:
        wx_open_user_cache = WxOpenUserCache(app_id=wx_open_user.app_id, open_id=wx_open_user.wx_open_id)
        wx_open_user_cache.logout()

    coach_cache = CoachCache(coach.id)
    coach_cache.delete()
    if coach.coach_type != 'public':
        CoachIndex(biz_id=biz_id).delete(coach.id)

    # 清除视频tags
    delete_coach_video_tags(coach)
    # 最后才commit
    db.session.commit()
    if coach.coach_type == 'private':
        # 只需要刷新私教的token
        biz_user_cache = BizUserCache(website='11train', phone_number=coach.phone_number)
        biz_user_cache.reload()
    return jsonify()


@blueprint.route('/<string:c_id>/in_service', methods=['PUT'])
@roles_required(ManagerRole())
def update_coach(c_id):
    biz_id = g.get('biz_id')
    coach: Coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg="该教练不存在"), HTTPStatus.NOT_FOUND
    coach.in_service = True
    permissions = get_default_coach_permission(biz_id, coach.id)
    permission_list = get_permissions_name(permissions, biz_id, coach.id)
    coach.permission_list = permission_list
    db.session.commit()
    db.session.refresh(coach)
    restore_staff(coach)
    n_index = CoachIndex(biz_id=biz_id).add(coach.id)
    biz_cache = StoreBizCache(biz_id)
    biz_cache.reload()
    biz_user_cache = BizUserCache(website='11train', phone_number=coach.phone_number)
    biz_user_cache.reload()
    return jsonify()


@blueprint.route('/<string:c_id>/index/<int:n_index>', methods=['POST'])
@permission_required(ManagePrivateCoachPermission())
def post_coach_index(c_id, n_index):
    biz_id = g.get('biz_id')

    coach: Coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND

    try:
        CoachIndex(biz_id=biz_id).update(coach.id, n_index)
        return jsonify()
    except IndexError:
        return jsonify(msg='invalid index range'), HTTPStatus.BAD_REQUEST


@blueprint.route('/<string:c_id>/month_report', methods=['GET'])
@roles_required(CoachRole())  # TODO 让boss端也可以访问
def get_month_report(c_id):
    """ 教练月报 """
    # c_id的提供可以让boss端方便的访问教练月报
    coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND

    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)

    if not (year or month):
        return jsonify(msg='missing year or month'), HTTPStatus.BAD_REQUEST

    coach_cache = CoachCache(coach.id)
    brief = coach_cache.get('brief')
    yymm = year * 100 + month

    # 先查询是否有已经自动生成好的月报，如果没有则返回当下的数据
    month_report: MonthReport = MonthReport.query.filter(and_(
        MonthReport.coach_id == coach.id,
        MonthReport.yymm == yymm,
    )).first()
    valid_month = get_valid_month(coach.id)
    if month_report:
        return jsonify({
            'coach': {
                'name': brief['name'],
                'avatar': brief['image'],
            },
            'exp_count': month_report.exp_count,
            'private_count': month_report.private_count,
            'month_total_lesson': month_report.total_lesson,
            'average_lesson': "%.1f" % month_report.average,
            'ranking': month_report.trainee_ranking,
            'valid_month': valid_month
        })

    early_month = datetime(year, month, 1)
    exp_count = get_exp_count(coach.id, early_month)  # 体验会员人数
    private_count = get_private_count(coach.id)  # 会员总数
    month_total_lesson = get_total_lesson(coach.id, year, month)
    ranking = get_ranking(coach.id, year, month)

    today = tp.get_day_min(datetime.today())
    # 如果当前的日期的月份大于查看月报的月份
    if today.month > month:
        days = tp.get_day_of_month(early_month)
    else:
        # 如果查看的月份与当下的月份一样
        days = datetime.today().day

    return jsonify({
        'coach': {
            'name': brief['name'],
            'avatar': brief['image'],
        },
        'exp_count': exp_count,
        'private_count': private_count,
        'month_total_lesson': month_total_lesson,
        'average_lesson': "%.1f" % (month_total_lesson / days),
        'ranking': ranking,
        'valid_month': valid_month
    })


@blueprint.route('/month_report/brief', methods=['GET'])
@roles_required(CoachRole())
def get_month_report_brief():
    # 本月概况
    biz_id = g.get('biz_id')
    coach_id = CoachRole(biz_id=biz_id).get_id(g.role)
    coach: Coach = Coach.query.filter(
        Coach.id == coach_id
    ).first()
    now = datetime.now()
    early_month = tp.get_early_month(now)
    total_lesson = get_total_lesson(coach_id, early_month.year, early_month.month)

    return jsonify({
        'total_lesson': total_lesson,
        'id': coach.get_hash_id()
    })


@blueprint.route('/<string:c_id>/videos', methods=['GET'])
@roles_required()
@hide_coach_videos()
def get_coach_videos(c_id):
    coach: Coach = Coach.find(c_id)
    if not coach or coach.in_service is False:
        return jsonify(msg='教练不存在或已离职'), HTTPStatus.NOT_FOUND
    page = request.args.get('page', default=1, type=int)
    page_size = request.args.get('page_size', default=10, type=int)
    # 抓取所有带有该教练标签的视频
    videos = coach.get_videos()
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


@blueprint.route('/transform_image', methods=['POST'])
@permission_required(ManagePrivateCoachPermission())
def transform_coach_image():
    biz_id = g.get('biz_id')
    coaches: List[Coach] = Coach.query.filter(
        # Coach.biz_id == biz_id,
        # Coach.in_service == true()
    ).all()
    for coach in coaches:
        if coach.images:
            images = copy.deepcopy(coach.images)
            new_images = []
            for image in images:
                if image.startswith('https'):
                    new_images.append(image)

                elif image.startswith('http'):
                    new_image = image.replace('http', 'https')
                    new_images.append(new_image)
            if new_images:
                coach.images = new_images
                db.session.commit()
                db.session.refresh(coach)
                coach_cache = CoachCache(coach.id)
                coach_cache.reload()
    return jsonify(msg='OK')


# TODO quick post coach


@blueprint.route('/<string:c_id>/photo_wall', methods=['GET'])
@roles_required()
def get_photo_wall(c_id):
    """ 教练页获取图片墙详情(所有图片) """
    coach: Coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    page = request.args.get('page', default=1, type=int)
    photo_wall = PhotoWall.query.filter(
        PhotoWall.coach_id == coach.id
    ).order_by(desc(PhotoWall.created_at)).paginate(page=page, per_page=8, error_out=False)
    photos = [pw.photo for pw in photo_wall.items]
    return jsonify({
        "photo_wall": photos,
        "has_next": photo_wall.has_next
    })


def delete_coach_video_tags(coach):
    # 抓取所有带有该教练标签的视频
    videos = coach.get_videos()
    for v in videos:
        new_tags = copy.deepcopy(v.tags)
        new_video_coaches = copy.deepcopy(v.coaches)
        new_video_coaches.remove(coach.id)
        for t in new_tags:
            if t.get('type') == 'coach':
                t.get('ids').remove(coach.get_hash_id())
        v.tags = new_tags
        v.coaches = new_video_coaches
    coach.videos = []
    db.session.commit()


def get_ranking(coach_id, year, month):
    trainees: List[Trainee] = Trainee.query.filter(and_(
        Trainee.coach_id == coach_id,
        Trainee.is_bind == true(),
    )).order_by(desc(Trainee.attended_lessons)).all()

    ranking = []
    for trainee in trainees:
        trainee_cache = TraineeCache(trainee.coach_id, trainee.customer_id)
        name = trainee_cache.get('name')
        customer_cache = CustomerCache(customer_id=trainee.customer_id)
        avatar = customer_cache.get('avatar')
        attended_count = get_month_attended_count(trainee, year, month)
        ranking.append({
            'name': name,
            'avatar': avatar,
            'attended_count': attended_count,
        })
    ranking.sort(key=lambda x: (x['attended_count']), reverse=True)  # 按照当月已上课时从大到小排序
    return ranking


def get_valid_month(coach_id):
    """ 获取可以查看的月报月份 """
    first_report: MonthReport = MonthReport.query.filter(
        MonthReport.coach_id == coach_id
    ).order_by(asc(MonthReport.yymm)).first()

    valid_month = []
    early_month = tp.get_early_month(datetime.now())
    if not first_report:
        valid_month.append("{}年{:02d}月".format(early_month.year, early_month.month))
    else:
        first_yymm = yymm_to_datetime(first_report.yymm)
        while first_yymm <= early_month:
            valid_month.append("{}年{:02d}月".format(first_yymm.year, first_yymm.month))
            days = tp.get_day_of_month(first_yymm)
            first_yymm += timedelta(days=days)

    return valid_month


def get_total_lesson(coach_id, year, month):
    trainees: List[Trainee] = Trainee.query.filter(and_(
        Trainee.coach_id == coach_id,
        Trainee.is_bind == true(),
    )).all()

    month_total_lesson = 0
    for trainee in trainees:
        attended_count = get_month_attended_count(trainee, year, month)
        month_total_lesson += attended_count
    return month_total_lesson


def get_month_attended_count(trainee, year, month):
    early_month = datetime(year, month, 1)
    end_month = tp.get_end_month(early_month)

    early_yymmdd = get_yymmdd(early_month)
    end_yymmdd = get_yymmdd(end_month)

    attended_count = db.session.query(func.count(Seat.id)).filter(and_(
        Seat.is_valid == true(),
        Seat.coach_id == trainee.coach_id,
        Seat.customer_id == trainee.customer_id,
        Seat.status == SeatStatus.ATTENDED.value,
        Seat.yymmdd >= early_yymmdd,
        Seat.yymmdd <= end_yymmdd,
    )).scalar()
    return attended_count


def get_exp_count(coach_id, early_month):
    # 体验课节数
    end_month = tp.get_end_month(early_month)
    early_yymmdd = get_yymmdd(early_month)
    end_yymmdd = get_yymmdd(end_month)

    exp_count = db.session.query(func.count(Seat.customer_id)).filter(and_(
        Seat.is_valid == true(),
        Seat.coach_id == coach_id,
        Seat.yymmdd >= early_yymmdd,
        Seat.yymmdd <= end_yymmdd,
        Seat.priority == SeatPriority.EXPERIENCE.value,
    )).scalar()
    return exp_count


def get_private_count(coach_id):
    private_count = db.session.query(func.count(Trainee.id).filter(and_(
        Trainee.coach_id == coach_id,
        Trainee.is_bind == true(),
    ))).scalar()
    return private_count


def add_staff(coach):
    now = datetime.now()
    permissions_set = get_default_coach_permission(coach.biz_id, coach.id)
    coach_default_permission = get_permissions_name(permissions_set)
    try:
        biz_user = BizUser.query.filter(
            BizUser.phone_number == coach.phone_number
        ).first()
        if not biz_user:
            biz_user = BizUser(
                phone_number=coach.phone_number,
                created_at=now
            )
            db.session.add(biz_user)
            db.session.flush()
            db.session.refresh(biz_user)
        staff = BizStaff.query.filter(
            BizStaff.biz_id == coach.biz_id,
            BizStaff.biz_user_id == biz_user.id
        ).first()
        if not staff:
            staff = BizStaff(
                biz_id=coach.biz_id,
                biz_user_id=biz_user.id,
                roles=[CoachRole.role],
                permission_list=coach.permission_list or coach_default_permission,
                created_at=now,
                name=coach.name
            )
            db.session.add(staff)
        staff.roles = [CoachRole.role]
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        raise e

    return staff


def delete_staff(coach):
    biz_user = BizUser.query.filter(
        BizUser.phone_number == coach.phone_number
    ).first()
    if not biz_user:
        return
    staff: BizStaff = BizStaff.query.filter(
        BizStaff.biz_id == coach.biz_id,
        BizStaff.biz_user == biz_user
    ).first()
    if not staff:
        return
    staff.roles = []  # 去除该成员的私教角色
    staff.permission_list = [ViewBizPermission.name, ViewBizWebPermission.name]
    db.session.commit()

    return


def restore_staff(coach):
    biz_user = BizUser.query.filter(
        BizUser.phone_number == coach.phone_number
    ).first()
    if not biz_user:
        return
    staff: BizStaff = BizStaff.query.filter(
        BizStaff.biz_id == coach.biz_id,
        BizStaff.biz_user == biz_user
    ).first()
    if not staff:
        return
    staff.roles = [CoachRole.role]  # 恢复该成员的私教角色
    staff.permission_list = coach.permission_list
    db.session.commit()
    return


def change_staff_phone_number(biz_id, old_phone_number, new_phone_number):
    old_biz_user: BizUser = BizUser.query.filter(
        BizUser.phone_number == old_phone_number
    ).first()
    if not old_biz_user:
        return

    biz_staff: BizStaff = BizStaff.query.filter(
        BizStaff.biz_id == biz_id,
        BizStaff.biz_user_id == old_biz_user.id
    ).first()
    if not biz_staff:
        return

    try:
        new_biz_user: BizUser = BizUser.query.filter(
            BizUser.phone_number == new_phone_number
        ).first()
        if not new_biz_user:
            new_biz_user = BizUser(
                phone_number=new_phone_number,
                created_at=datetime.now()
            )
            db.session.add(new_biz_user)
            db.session.flush()
            db.session.refresh(new_biz_user)
        biz_staff.biz_user_id = new_biz_user.id
        biz_staff.modified_at = datetime.now()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e
    return
