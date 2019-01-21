from datetime import datetime
from typing import List

import copy
from sqlalchemy import true, asc, desc

from store.database import db
from store.domain.cache import CoachCache
from store.domain.models import Diary, Seat, SeatStatus, DiaryImage, Trainee
from store.utils.time_formatter import get_yymmdd, get_hhmm, yymmdd_to_datetime
from store.utils import time_processing as tp


def update_diary_body_data(diary: Diary, records: List):
    # [{'unit': 'kg', 'data': 45.5, 'name': '体重'}}, {'unit': 'bust', 'cm': 65.2, 'name': '胸围'}}, {...}]
    body_data = copy.deepcopy(diary.body_data) or []
    new_body_data = []
    if not diary.body_data:
        for r in records:
            new_body_data.append({
                'name': r.get('name'),
                'unit': r.get('unit'),
                'data': r.get('data')
            })

    else:
        old_b_name = [b.get('name') for b in body_data]
        for r in records:
            if r.get('name') not in old_b_name:
                new_body_data.append({
                    'name': r.get('name'),
                    'data': r.get('data'),
                    'unit': r.get('unit')
                })
                records.remove(r)

        for b_data in body_data:
            for r in records:
                if r.get('name') == b_data.get('name'):
                    b_data['data'] = r.get('data')
                    break

        new_body_data.extend(body_data)
    diary.body_data = new_body_data
    diary.modified_at = datetime.now()
    db.session.commit()
    return


def get_nearest_seat(date, customer_id):
    today_yymmdd = get_yymmdd(date)
    # 查询未来距离现在最近的一节待上课的课
    s: Seat = Seat.query.filter(
        Seat.is_valid == true(),
        Seat.customer_id == customer_id,
        Seat.status == SeatStatus.CONFIRMED.value,
        Seat.yymmdd >= today_yymmdd,
    ).order_by(desc(Seat.yymmdd), asc(Seat.start)).first()
    if s:
        coach_cache = CoachCache(s.coach_id)
        brief = coach_cache.get('brief')
        c_name = brief.get('name')
        start_time, end_time = get_hhmm(s.start, s.end)
        time_str = start_time + '-' + end_time
        if s.yymmdd == today_yymmdd:
            status = '今日有课'
        elif s.yymmdd > today_yymmdd:
            status = '下次上课'
        else:
            status = ''
        return {
            'coach_name': c_name,
            'time': time_str,
            'date': yymmdd_to_datetime(s.yymmdd).strftime('%m.%d'),
            'status': status
        }

    return {}


def get_nearest_seat_tip(date, customer_id):
    today_yymmdd = get_yymmdd(date)
    # 查询未来距离现在最近的一节待上课的课
    s: Seat = Seat.query.filter(
        Seat.is_valid == true(),
        Seat.customer_id == customer_id,
        Seat.status == SeatStatus.CONFIRMED.value,
        Seat.yymmdd >= today_yymmdd,
    ).order_by(desc(Seat.yymmdd), asc(Seat.start)).first()
    if s:
        s_date = yymmdd_to_datetime(s.yymmdd)
        week = tp.get_week(s_date)
        week_chstr = tp.transform_week_chstr(week)
        return "⏰下一次私教课在{date_str} 星期{week_chstr}".format(
            date_str=s_date.strftime('%m月%d日'),
            week_chstr=week_chstr
        )
    return None


def post_diary_image(diary, image_url):
    # 上传图片至健身相册
    d_images = copy.deepcopy(diary.images) or []
    if len(d_images) == 6:
        return '图片不能超过6张'
    d_images.append(image_url)
    image = DiaryImage(
        customer_id=diary.customer_id,
        image=image_url,
        created_at=diary.recorded_at
    )
    db.session.add(image)
    diary.images = d_images
    diary.modified_at = datetime.now()
    db.session.commit()
    return '修改成功'


def delete_diary_image(diary, i_id):
    # 删除日记图片
    diary_image: DiaryImage = DiaryImage.find(i_id)
    if not diary_image:
        return "图片不存在"
    d_images = copy.deepcopy(diary.images) or []
    if not d_images:
        return "图片不存在"
    if diary_image.image not in d_images:
        return "图片不存在"
    d_images.remove(diary_image.image)
    diary.images = d_images
    diary.modified_at = datetime.now()
    db.session.delete(diary_image)
    db.session.commit()
    return "删除成功"


def get_coach_notes(coach_note):
    if not coach_note:
        return []

    coach_notes = []
    for c in coach_note:
        coach_id = c.get('coach_id')
        coach_cache = CoachCache(coach_id)
        brief = coach_cache.get('brief')
        avatar = brief.get('avatar')
        coach_notes.append({
            'avatar': avatar,
            'note': c.get('note')
        })
    return coach_notes


def update_coach_unread(customer_id):
    trainees: List[Trainee] = Trainee.query.filter(
        Trainee.customer_id == customer_id,
        Trainee.is_bind == true()
    ).all()
    coach_ids = [t.coach_id for t in trainees]
    for c_id in coach_ids:
        CoachCache(c_id).set_unread(customer_id)
    return
