import json
from datetime import datetime
from http import HTTPStatus
from typing import List
from flask import jsonify, Blueprint, g, request, send_file
from sqlalchemy import true, null, or_
from store.database import db
from store.domain.cache import CoachCache, StoreBizCache, AppCache, CourseCache, VideoLimitCache, VideoHistory
from store.domain.middle import permission_required, roles_required
from store.domain.models import Video, Place, WxOpenUser, Thumb, Coach, Course, \
    BizStaff, Share, ShareType, Feed
from store.domain.permission import ViewBizPermission, get_permissions_name
from store.domain.role import CoachRole, CustomerRole
import base62
import io
from store.domain.wxapp import UnlimitedCode
from store.videos.utils import generate_share_pic_threads, get_role, check_video_info, get_mini_tags_data, \
    get_thumb_count, get_uploader, get_pc_tags_data, get_video_info, save_video_info, check_uploader, \
    get_different_tags, assign_tags, get_thumbs_brief, get_user_videos, delete_coaches_video, delete_courses_video, \
    delete_places_video, convert_video

blueprint = Blueprint('_videos', __name__)


@blueprint.route('', methods=['GET'])
@roles_required()
def get_videos():
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    g_role = g.get('role')
    permissions = g.get('permission')
    role, object_id = get_role(biz_id, g_role)

    page = request.args.get('page', 1, type=int)  # 默认显示第一页的数据
    page_size = request.args.get('page_size', 10, type=int)  # 每页显示条数(pc端与小程序不同)
    videos = get_user_videos(biz_id=biz_id, role=role, object_id=object_id, permissions=permissions, page=page,
                             page_size=page_size)

    if page == 1 and videos.items == []:
        # 第一页没有数据说明没有发布过
        return jsonify([])

    res = []
    if w_id:
        for video in videos.items:
            video = check_video_info(video)  # 校验视频信息(封面图等)
            brief = video.get_brief()
            tags = get_mini_tags_data(video)
            thumb = get_thumb_count(video)
            upload_time = get_uploader(video).get('upload_time')
            brief.update({'upload_time': upload_time})
            res.append({
                'brief': brief,
                'tags': tags,
                'thumbs_count': thumb,
            })
        return jsonify(res)

    for video in videos.items:
        check_video_info(video)
        tags = get_pc_tags_data(video)
        uploader = get_uploader(video)
        uploader_name = uploader.get('name')
        upload_time = uploader.get('upload_time')
        size = video.size
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
            'tags': tags
        })
    return jsonify({
        'videos': res,
        'page_count': videos.pages,  # 总页数
    })


@blueprint.route('/<string:file_id>/info', methods=['POST'])
@roles_required()
def post_video_info(file_id):
    # 上传视频完成后调用
    biz_id = g.get('biz_id')
    g_role = g.get('role')  # {'6': {"manager_id": 1}, '22': {"manager_id": 3}}
    upload_type = request.args.get('upload_type', default='store', type=str)

    role, object_id = get_role(biz_id, g_role)
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    height = json_data.get('height')
    width = json_data.get('width')
    duration = json_data.get('duration')

    title = json_data.get('title')
    try:
        video_info = get_video_info(file_id)  # 请求腾讯云获取视频信息
    except Exception as e:
        return jsonify(msg='获取视频信息失败')

    if not video_info:
        return jsonify(msg='无法获取视频信息'), HTTPStatus.BAD_REQUEST

    if height:
        video_info.update({'height': height})
    if width:
        video_info.update({'width': width})
    if duration:
        video_info.update({'duration': duration})
    if title:
        video_info.update({'title': title})

    is_ok, msg = save_video_info(
        biz_id=biz_id, file_id=file_id, video_info=video_info, role=role, object_id=object_id, upload_type=upload_type
    )  # 保存到数据库
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST
    # 视频转码(后台轮询消息队列获取转码结果)
    convert_video(file_id)

    return jsonify(msg=msg)


@blueprint.route('/<string:file_id>', methods=['PUT'])
@roles_required()
def put_video_info(file_id):
    biz_id = g.get('biz_id')
    permissions = g.get('permission')
    permission_list = get_permissions_name(permissions, biz_id)

    g_role = g.get('role')
    role, object_id = get_role(biz_id, g_role)
    uploader = {'role': role, 'object_id': object_id}

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    video: Video = Video.find(file_id)
    if not video or Video.is_valid is False:
        return jsonify(msg='视频不存在'), HTTPStatus.NOT_FOUND

    is_ok, msg = check_uploader(video=video, uploader=uploader, role=role, permission_list=permission_list)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    v_data = json_data.get('video')
    new_tags = v_data.get('tags')

    title = v_data.get('title')
    if title:
        video.title = title
    add_tags, delete_tags = get_different_tags(new_tags=new_tags, old_tags=video.tags)
    # 将新的tag存入
    video.tags = new_tags
    video.modified_at = datetime.now()
    db.session.commit()
    db.session.refresh(video)
    # 根据tags来决定视频存放的位置
    assign_tags(add_tags=add_tags, delete_tags=delete_tags, video=video)

    return jsonify(msg='修改成功')


@blueprint.route('/<string:file_id>', methods=['GET'])
@roles_required()
def get_video(file_id):
    video: Video = Video.find(file_id)
    if not video or Video.is_valid is False:
        return jsonify(msg='视频不存在'), HTTPStatus.NOT_FOUND

    video = check_video_info(video)  # 校验视频信息(封面图等)
    video_brief = video.get_brief()
    w_id = g.get('w_id')
    if w_id:
        w_user: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.id == w_id
        ).first()
        if not w_user:
            return jsonify(msg='账号异常'), HTTPStatus.BAD_REQUEST
        from store.places.apis import get_thumb
        thumb = get_thumb(video, w_user.customer_id)
        tags = get_mini_tags_data(video)
        video_brief.update({'tags': tags})
        video_brief.update({'thumb': thumb})
    else:
        tags = get_pc_tags_data(video)
        video_brief.update({'tags': tags})

    return jsonify({
        "video": video_brief,
    })


@blueprint.route('', methods=['POST'])
@roles_required()
def post_video():
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    video_data = json_data.get('video')
    to_feed = json_data.get('to_feed')
    file_id = video_data.get('fileId')
    title = video_data.get('title')
    tags = video_data.get('tags')
    video: Video = Video.find(file_id)
    if not video:
        return jsonify(msg='视频未上传完毕'), HTTPStatus.BAD_REQUEST
    add_tags, delete_tags = get_different_tags(new_tags=tags, old_tags=video.tags)
    video.tags = tags
    if title:
        video.title = title
    if to_feed:
        feed = Feed(
            biz_id=biz_id,
            video={'fileId': file_id, 'videoUrl': video.url},
            words=title,
            created_at=datetime.now()
        )
        db.session.add(feed)
    db.session.commit()
    db.session.refresh(video)

    # 根据tags来决定视频存放的位置
    assign_tags(add_tags=add_tags, delete_tags=delete_tags, video=video)

    return jsonify(msg='发布成功')


@blueprint.route('', methods=['DELETE'])
@roles_required()
def delete_video():
    biz_id = g.get('biz_id')
    permissions = g.get('permission')
    g_role = g.get('role')
    role, object_id = get_role(biz_id, g_role)
    uploader = {'role': role, 'object_id': object_id}
    permission_list = get_permissions_name(permissions, biz_id)

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    staff: BizStaff = BizStaff.query.filter(
        BizStaff.id == object_id
    ).first()
    # 如果没有staff说明是manager
    if staff:
        if staff.roles == [CoachRole.role]:
            coach: Coach = Coach.query.filter(
                Coach.biz_id == staff.biz_id,
                Coach.phone_number == staff.biz_user.phone_number
            ).first()
            uploader = {'role': 'coach', 'object_id': coach.id}

    file_ids = json_data.get('file_ids')

    try:
        for file_id in file_ids:
            video: Video = Video.find(file_id)
            if not video or Video.is_valid is False:
                return jsonify(msg='视频不存在'), HTTPStatus.NOT_FOUND
            is_ok, msg = check_uploader(video, uploader, role, permission_list)
            if not is_ok:
                return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

            video.is_valid = False
            coach_ids = video.coaches
            courses_ids = video.courses
            place_ids = video.places
            if coach_ids:
                delete_coaches_video(coach_ids, video)
            if courses_ids:
                delete_courses_video(courses_ids, video)
            if place_ids:
                delete_places_video(place_ids, video)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e
    return jsonify(msg='删除成功')


@blueprint.route('/<string:file_id>/thumb', methods=['POST'])
@permission_required(ViewBizPermission())
def post_thumb(file_id):
    biz_id = g.get('biz_id')
    video: Video = Video.find(file_id)
    if not video or Video.is_valid is False:
        return jsonify(msg='视频不存在'), HTTPStatus.NOT_FOUND
    w_id = g.get('w_id')
    w_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.id == w_id
    ).first()
    if not w_user:
        return jsonify(msg='账号有误'), HTTPStatus.BAD_REQUEST
    thumb: Thumb = Thumb.query.filter(
        Thumb.video_id == video.id,
        Thumb.customer_id == w_user.customer_id
    ).first()

    if thumb:
        avatars, nick_names = get_thumbs_brief(video)
        return jsonify({
            'is_thumb': True,
            "thumb_count": get_thumb_count(video),
            'avatars': avatars,  # 点赞后用户头像直接出现
            'nick_names': nick_names,  # 点赞后用户nick_name直接出现
        })

    thumb = Thumb(
        biz_id=biz_id,
        customer_id=w_user.customer_id,
        video_id=video.id,
        created_at=datetime.now()
    )

    db.session.add(thumb)
    db.session.commit()
    db.session.refresh(thumb)

    avatars, nick_names = get_thumbs_brief(video)
    return jsonify({
        'is_thumb': True,
        'thumb_count': get_thumb_count(video),
        'avatars': avatars,  # 点赞后用户头像直接出现
        'nick_names': nick_names,  # 点赞后用户nick_name直接出现
    })


@blueprint.route('/<string:file_id>/share_image', methods=['GET'])
@roles_required()
def get_share_image(file_id):
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    video: Video = Video.find(file_id)
    if not video or video.is_valid is False:
        return jsonify(msg='视频不存在'), HTTPStatus.BAD_REQUEST
    store_biz_cache = StoreBizCache(biz_id)
    customer_app_id = store_biz_cache.get('customer_app_id')
    if not customer_app_id:
        return jsonify(msg='客户端小程序不存在'), HTTPStatus.NOT_FOUND
    share_type = ShareType.QRCODE.value
    path = '/pages/video/detail'
    params = 'file_id={file_id}&page=videoDetail'.format(file_id=file_id)
    path_id = 's'  # 这个ID由客户端定义, 但是得注意版本兼容性
    s: Share = Share.query.filter(
        Share.biz_id == biz_id,
        Share.type == share_type,
        Share.path == path,
        Share.params == params,
        Share.shared_customer_id == customer_id
    ).first()

    now = datetime.now()
    if not s:
        s = Share(
            biz_id=biz_id,
            type=share_type,
            path=path,
            params=params,
            shared_customer_id=customer_id,
            created_at=now
        )
        db.session.add(s)
        db.session.commit()
        db.session.refresh(s)

    code_mode = 1
    s_id = base62.encode(s.id)

    scene = '{code_mode}&{path_id}&{s_id}'.format(code_mode=code_mode, path_id=path_id, s_id=s_id)
    qr_code = UnlimitedCode(app_id=customer_app_id).get_raw_code(scene)

    app_cache = AppCache(customer_app_id)
    store_name = app_cache.get('nick_name')
    check_video_info(video)

    share_pic = generate_share_pic_threads(video, store_name, qr_code)

    share_pic_bytes = io.BytesIO()
    share_pic.save(share_pic_bytes, format='JPEG')
    share_pic_bytes.seek(0)

    now = datetime.now()
    date_str = now.strftime("_%Y%m%d")
    file_name = file_id + str(date_str) + '.jpg'
    res = send_file(share_pic_bytes, attachment_filename=file_name, mimetype='image/jpeg', as_attachment=true)
    return res


@blueprint.route('/tags', methods=['GET'])
@roles_required()
def get_tags():
    biz_id = g.get('biz_id')
    places_list = Place.get_biz_places(biz_id)
    courses_list: List[Course] = Course.query.filter(
        Course.biz_id == biz_id
    ).all()
    coach_list: List[Coach] = Coach.query.filter(
        Coach.biz_id == biz_id,
        Coach.in_service == true(),
        Coach.coach_type == 'private'
    ).all()

    places = {'type': 'place', 'data': places_list}
    courses = {'type': 'course', 'data': []}
    coaches = {'type': 'coach', 'data': []}

    for course in courses_list:
        course_cache = CourseCache(course.id)
        brief = course_cache.get('brief')
        title = brief.get('title')
        course_id = brief.get('id')
        courses['data'].append({'name': title, 'id': course_id})

    for coach in coach_list:
        c_cache = CoachCache(coach.id)
        brief = c_cache.get('brief')
        name = brief.get('name')
        coach_id = brief.get('id')
        coaches['data'].append({'name': name, 'id': coach_id})

    return jsonify({
        'places': places,
        'courses': courses,
        'coaches': coaches,
    })


@blueprint.route('/record', methods=['PUT'])
@roles_required(CustomerRole())
def post_video_record():
    """ 记录用户观看历史以及时长并返回是否超出限额 """
    # TODO 每日清零
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    if not customer_id:
        return jsonify(msg="用户不存在"), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    file_id = json_data.get('file_id')
    play_time = json_data.get('play_time')

    limit_cache = VideoLimitCache(customer_id=customer_id)
    history_cache = VideoHistory(customer_id=customer_id)

    h_file_ids = history_cache.get('file_ids') or []
    if file_id not in h_file_ids:
        h_file_ids.append(file_id)
        history_cache.set({'file_ids': json.dumps(h_file_ids)})

    is_over = limit_cache.is_over()
    if is_over:
        return jsonify({
            'is_over': is_over
        })
    used = limit_cache.get('used') or 0
    used += play_time
    limit_cache.set({'used': used})

    return jsonify({
        'is_over': limit_cache.is_over()
    })


@blueprint.route('/is_over', methods=['GET'])
@roles_required(CustomerRole())
def get_is_over():
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id).get_id(g.role)
    if not customer_id:
        return jsonify(msg="用户不存在"), HTTPStatus.NOT_FOUND
    limit_cache = VideoLimitCache(customer_id=customer_id)
    is_over = limit_cache.is_over()
    return jsonify({
        'is_over': is_over
    })
