from typing import List

from sqlalchemy import desc, asc, true

from store.domain.cache import CourseCache, CoachCache
from store.domain.models import Seat, Diary, Customer, Contract, ContractContent, Trainee
from store.utils.time_formatter import yymmdd_to_datetime


def get_lesson_profile(customer: Customer):
    contract_ids = Contract.get_customer_valid_contract_ids(customer.id)
    contracts: List[Contract] = Contract.query.filter(
        Contract.id.in_(contract_ids),
        Contract.is_valid == true()
    ).order_by(asc(Contract.signed_at)).all()

    res = []
    public_course = {}  # {1:[20, 10], 5:[30, 15], ...}
    personal_course = {}
    for c in contracts:
        contract_content: List[ContractContent] = ContractContent.query.filter(
            ContractContent.contract_id == c.id
        ).all()
        for content in contract_content:
            total = content.total
            attended = content.attended
            if c.is_group:
                if content.course_id not in public_course.keys():
                    public_course.update({content.course_id: [total, attended]})
                else:
                    lesson = public_course[content.course_id]
                    lesson[0] += total
                    lesson[1] += attended
            else:
                if content.course_id not in personal_course.keys():
                    personal_course.update({content.course_id: [total, attended]})
                else:
                    lesson = personal_course[content.course_id]
                    lesson[0] += total
                    lesson[1] += attended

    public_course = get_lesson_brief(public_course, True)
    personal_course = get_lesson_brief(personal_course, False)

    public_course.sort(key=lambda x: (x['name']))
    personal_course.sort(key=lambda x: (x['name']))

    res.extend(public_course)
    res.extend(personal_course)
    return res


def get_seat_profile(seat_hid):
    seat: Seat = Seat.find(seat_hid)
    if seat and not seat.is_check:
        seat_profile = {
            "time": "{start_time}-{end_time}".format(
                start_time=seat.start_time.strftime("%H:%M"),
                end_time=seat.end_time.strftime("%H:%M")
            ),
            "name": '',
            "course_id": '',
            "date": yymmdd_to_datetime(seat.yymmdd).strftime("%m月%d日"),
        }
        if seat.course_id:
            course_cache = CourseCache(seat.course_id)
            course_brief = course_cache.get('brief')
            seat_profile.update({
                "name": course_brief.get('title'),
                "course_id": course_brief.get('id'),
            })
    else:
        seat_profile = {}
    return seat_profile


def get_diary_profile(trainee):
    c_cache = CoachCache(trainee.coach_id)
    # 获取最近一次日记
    diary: Diary = Diary.query.filter(
        Diary.customer_id == trainee.customer_id,
    ).order_by(desc(Diary.recorded_at)).first()
    if not diary:
        diary_profile = {
            'primary_mg': [],
            'training_type': [],
            'date': "",
            'unread': bool(trainee.customer_id in c_cache.get_unread())
        }
    else:
        diary_profile = {
            'primary_mg': diary.primary_mg or [],
            'training_type': diary.get_training_type(trainee.id),
            'date': diary.recorded_at.strftime('%Y年%m月%d日'),
            'unread': bool(trainee.customer_id in c_cache.get_unread())
        }

    return diary_profile


def get_lesson_brief(courses: dict, is_group: bool):
    # {1:[20, 10], 5:[30, 15], ...}
    lessons = []
    for course_id, lesson in courses.items():
        course_cache = CourseCache(course_id)
        course_brief = course_cache.get('brief')
        name = course_brief.get('title')
        if is_group:
            name += "(多人)"
        brief = {
            "id": course_brief.get('id'),
            "name": name,
            "total": lesson[0],
            "attended": lesson[1],
            "remainder": lesson[0] - lesson[1],
            "is_group": is_group
        }
        lessons.append(brief)
    return lessons


def get_trainee_lesson(trainee: Trainee):
    # 学员列表页显示剩余和已上课时(此处不需要区分单人或多人)
    customer_id = trainee.customer_id
    contract_ids = Contract.get_customer_valid_contract_ids(customer_id)
    contract_content: List[ContractContent] = ContractContent.query.filter(
        ContractContent.contract_id.in_(contract_ids),
        ContractContent.is_valid == true()
    ).all()
    total = 0
    attended = 0
    for c in contract_content:
        total += c.total
        attended += c.attended

    return {
        "attended": attended,
        "remainder": total - attended,
    }
