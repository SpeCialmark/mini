from datetime import datetime
from typing import List

from sqlalchemy import or_, true, func

from store.database import db
from store.domain.cache import CoachCache, BizStaffCache
from store.domain.models import Trainee, BizStaff, Coach, Department, WxOpenUser, WorkReport, Course, \
    Customer, Beneficiary, ContractContent, ContractLog
from store.domain.role import CoachRole, StaffRole, ManagerRole


def get_department_brief(department: Department):
    members = department.members or []
    m_res = [get_member_brief_card(m, department.leader_sid) for m in members]
    m_res.sort(key=lambda x: (-x['is_leader']))
    brief = {
        "id": department.get_hash_id(),
        "name": department.name,
        "members": m_res,
        "parent_id": Department.encode_id(department.parent_id) if department.parent_id else 0
    }
    return brief


def get_member_brief_card(staff_id, leader_id=None):
    s_cache = BizStaffCache(staff_id)
    coach_hid = s_cache.get('coach_id')
    if coach_hid:
        c_cache = CoachCache(Coach.decode_id(coach_hid))
        c_brief = c_cache.get('brief')
        brief = {
            "id": s_cache.get("id"),
            "coach_id": c_brief.get('id'),
            "name": c_brief.get('name'),
            "avatar": c_brief.get('avatar'),
            "privates": c_cache.get('privates'),
            "exps": c_cache.get('exps'),
            "measurements": c_cache.get('measurements'),
            "is_leader": bool(staff_id == leader_id)
        }
    else:
        brief = {
            "id": s_cache.get("id"),
            "coach_id": None,
            "name": s_cache.get("name"),
            "avatar": s_cache.get("avatar"),
            "is_leader": bool(staff_id == leader_id)
        }

    return brief


def get_staff(w_id):
    wx_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.id == w_id
    ).first()
    if not wx_user:
        return None
    if wx_user.role == StaffRole.role or wx_user.role == ManagerRole.role or wx_user.role == CoachRole.role:
        staff: BizStaff = BizStaff.query.filter(
            BizStaff.id == wx_user.manager_id
        ).first()
        return staff
    return None


def get_staff_brief(staff: BizStaff):
    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.login_biz_id == staff.biz_id,
        WxOpenUser.manager_id == staff.id
    ).first()
    if wx_open_user:
        avatar = wx_open_user.wx_info.get('avatarUrl')
    else:
        avatar = "https://oss.11train.com/user/avatar/defulate_avatar.png"
    return {
        "id": staff.get_hash_id(),
        "name": staff.name,
        "phone_number": staff.biz_user.phone_number,
        "avatar": avatar
    }


def get_message_unread(all_staffs, viewer: BizStaff, yymmdd):

    work_reports: List[WorkReport] = WorkReport.query.filter(
        WorkReport.yymmdd == yymmdd,
        WorkReport.staff_id.in_(all_staffs),
        # WorkReport.viewers.any(viewer.id)
    ).all()
    unread_report = list(set([wr.staff_id for wr in work_reports if viewer.id not in wr.viewers]))

    return len(unread_report)


def get_message_count(all_staffs, yymmdd):
    work_reports = db.session.query(func.count(WorkReport.id)).filter(
        WorkReport.yymmdd == yymmdd,
        WorkReport.staff_id.in_(all_staffs),
    ).scalar()
    return work_reports


def post_beneficiaries(biz_id, contract_id, beneficiaries):
    for b in beneficiaries:
        name = b.get('name')
        phone_number = b.get('phone_number')
        if not all([name, phone_number]):
            return False, "请将合同填写完整"
        customer: Customer = Customer.query.filter(
            Customer.biz_id == biz_id,
            Customer.phone_number == phone_number
        ).first()
        beneficiary = Beneficiary(
            biz_id=biz_id,
            name=name,
            phone_number=phone_number,
            customer_id=customer.id if customer else None,
            contract_id=contract_id
        )
        db.session.add(beneficiary)
    return True, ""


def post_trainee(biz_id, name, phone_number, coach_id):
    now = datetime.now()
    customer_id = None
    customer: Customer = Customer.query.filter(
        Customer.biz_id == biz_id,
        Customer.phone_number == phone_number
    ).first()
    if customer:
        customer_id = customer.id
    trainee = Trainee(
        phone_number=phone_number,
        name=name,
        coach_id=coach_id,
        customer_id=customer_id,
        is_bind=True,
        bind_at=now,
        created_at=now
    )
    db.session.add(trainee)
    return


def check_contract_content(content):
    course_hids = []
    for c in content:
        course_hid = c.get('course_id')
        coach_hid = c.get('coach_id')
        total = c.get('total')
        attended = c.get('attended')
        price = c.get('price')
        try:
            price = round(float(price), 1)
        except ValueError:
            return False, "请输入正确的价格", content
        if type(total) != int or type(attended) != int:
            return False, "请输入正确的课时数", content
        if attended > total:
            return False, "参数错误", content
        if course_hid in course_hids:
            return False, "请勿选择重复的课程", content
        coach: Coach = Coach.find(coach_hid)
        if not coach:
            return False, "教练不存在", content
        course: Course = Course.find(course_hid)
        if not course:
            return False, "课程不存在", content
        c.update({"course_id": course.id, "coach_id": coach.id})
        course_hids.append(course_hid)
    return True, "", content


def post_content(contract, content, beneficiaries):
    now = datetime.now()
    for c in content:
        coach_id = c.get('coach_id')
        contract_content = ContractContent(
            contract_id=contract.id,
            course_id=c.get('course_id'),
            coach_id=c.get('coach_id'),
            total=c.get('total'),
            attended=c.get('attended'),
            price=c.get('price'),
            created_at=now,
            is_group=contract.is_group
        )
        db.session.add(contract_content)
        for b in beneficiaries:
            name = b.get('name')
            phone_number = b.get('phone_number')
            trainee: Trainee = Trainee.query.filter(
                Trainee.phone_number == phone_number,
                Trainee.coach_id == coach_id
            ).first()
            if not trainee:
                post_trainee(contract.biz_id, name, phone_number, coach_id)
    return


def post_contract_log(biz_id, contract_id, staff_id, operation):
    log = ContractLog(
        biz_id=biz_id,
        contract_id=contract_id,
        staff_id=staff_id,
        operation=operation,
        operated_at=datetime.now()
    )
    db.session.add(log)
    db.session.commit()
    return
