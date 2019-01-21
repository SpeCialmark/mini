import json
import math
import time
from datetime import datetime

from QcloudApi.common import sign
from random import randint
from typing import List

import copy
import io
import sys
import requests
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import asc, func, true, desc, or_
from store.config import cfg, _env
from store.database import db
from store.domain.cache import CoachCache, CourseCache, PlaceCache, CustomerCache
from store.domain.permission import get_permissions_name, UploadVideoPermission, ManageVideoPermission
from store.domain.role import ManagerRole, CoachRole, CustomerRole, BizUserRole, AdminRole
from store.utils.oss import bucket
from concurrent import futures
from store.domain.models import Video, Coach, Course, Place, Thumb, WxAuthorizer, AppMark, BizStaff, BizUser
import timeit

from store.utils.picture_processing import round_rectangle, circle
from store.wxopen import backend_client, backend_agent_id

base_path = sys.path[0] + '/res/'


class VideoType:
    Place = 'place'
    Course = 'course'
    Store = 'store'
    Coach = 'coach'
    Feed = 'feed'


def upload_poster_to_oss(video: Video):
    if not video.poster:
        return
    file_name = '{}.jpg'.format(video.file_id)
    cover_key = cfg['aliyun_oss']['video_cover_path'].format(file_name=file_name)
    exist = bucket.object_exists(cover_key)  # 查看文件是否存在
    if exist:
        return
    r_put = bucket.put_object(cover_key, requests.get(video.poster), {'Content-Disposition': 'attachment'})
    if r_put.status != 200:
        raise IOError('图片上传到阿里云失败')


def get_avatar(avatar_url):
    start = timeit.default_timer()
    print("Task #2 started!", start)
    avatar = Image.open(requests.get(avatar_url, stream=True).raw).convert('RGBA')
    avatar = avatar.resize((100, 100), Image.ANTIALIAS)
    stop = timeit.default_timer()
    print("Task #2 is done!", stop)
    print("Task 2 time=", stop - start)
    return avatar


def get_poster(poster_url):
    start = timeit.default_timer()
    print("Task #3 started!", start)
    poster = Image.open(requests.get(poster_url, stream=True).raw).convert('RGBA')
    poster = poster.resize((750, int(poster.size[1] * (750 / poster.size[0]))), Image.ANTIALIAS)
    stop = timeit.default_timer()
    print("Task #3 is done!", stop)
    print("Task 3 time=", stop - start)

    start2 = timeit.default_timer()
    # 图片宽高自适应
    if poster.size[0] > 754:
        poster.thumbnail((754, poster.size[1]), Image.ANTIALIAS)  # 按比例缩放
        poster = poster
    else:
        poster = poster.resize((poster.size[0] * 2, poster.size[1] * 2), Image.ANTIALIAS)
        poster.thumbnail((754, poster.size[1]), Image.ANTIALIAS)
        poster = poster
    stop2 = timeit.default_timer()
    print("!!Task 4 time=", stop2 - start2)
    return poster


def generate_share_pic_threads(video: Video, store_name, qrcode):
    play_icon = Image.open(base_path + 'play_icon.png').convert('RGBA')  # 播放icon
    fingerprint = Image.open(base_path + 'fingerprint.png').convert('RGBA')  # 指纹
    title = video.title
    if not video.poster:
        refresh_video_info(video, VideoIntention.POSTER)

    file_name = '{}.jpg'.format(video.file_id)
    cover_key = cfg['aliyun_oss']['video_cover_path'].format(file_name=file_name)

    exist = bucket.object_exists(cover_key)  # 查看文件是否存在
    if not exist:
        upload_poster_to_oss(video)

    poster_url = cfg['aliyun_oss']['host'] + '/' + cover_key

    qr_code, poster = None, None
    qr_code = Image.open(io.BytesIO(qrcode.content)).convert('RGBA')
    with futures.ThreadPoolExecutor(max_workers=2) as executor:
        poster_f = executor.submit(get_poster, poster_url)
        fs = {poster_f: 'poster'}

        for f in futures.as_completed(fs):
            if fs[f] == 'poster':
                poster = f.result()

    qr_code = qr_code.resize((160, 160), Image.ANTIALIAS)
    play_icon = play_icon.resize((130, 130), Image.ANTIALIAS)
    fingerprint = fingerprint.resize((150, 150), Image.ANTIALIAS)
    words_back_ground = round_rectangle((210, 60), 10, '#E1CBA5')  # 文字背景
    p_a = poster.split()[3]
    q_a = qr_code.split()[3]
    i_a = play_icon.split()[3]
    f_a = fingerprint.split()[3]

    qr_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=28)  # 长按识别小程序大小28px
    text_font = ImageFont.truetype(base_path + 'font/msyhbd.ttf', size=28)  # 看视频一起练大小28px
    store_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=24)  # 店名大小24px

    qr_str = '长按识别小程序'
    text_str = '看视频一起练!'
    store_str = "@" + store_name

    if title:
        back_ground = Image.new('RGBA', (750, poster.size[1] + 336), '#ffffff').convert('RGBA')  # 白底
        mack = Image.new('RGBA', (750, 86), '#ffffff').convert('RGBA')
        m_a = mack.split()[3]
        back_ground.paste(mack, (0, 0), mask=m_a)
        title_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=32)  # 视频标题大小32px
        word_draw = ImageDraw.Draw(back_ground)
        word_draw.text((20, 20), title, font=title_font, fill='#666666')
        poster_box = (int(poster.size[0] / 2 - play_icon.size[0] / 2), int(poster.size[1] / 2 - play_icon.size[1] / 2 + mack.size[1]))
        back_ground.paste(poster, (0, mack.size[1]), mask=p_a)
        back_ground.paste(words_back_ground, (int(back_ground.size[0]/2-words_back_ground.size[0]/2), int(poster.size[1]+mack.size[1]+40)))
        back_ground.paste(play_icon, poster_box, mask=i_a)
        back_ground.paste(qr_code, (int(back_ground.size[0]-qr_code.size[0]-50), poster.size[1]+mack.size[1]+40), mask=q_a)
        back_ground.paste(fingerprint, (50, poster.size[1]+mack.size[1]+40), mask=f_a)
        word_draw.text((int(back_ground.size[0]/2-words_back_ground.size[0]/2)+10, int(poster.size[1] + mack.size[1] + 50)), qr_str, font=qr_font, fill='#ffffff')
        word_draw.text((int(back_ground.size[0]/2-words_back_ground.size[0]/2)+10, int(poster.size[1] + mack.size[1] + 115)), text_str, font=text_font, fill='#666666')
        word_draw.text((int(back_ground.size[0]/2-words_back_ground.size[0]/2)+10, int(poster.size[1] + mack.size[1] + 165)), store_str, font=store_font, fill='#666666')
    else:
        back_ground = Image.new('RGBA', (750, poster.size[1] + 250), '#ffffff').convert('RGBA')  # 白底
        word_draw = ImageDraw.Draw(back_ground)
        poster_box = (int(poster.size[0] / 2 - play_icon.size[0] / 2), int(poster.size[1] / 2 - play_icon.size[1] / 2))
        back_ground.paste(poster, (0, 0), mask=p_a)
        back_ground.paste(words_back_ground,
                          (int(back_ground.size[0] / 2 - words_back_ground.size[0] / 2), int(poster.size[1] + 40)))
        back_ground.paste(play_icon, poster_box, mask=i_a)
        back_ground.paste(qr_code, (int(back_ground.size[0] - qr_code.size[0] - 50), poster.size[1] + 40), mask=q_a)
        back_ground.paste(fingerprint, (50, poster.size[1] + 40), mask=f_a)
        word_draw.text((int(back_ground.size[0]/2-words_back_ground.size[0]/2)+10, int(poster.size[1] + 50)), qr_str, font=qr_font, fill='#ffffff')
        word_draw.text((int(back_ground.size[0]/2-words_back_ground.size[0]/2)+10, int(poster.size[1] + 115)), text_str, font=text_font, fill='#666666')
        word_draw.text((int(back_ground.size[0]/2-words_back_ground.size[0]/2)+10, int(poster.size[1] + 165)), store_str, font=store_font, fill='#666666')

    share_pic = back_ground.convert(mode='RGB')
    return share_pic


def draw_video_tags(tags, word_draw, tags_font, poster):
    for index, t in enumerate(tags):
        t_name = "#" + t.get('name') + "#"
        t_box = (20 + index * len(t_name) * tags_font.size, poster.size[1] + 20)
        word_draw.text(t_box, t_name, font=tags_font, fill='#666666')

    return


def check_video_permission(biz_id, permissions):
    permission_list = get_permissions_name(permissions, biz_id)
    if ManageVideoPermission.name in permission_list:
        return True, ''
    elif UploadVideoPermission.name in permission_list:
        return True, ''

    return False, '暂无权限'


def get_different_tags(new_tags, old_tags):
    if not old_tags:
        old_tags = []
    delete_tags = []
    add_tags = []
    new_coach = set()
    new_course = set()
    new_place = set()
    old_coach = set()
    old_course = set()
    old_place = set()
    for nt in new_tags:
        if nt.get('type') == 'coach':
            for c_id in nt.get('ids'):
                new_coach.add(c_id)
        elif nt.get('type') == 'course':
            for c_id in nt.get('ids'):
                new_course.add(c_id)
        elif nt.get('type') == 'place':
            for p_id in nt.get('ids'):
                new_place.add(p_id)

    for ot in old_tags:
        if ot.get('type') == 'coach':
            for c_id in ot.get('ids'):
                old_coach.add(c_id)
        elif ot.get('type') == 'course':
            for c_id in ot.get('ids'):
                old_course.add(c_id)
        elif ot.get('type') == 'place':
            for p_id in ot.get('ids'):
                old_place.add(p_id)

    same_coach = new_coach & old_coach
    same_course = new_course & old_course
    same_place = new_place & old_place

    # 需要剔除的tag
    delete_coach = old_coach - same_coach
    delete_course = old_course - same_course
    delete_place = old_place - same_place

    # 需要新增的tag
    add_coach = new_coach - same_coach
    add_course = new_course - same_course
    add_place = new_place - same_place

    delete_tags.append({'type': 'coach', 'ids': list(delete_coach)})
    delete_tags.append({'type': 'course', 'ids': list(delete_course)})
    delete_tags.append({'type': 'place', 'ids': list(delete_place)})

    add_tags.append({'type': 'coach', 'ids': list(add_coach)})
    add_tags.append({'type': 'course', 'ids': list(add_course)})
    add_tags.append({'type': 'place', 'ids': list(add_place)})

    return add_tags, delete_tags


def assign_tags(add_tags, delete_tags, video):
    # 根据tags分配video的存放位置
    try:
        videos_places = copy.deepcopy(video.places) if video.places else []
        videos_courses = copy.deepcopy(video.courses) if video.courses else []
        videos_coaches = copy.deepcopy(video.coaches) if video.coaches else []
        # 新增
        for at in add_tags:
            if at.get('type') == 'coach':
                coach_ids = [Coach.decode_id(c_id) for c_id in at.get('ids')]
                if not coach_ids:
                    continue
                coaches: List[Coach] = Coach.query.filter(
                    Coach.id.in_(coach_ids)
                ).all()
                for coach in coaches:
                    c_videos = copy.deepcopy(coach.videos) if coach.videos else []
                    c_videos.append(video.id)
                    videos_coaches.append(coach.id)
                    coach.videos = c_videos

            elif at.get('type') == 'course':
                course_ids = [Course.decode_id(c_id) for c_id in at.get('ids')]
                if not course_ids:
                    continue
                courses: List[Course] = Course.query.filter(
                    Course.id.in_(course_ids)
                ).all()
                for course in courses:
                    c_videos = copy.deepcopy(course.videos) if course.videos else []
                    c_videos.append(video.id)
                    videos_courses.append(course.id)
                    course.videos = c_videos

            elif at.get('type') == 'place':
                place_ids = [Place.decode_id(c_id) for c_id in at.get('ids')]
                if not place_ids:
                    continue
                places: List[Place] = Place.query.filter(
                    Place.id.in_(place_ids)
                ).all()
                for place in places:
                    p_videos = copy.deepcopy(place.videos) if place.videos else []
                    p_videos.append(video.id)
                    videos_places.append(place.id)
                    place.videos = p_videos
        # 删除
        for dt in delete_tags:
            if dt.get('type') == 'coach':
                coach_ids = [Coach.decode_id(c_id) for c_id in dt.get('ids')]
                if not coach_ids:
                    continue
                coaches: List[Coach] = Coach.query.filter(
                    Coach.id.in_(coach_ids)
                ).all()
                for coach in coaches:
                    c_videos = copy.deepcopy(coach.videos) if coach.videos else []
                    c_videos.remove(video.id)
                    videos_coaches.remove(coach.id)
                    coach.videos = c_videos

            elif dt.get('type') == 'course':
                course_ids = [Course.decode_id(c_id) for c_id in dt.get('ids')]
                if not course_ids:
                    continue
                courses: List[Course] = Course.query.filter(
                    Course.id.in_(course_ids)
                ).all()
                for course in courses:
                    c_videos = copy.deepcopy(course.videos) if course.videos else []
                    c_videos.remove(video.id)
                    videos_courses.remove(course.id)
                    course.videos = c_videos

            elif dt.get('type') == 'place':
                place_ids = [Place.decode_id(c_id) for c_id in dt.get('ids')]
                if not place_ids:
                    continue
                places: List[Place] = Place.query.filter(
                    Place.id.in_(place_ids)
                ).all()
                for place in places:
                    p_videos = copy.deepcopy(place.videos) if place.videos else []
                    p_videos.remove(video.id)
                    videos_places.remove(place.id)
                    place.videos = p_videos

        video.places = videos_places
        video.coaches = videos_coaches
        video.courses = videos_courses
        db.session.commit()
    except Exception as e:
        db.session.rollback()


def delete_coaches_video(coach_ids, video):
    coaches: List[Coach] = Coach.query.filter(
        Coach.id.in_(coach_ids)
    ).all()
    for coach in coaches:
        c_videos = copy.deepcopy(coach.videos)
        c_videos.remove(video.id)
        coach.videos = c_videos


def delete_courses_video(course_ids, video):
    courses: List[Course] = Course.query.filter(
        Course.id.in_(course_ids)
    ).all()
    for course in courses:
        c_videos = copy.deepcopy(course.videos)
        c_videos.remove(video.id)
        course.videos = c_videos


def delete_places_video(place_ids, video):
    places: List[Place] = Place.query.filter(
        Place.id.in_(place_ids)
    ).all()
    for place in places:
        p_videos = copy.deepcopy(place.videos)
        p_videos.remove(video.id)
        place.videos = p_videos


def get_mini_tags_data(video):
    res = []
    tags = video.tags
    if tags:
        for t in tags:
            # {'type': 'coach', 'ids': []}
            if t.get('type') == 'coach':
                for c_id in t.get('ids'):
                    c_cache = CoachCache(Coach.decode_id(c_id))
                    brief = c_cache.get('brief')
                    name = brief.get('name')
                    c_hid = brief.get('id')
                    res.append({'type': 'coach', 'id': c_hid, 'name': name})
            elif t.get('type') == 'course':
                for c_id in t.get('ids'):
                    c_cache = CourseCache(Course.decode_id(c_id))
                    brief = c_cache.get('brief')
                    name = brief.get('title')
                    c_hid = brief.get('id')
                    res.append({'type': 'course', 'id': c_hid, 'name': name})
            elif t.get('type') == 'place':
                for p_id in t.get('ids'):
                    p_cache = PlaceCache(Place.decode_id(p_id))
                    name, p_hid = p_cache.get('name', 'id')
                    res.append({'type': 'place', 'id': p_hid, 'name': name})
    return res


def get_pc_tags_data(video):
    res = []
    tags = video.tags
    if tags:
        for t in tags:
            # {'type': 'coach', 'ids': []}
            if t.get('type') == 'coach':
                coach_data = []
                for c_id in t.get('ids'):
                    c_cache = CoachCache(Coach.decode_id(c_id))
                    brief = c_cache.get('brief')
                    name = brief.get('name')
                    c_hid = brief.get('id')
                    coach_data.append({'id': c_hid, 'name': name})
                res.append({'type': 'coach', 'data': coach_data})
            elif t.get('type') == 'course':
                course_data = []
                for c_id in t.get('ids'):
                    c_cache = CourseCache(Course.decode_id(c_id))
                    brief = c_cache.get('brief')
                    name = brief.get('title')
                    c_hid = brief.get('id')
                    course_data.append({'id': c_hid, 'name': name})
                res.append({'type': 'course', 'data': course_data})
            elif t.get('type') == 'place':
                place_data = []
                for p_id in t.get('ids'):
                    p_cache = PlaceCache(Place.decode_id(p_id))
                    name, p_hid = p_cache.get('name', 'id')
                    place_data.append({'id': p_hid, 'name': name})
                res.append({'type': 'place', 'data': place_data})

    return res


def check_uploader(video, uploader, role, permission_list):
    if ManageVideoPermission.name in permission_list:
        return True, ''

    if role == ManagerRole.role:
        return True, ''

    if uploader == video.uploaded_by:
        return True, ''

    return False, '您暂无权限操作他人上传的视频'


def check_video_info(video):
    # 校验视频信息,目前只校验了是否有封面
    if not video.poster or video.poster == '':
        refresh_video_info(video, VideoIntention.POSTER)

    return video


def get_thumbs_brief(video):
    thumbs: List[Thumb] = Thumb.query.filter(
        Thumb.video_id == video.id
    ).order_by(asc(Thumb.created_at)).all()
    avatars = []
    nick_names = []
    for thumb in thumbs:
        c_cache = CustomerCache(thumb.customer_id)
        avatar, nick_name = c_cache.get('avatar', 'nick_name')
        avatars.append(avatar)
        nick_names.append(nick_name)
    return avatars, nick_names


def get_thumb_count(video):
    thumb_count = db.session.query(func.count(Thumb.customer_id)).filter(
        Thumb.video_id == video.id
    ).scalar()
    return thumb_count


def get_role(biz_id, g_role):
    role_dict = g_role.get(str(biz_id))
    for id_key_str, r_id in role_dict.items():
        if id_key_str == ManagerRole.id_key_str:
            return ManagerRole.role, r_id
        elif id_key_str == CoachRole.id_key_str:
            return CoachRole.role, r_id
        elif id_key_str == CustomerRole.id_key_str:
            return CustomerRole.role, r_id
        elif id_key_str == BizUserRole.id_key_str:
            return BizUserRole.role, r_id
        elif id_key_str == AdminRole.id_key_str:
            return AdminRole.role, r_id
        else:
            return "unknown_role", -1


def get_uploader(video):
    # 获取上传者
    role = video.uploaded_by.get('role')
    object_id = video.uploaded_by.get('object_id')
    if role == CoachRole.role:
        c_cache = CoachCache(object_id)
        brief = c_cache.get('brief')
        avatar = brief.get('image')
        name = brief.get('name')
    else:
        # 显示商家头像
        wx_auth: WxAuthorizer = WxAuthorizer.query.filter(
            WxAuthorizer.biz_id == video.biz_id,
            WxAuthorizer.mark == AppMark.CUSTOMER.value
        ).first()
        avatar = wx_auth.head_img
        name = wx_auth.nick_name

    return {
        'avatar': avatar,
        'name': name,
        'upload_time': video.created_at.strftime("%Y-%m-%d  %H:%M"),
        'coach_id': Coach.encode_id(object_id) if role == CoachRole.role else None
    }


def get_video_info(file_id):
    secret_id = cfg['tencent_video']['secret_id']
    secret_key = cfg['tencent_video']['secret_key']
    current = int(time.time())
    nonce = randint(1, pow(2, 32))
    s = sign.Sign(secret_id, secret_key)
    params = {
        'SecretId': secret_id,
        'SignatureMethod': 'HmacSHA1',
        'Nonce': nonce,
        'Timestamp': current,
        'Action': 'GetVideoInfo',
        'fileId': file_id,
    }
    ss = s.make('vod.api.qcloud.com', '/v2/index.php', params,
                method='GET')

    url = 'https://vod.api.qcloud.com/v2/index.php'
    params.update({'Signature': ss})
    r = requests.get(url, params)
    video_info = r.json()

    return video_info


def convert_video(file_id):
    # 视频转码(上传完成后调用)
    secret_id = cfg['tencent_video']['secret_id']
    secret_key = cfg['tencent_video']['secret_key']
    current = int(time.time())
    nonce = randint(1, pow(2, 32))
    s = sign.Sign(secret_id, secret_key)
    params = {
        'SecretId': secret_id,
        'SignatureMethod': 'HmacSHA1',
        'Nonce': nonce,
        'Timestamp': current,
        'Action': 'ConvertVodFile',
        'fileId': file_id,
        'isWatermark': 1  # 转码时使用默认水印(水印的出现位置及大小需到点播控制台进行设置)
    }
    ss = s.make('vod.api.qcloud.com', '/v2/index.php', params,
                method='GET')

    url = 'https://vod.api.qcloud.com/v2/index.php'
    params.update({'Signature': ss})
    r = requests.get(url, params)
    return


def modify_video_info(video):
    # 主要用于修改视频文件名字
    file_name = 'b{biz_id}_'.format(
        biz_id=video.biz_id
    ) + datetime.strftime(datetime.today(), '%Y%m%d_%H%M%S')
    secret_id = cfg['tencent_video']['secret_id']
    secret_key = cfg['tencent_video']['secret_key']
    current = int(time.time())
    nonce = randint(1, pow(2, 32))
    s = sign.Sign(secret_id, secret_key)
    params = {
        'SecretId': secret_id,
        'SignatureMethod': 'HmacSHA1',
        'Nonce': nonce,
        'Timestamp': current,
        'Action': 'ModifyVodInfo',
        'fileId': video.file_id,
        'fileName': file_name
    }
    ss = s.make('vod.api.qcloud.com', '/v2/index.php', params,
                method='GET')

    url = 'https://vod.api.qcloud.com/v2/index.php'
    params.update({'Signature': ss})
    r = requests.get(url, params)
    video_info = r.json()

    return video_info


def save_video_info(biz_id, file_id, video_info, role, object_id, upload_type):
    video: Video = Video.query.filter(
        Video.file_id == file_id
    ).first()

    basic_info = video_info.get('basicInfo')
    width = video_info.get('width')
    height = video_info.get('height')
    duration = video_info.get('duration')
    title = video_info.get('title')
    if video:
        refresh_video_info(video)
        return True, '保存成功'
    video = Video()
    try:
        video.video_info = json.dumps(video_info)
        uploaded_by = {'role': role, 'object_id': object_id}
        if role != ManagerRole.role:
            if upload_type == 'coach':
                staff: BizStaff = BizStaff.query.filter(
                    BizStaff.id == object_id
                ).first()
                if staff.roles == [CoachRole.role]:
                    coach: Coach = Coach.query.filter(
                        Coach.biz_id == staff.biz_id,
                        Coach.phone_number == staff.biz_user.phone_number,
                        Coach.in_service == true()
                    ).first()
                    uploaded_by = {'role': 'coach', 'object_id': coach.id}
        video.uploaded_by = uploaded_by

        size = basic_info.get('size')  # 字节
        if height != 0:
            video.height = height
        if width != 0:
            video.width = width
        if duration:
            video.duration = math.ceil(duration)  # 向上取整
            video.code_rate = int((size / 1000) / duration)  # 码率(单位KB/S)

        video_url = basic_info.get('sourceVideoUrl')
        poster = basic_info.get('coverUrl')  # 封面图url
        video_type = basic_info.get('type')
        classification_id = basic_info.get('classificationId')  # 视频分类的ID

        video.biz_id = biz_id
        video.file_id = file_id
        video.size = "%.1f" % float(size / (1024 * 1024))  # byte -> MB
        video.url = video_url
        video.title = title  # 视频标题
        video.poster = poster
        video.video_type = video_type
        video.classification_id = classification_id
        video.created_at = datetime.now()

        db.session.add(video)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return False, '保存失败'

    return True, '保存成功'


# def pull_event():
#     # 拉取消息队列
#     secret_id = cfg['tencent_video']['secret_id']
#     secret_key = cfg['tencent_video']['secret_key']
#     current = int(time.time())
#     nonce = randint(1, pow(2, 32))
#     s = sign.Sign(secret_id, secret_key)
#     params = {
#         'SecretId': secret_id,
#         'SignatureMethod': 'HmacSHA1',
#         'Nonce': nonce,
#         'Timestamp': current,
#         'Action': 'PullEvent',
#     }
#     ss = s.make('vod.api.qcloud.com', '/v2/index.php', params,
#                 method='GET')
#
#     url = 'https://vod.api.qcloud.com/v2/index.php'
#     params.update({'Signature': ss})
#     r = requests.get(url, params)
#     event_info = r.json()
#     confirm_event(event_info)
#     return event_info


def confirm_event(event_info):
    # 消费消息
    # 目前只处理视频转码的消息
    event_list = event_info.get('eventList')
    if not event_list:
        return
    for event in event_list:
        if event.get('eventContent').get('eventType') == 'TranscodeComplete':
            # 只对转码信息做处理
            # 转码完成
            e_data = event.get('eventContent').get('data')
            if e_data.get('status') != 0:
                # 转码失败
                # 发送错误信息到企业微信
                content = 'status:{status}, {fileId}转码失败, vodTaskId={vodTaskId}, message={message}'.format(
                    status=e_data.get('status'), fileId=e_data.get('fileId'), vodTaskId=e_data.get('vodTaskId'),
                    message=e_data.get('message')
                )
                if _env == 'dev':
                    content = '测试:' + content
                backend_client.message.send_text(
                    agent_id=backend_agent_id,
                    party_ids=[cfg['party_id']['backend']],
                    user_ids=[],
                    content=content
                )
            else:
                # 转码成功
                file_id = e_data.get('fileId')
                video: Video = Video.find(file_id)
                if not video:
                    # 有可能是测试服上传的视频
                    continue
                # 刷新视频信息
                play_set = e_data.get('playSet')
                if play_set:
                    for p in play_set:
                        if p.get('definition') == 30:
                            video.hd_url = p.get('url')
                        elif p.get('definition') == 40:
                            video.fhd_url = p.get('url')
                        elif p.get('definition') == 20:
                            video.sd_url = p.get('url')
                    db.session.commit()
                # refresh_video_info(video)

        # 不论是什么类别的消息都消费掉
        # 消费消息
        secret_id = cfg['tencent_video']['secret_id']
        secret_key = cfg['tencent_video']['secret_key']
        current = int(time.time())
        nonce = randint(1, pow(2, 32))
        s = sign.Sign(secret_id, secret_key)
        params = {
            'SecretId': secret_id,
            'SignatureMethod': 'HmacSHA1',
            'Nonce': nonce,
            'Timestamp': current,
            'Action': 'ConfirmEvent',
            'msgHandle.1': event.get('msgHandle')
        }
        ss = s.make('vod.api.qcloud.com', '/v2/index.php', params,
                    method='GET')
        url = 'https://vod.api.qcloud.com/v2/index.php'
        params.update({'Signature': ss})
        r = requests.get(url, params)
    return


def refresh_video_info(video, intention=None):
    video_info = get_video_info(video.file_id)
    if intention == VideoIntention.POSTER:
        # 获取视频封面
        basic_info = video_info.get('basicInfo')
        refresh_video_basic_info(video, basic_info)
    elif intention == VideoIntention.TRANSCODE:
        # 获取视频转码信息
        transcode_info = video_info.get('transcodeInfo')  # 视频转码信息(转码后才有)
        refresh_video_transcode_info(video, transcode_info)
    else:
        # 其他情况不做刷新
        return
    video.video_info = json.dumps(video_info)
    db.session.commit()
    db.session.refresh(video)
    return


def refresh_video_transcode_info(video, transcode_info):
    transcode_list = transcode_info.get('transcodeList')
    for t in transcode_list:
        if 'templateName' in t.keys():
            if t.get('templateName') == 'MP4-高清-HD':
                video.hd_url = t.get('url')
            elif t.get('templateName') == 'MP4-全高清-FHD':
                video.fhd_url = t.get('url')
            elif t.get('templateName') == 'MP4-标清-SD':
                video.sd_url = t.get('url')
    return


def refresh_video_basic_info(video, basic_info):
    size = basic_info.get('size')  # 字节
    video_url = basic_info.get('sourceVideoUrl')
    poster = basic_info.get('coverUrl')
    video_type = basic_info.get('type')
    classification_id = basic_info.get('classificationId')  # 视频分类的ID

    video.size = "%.1f" % float(size / (1024 * 1024))  # byte -> MB
    video.url = video_url
    video.poster = poster
    video.video_type = video_type
    video.classification_id = classification_id
    video.modified_at = datetime.now()

    return


def get_user_videos(biz_id, role, object_id, permissions, page, page_size):
    uploader = {'role': role, 'object_id': object_id}
    permission_list = get_permissions_name(permissions, biz_id)

    if ManageVideoPermission.name in permission_list or role == ManagerRole.role:
        # 如果有管理视频的权限或者角色是管理员则返回所有视频
        videos: Video = Video.query.filter(
            Video.biz_id == biz_id,
            Video.is_valid == true()
        ).order_by(desc(Video.created_at)).paginate(page=page, per_page=page_size, error_out=False)
        return videos

    if role == BizUserRole.role:
        # pc端
        staff: BizStaff = BizStaff.query.filter(
            BizStaff.id == object_id
        ).first()
        if staff.roles != [CoachRole.role]:
            # 成员只能查看自己上传的视频
            videos: Video = Video.query.filter(
                Video.uploaded_by == uploader,
                Video.is_valid == true()
            ).order_by(desc(Video.created_at)).paginate(page=page, per_page=page_size, error_out=False)
            return videos

        # 教练可以在pc端查看自己在手机或者电脑上上传的视频
        # 由于pc端与小程序端所带token不同,因此上传者需要解析为两个
        coach: Coach = Coach.query.filter(
            Coach.biz_id == staff.biz_id,
            Coach.phone_number == staff.biz_user.phone_number,
            Coach.coach_type == 'private',
            Coach.in_service == true()
        ).first()
        c_uploader = {'role': 'coach', 'object_id': coach.id}
        videos: Video = Video.query.filter(or_(
            Video.uploaded_by == uploader,
            Video.uploaded_by == c_uploader
        ),
            Video.is_valid == true()
        ).order_by(desc(Video.created_at)).paginate(page=page, per_page=page_size, error_out=False)
        return videos

    else:
        # 移动端(教练在小助手点击拍摄视频进入列表)
        coach: Coach = Coach.query.filter(
            Coach.id == object_id
        ).first()
        biz_user: BizUser = BizUser.query.filter(
            BizUser.phone_number == coach.phone_number
        ).first()
        staff: BizStaff = BizStaff.query.filter(
            BizStaff.biz_id == biz_id,
            BizStaff.biz_user_id == biz_user.id
        ).first()
        if staff:
            # 有些版本较低的用户没有staff数据
            s_uploader = {'role': 'biz_user', 'object_id': staff.id}
            videos: Video = Video.query.filter(or_(
                Video.uploaded_by == uploader,
                Video.uploaded_by == s_uploader
            ),
                Video.is_valid == true()
            ).order_by(desc(Video.created_at)).paginate(page=page, per_page=page_size, error_out=False)
        else:
            videos: Video = Video.query.filter(
                Video.uploaded_by == uploader,
                Video.is_valid == true()
            ).order_by(desc(Video.created_at)).paginate(page=page, per_page=page_size, error_out=False)
        return videos


class VideoIntention:
    POSTER = 'get_poster'
    TRANSCODE = 'get_transcode'
