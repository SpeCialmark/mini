from flask import Blueprint
from flask import jsonify, request, g
from http import HTTPStatus
from sqlalchemy import true, desc, func, null, or_, asc
from datetime import datetime
from store.database import db
from store.domain.cache import CoachCache, TokenCache, WxOpenUserCache, DepartmentCache, CourseCache, \
    AppCache, StoreBizCache, TraineeCache, BizStaffCache
from store.domain.models import StoreBiz, Coach, Department, BizStaff, BizUser, WxOpenUser, WorkReport, Trainee, Course, \
    Contract, Customer, WxAuthorizer, AppMark, Beneficiary, Plan, ContractContent, ContractLog
from store.domain.middle import roles_required, leader_require, root_department_require
from store.domain.role import ManagerRole, StaffRole
import re
from typing import List

from store.manager.utils import get_department_brief, get_member_brief_card, get_staff_brief, post_beneficiaries, \
    check_contract_content, post_content, post_contract_log
from store.utils import time_processing as tp
from store.utils.sms import verify_sms_code

blueprint = Blueprint('_manager', __name__)


def from_coach_get_staff(coach: Coach):
    biz_user: BizUser = BizUser.query.filter(
        BizUser.phone_number == coach.phone_number
    ).first()
    if not biz_user:
        return None
    staff: BizStaff = BizStaff.query.filter(
        BizStaff.biz_id == coach.biz_id,
        BizStaff.biz_user_id == biz_user.id
    ).first()
    return staff


@blueprint.route('/staffs', methods=['GET'])
@root_department_require()
def get_staffs():
    """ 创建部门时获取成员列表 """
    biz_id = g.get('biz_id')
    # 查询所有私教
    coaches: List[Coach] = Coach.query.filter(
        Coach.biz_id == biz_id,
        Coach.in_service == true(),
        Coach.coach_type == "private",
        Coach.phone_number != null()
    ).all()
    # 获取所有教练的手机号码
    phone_numbers = list(set([c.phone_number for c in coaches]))

    # 获取所有手机号码不在教练手机号码中的biz_user
    biz_users: List[BizUser] = BizUser.query.filter(
        BizUser.phone_number.notin_(phone_numbers)
    ).all()

    biz_user_ids = [b.id for b in biz_users]
    # 获取当前门店下手机号码不是教练的staff
    staffs: List[BizStaff] = BizStaff.query.filter(
        BizStaff.biz_id == biz_id,
        BizStaff.biz_user_id.in_(biz_user_ids)
    ).all()

    all_coach = []

    for c in coaches:
        staff = from_coach_get_staff(c)
        if staff:
            all_coach.append({
                "id": staff.get_hash_id(),
                "coach_id": c.get_hash_id(),
                "avatar": c.avatar,
                "name": c.name,
                "phone_number": c.phone_number
            })

    all_staff = [get_staff_brief(s) for s in staffs]
    # 建组的时候提供成员列表(通过staff_id来进行区别)
    return jsonify({
        "staffs": all_staff,
        "coaches": all_coach,
    })


@blueprint.route('/phone_login', methods=['POST'])
def phone_login():
    """ 管理端登陆 """
    # 访问phone_login之前先访问wx_login和put_user_info确保能够拿到wx头像
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    phone_number = json_data.get('phone_number')
    if not phone_number or not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    sms_code = json_data.get('sms_code')
    if not sms_code:
        return jsonify(msg='验证码缺失'), HTTPStatus.BAD_REQUEST

    login_biz_id = json_data.get('biz_id')
    login_store: StoreBiz = StoreBiz.find(login_biz_id)
    if not login_store:
        return jsonify(msg='所选门店不存在'), HTTPStatus.NOT_FOUND
    verified, msg = verify_sms_code(phone_number=phone_number, sms_code=sms_code)
    if not verified:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    token = request.headers.get('token')
    token_cache = TokenCache(token=token)

    app_id, open_id = token_cache.get('app_id', 'open_id')
    wx_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.app_id == app_id,
        WxOpenUser.wx_open_id == open_id
    ).first()
    # 将登陆的biz_id绑定到wx_user中
    wx_user.login_biz_id = login_store.id
    db.session.commit()
    db.session.refresh(wx_user)

    wx_open_user_cache = WxOpenUserCache(app_id=app_id, open_id=open_id)
    # 刷新缓存中的biz_id
    wx_open_user_cache.reload()
    biz_id, token, client_role = wx_open_user_cache.get('biz_id', 'token', 'client_role')

    store_biz: StoreBiz = StoreBiz.query.filter(
        StoreBiz.id == biz_id
    ).first()

    biz_user: BizUser = BizUser.query.filter(
        BizUser.phone_number == phone_number
    ).first()

    if not biz_user:
        return jsonify(msg='该账号尚未注册'), HTTPStatus.NOT_FOUND

    staff: BizStaff = BizStaff.query.filter(
        BizStaff.biz_id == login_store.id,
        BizStaff.biz_user_id == biz_user.id,
    ).first()

    if not staff:
        return jsonify(msg='您还不是该门店的工作人员, 请联系管理员帮您添加'), HTTPStatus.NOT_FOUND

    if biz_user.id == store_biz.biz_user_id:
        wx_open_user_cache.upgrade_to_manager(staff)
        client_role = ManagerRole.role
    else:
        wx_open_user_cache.upgrade_to_staff(staff)
        client_role = StaffRole.role

    return jsonify({
        'token': token,
        'role': client_role,
    })


@blueprint.route('/logout', methods=['POST'])
@roles_required()
def post_logout():
    token = request.headers.get('token')
    token_cache = TokenCache(token=token)
    app_id, open_id = token_cache.get('app_id', 'open_id')
    wx_open_user_cache = WxOpenUserCache(app_id=app_id, open_id=open_id)
    wx_open_user_cache.logout()
    return jsonify()


@blueprint.route('/biz_list', methods=['GET'])
@roles_required()
def get_biz_list():
    # BOSS端获取门店
    app_id = g.get('app_id')
    app_cache = AppCache(app_id)
    biz_id = app_cache.get('biz_id')
    store: StoreBiz = StoreBiz.query.filter(
        StoreBiz.id == biz_id
    ).first()
    if not store:
        return jsonify()

    biz_list: List[StoreBiz] = StoreBiz.query.filter(
        StoreBiz.biz_user_id == store.biz_user_id
    ).all()
    biz_ids = [biz.id for biz in biz_list]

    app_list: List[WxAuthorizer] = WxAuthorizer.query.filter(
        WxAuthorizer.biz_id.in_(biz_ids),
        WxAuthorizer.mark == AppMark.BOSS.value
    ).all()

    res = []
    for app in app_list:
        nick_name = app.nick_name
        app_biz_id = StoreBiz.encode_id(app.biz_id)
        res.append({
            "nick_name": nick_name,
            "biz_id": app_biz_id,
        })

    return jsonify({
        'biz_list': res
    })


@blueprint.route('/departments/root', methods=['POST'])
@roles_required(ManagerRole())
def post_root_department():
    """ 管路员建立根部门 """
    biz_id = g.get("biz_id")
    manager_id = ManagerRole(biz_id).get_id(g.role)
    name = '总部门'
    old_root: Department = Department.query.filter(
        Department.biz_id == biz_id,
        or_(
            Department.is_root == true(),
            Department.name == name
        )
    ).first()
    if old_root:
        return jsonify(msg='总部门已存在'), HTTPStatus.BAD_REQUEST

    department = Department(
        biz_id=biz_id,
        name=name,
        leader_sid=manager_id,
        is_root=True,
        members=[manager_id],
        created_at=datetime.now()
    )
    db.session.add(department)
    db.session.commit()
    return jsonify(msg='添加总部门成功')


@blueprint.route('/departments/root', methods=['GET'])
@root_department_require()
def get_root_department():
    biz_id = g.get('biz_id')
    root: Department = Department.get_root(biz_id)
    if not root:
        store: StoreBiz = StoreBiz.query.filter(
            StoreBiz.id == biz_id
        ).first()
        if not store:
            raise KeyError('store id=' + biz_id + 'is not found')
        manager: BizStaff = BizStaff.query.filter(
            BizStaff.biz_user_id == store.biz_user_id,
            BizStaff.biz_id == biz_id
        ).first()
        if not manager:
            return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND
        root = Department(
            biz_id=biz_id,
            name='总部门',
            leader_sid=manager.id,
            is_root=True,
            members=[manager.id],
            created_at=datetime.now()
        )
        db.session.add(root)
        db.session.commit()
        db.session.refresh(root)

    staffs: List[BizStaff] = BizStaff.query.filter(
        BizStaff.id.in_(root.members),
        BizStaff.biz_id == biz_id
    ).all()

    members = []
    leader = {}
    for s in staffs:
        if s.id == root.leader_sid:
            leader = get_staff_brief(s)
        else:
            members.append(get_staff_brief(s))

    return jsonify({
        "members": members,
        "leader": leader
    })


@blueprint.route('/departments/root', methods=['PUT'])
@roles_required(ManagerRole())
def put_root_department():
    biz_id = g.get("biz_id")
    json_data = request.get_json()
    manager_id = ManagerRole(biz_id).get_id(g.role)
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    members = json_data.get('members')
    root: Department = Department.get_root(biz_id)
    if not root:
        return jsonify()

    new_members = [BizStaff.decode_id(m.get('id')) for m in members]
    if manager_id not in new_members:
        new_members.append(manager_id)
    root.members = new_members
    root.modified_at = datetime.now()
    db.session.commit()
    return jsonify(msg='修改成功')


@blueprint.route('/departments', methods=['POST'])
@root_department_require()
def post_departments():
    """ 新增部门(组) """
    biz_id = g.get("biz_id")
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    name = json_data.get('name')
    leader_sid = json_data.get('leader_id')
    members = json_data.get('members')
    parent_id = json_data.get('parent_id')

    old_department: Department = Department.query.filter(
        Department.biz_id == biz_id,
        Department.name == name
    ).first()
    if old_department:
        return jsonify(msg='该部门已存在'), HTTPStatus.BAD_REQUEST

    leader: BizStaff = BizStaff.find(leader_sid)
    if not leader:
        return jsonify(msg='员工不存在'), HTTPStatus.NOT_FOUND

    now = datetime.now()
    try:
        department = Department(
            biz_id=biz_id,
            leader_sid=leader.id,
            name=name,
            created_at=now
        )
        db.session.add(department)
        db.session.flush()
        db.session.refresh(department)
        if parent_id:
            # 如果选择了父部门
            parent: Department = Department.find(parent_id)
            if not parent:
                return jsonify(msg='上级部门不存在'), HTTPStatus.NOT_FOUND
            department.parent_id = parent.id
        else:
            # 没有选择父部门则默认父部门为该门店下的根部门
            department.parent_id = Department.get_root_id(biz_id)

        member_ids = [BizStaff.decode_id(m.get('id')) for m in members]
        department.members = member_ids
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e
    DepartmentCache(department.id).reload()
    return jsonify(msg='添加成功')


@blueprint.route('/departments', methods=['GET'])
@leader_require()
def get_departments():
    """ 获取部门(组) """
    biz_id = g.get('biz_id')
    staff_id = g.get('staff_id')
    is_root = g.get('is_root')
    if is_root:
        # 管理组成员可查看所有的部门
        all_departments: List[Department] = Department.query.filter(
            Department.biz_id == biz_id,
            Department.is_root != true()
        ).order_by(desc(Department.created_at)).all()

    elif staff_id:
        # 组长访问
        departments: List[Department] = Department.query.filter(
            Department.biz_id == biz_id,
            Department.leader_sid == staff_id,
            Department.is_root != true()
        ).order_by(desc(Department.created_at)).all()
        all_departments = []
        for d in departments:
            all_departments.append(d)
            all_departments.extend(d.get_children())
    else:
        return jsonify(msg='暂无权限'), HTTPStatus.FORBIDDEN

    res = [get_department_brief(d) for d in all_departments]
    return jsonify({
        "departments": res,
        "is_root": is_root  # 用于显示新增分组按钮
    })


@blueprint.route('/departments/<string:d_id>', methods=['GET'])
@leader_require()
def get_department(d_id):
    department: Department = Department.find(d_id)
    if not department:
        return jsonify(msg='部门不存在'), HTTPStatus.NOT_FOUND
    members = department.members or []
    res = [get_member_brief_card(m, department.leader_sid) for m in members]
    if department.parent_id:
        parent_id = Department.encode_id(department.parent_id)
    else:
        parent_id = Department.get_root(department.biz_id).get_hash_id()
    return jsonify({
        "name": department.name,
        "members": res,
        "parent_id": parent_id
    })


@blueprint.route('/departments/<string:d_id>', methods=['PUT'])
@root_department_require()
def put_department(d_id):
    """ 修改部门(组)(只有管理员能对组进行修改) """
    department: Department = Department.find(d_id)
    if not department:
        return jsonify(msg='部门不存在'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    name = json_data.get('name')
    leader_sid = json_data.get('leader_id')
    members = json_data.get('members')
    parent_id = json_data.get('parent_id')

    leader: BizStaff = BizStaff.find(leader_sid)
    if not leader:
        return jsonify(msg='员工不存在'), HTTPStatus.NOT_FOUND

    if parent_id:
        parent: Department = Department.find(parent_id)
        if not parent:
            return jsonify(msg='上级部门不存在'), HTTPStatus.NOT_FOUND
        children_ids = department.get_children_ids()
        if parent.id in children_ids:
            return jsonify(msg='无法选择子部门作为所属部门'), HTTPStatus.BAD_REQUEST
        department.parent_id = parent.id

    if name:
        department.name = name

    if leader_sid:
        department.leader_sid = BizStaff.decode_id(leader_sid)

    if members:
        member_ids = [BizStaff.decode_id(m.get('id')) for m in members]
        department.members = member_ids

    db.session.commit()
    db.session.refresh(department)
    DepartmentCache(department.id).reload()

    return jsonify(msg='修改成功')


@blueprint.route('/departments/<string:d_id>', methods=['DELETE'])
@root_department_require()
def delete_department(d_id):
    """ 删除部门(组) """
    # 不能删除根部门；不能删除含有子部门的部门
    # biz_id = g.get('biz_id')
    department: Department = Department.find(d_id)
    if not department:
        return jsonify(msg='教练组不存在'), HTTPStatus.NOT_FOUND

    if department.get_children():
        return jsonify(msg='不能删除含有子部门的部门'), HTTPStatus.BAD_REQUEST

    if department.is_root:
        return jsonify(msg='不能删除总部门'), HTTPStatus.BAD_REQUEST

    db.session.delete(department)
    db.session.commit()
    DepartmentCache(department.id).delete()

    return jsonify(msg='删除成功')


@blueprint.route('/departments/available_parent', methods=['GET'])
@root_department_require()
def get_available_parent():
    """ 获取可选的父部门 """
    biz_id = g.get('biz_id')
    d_id = request.args.get('id')
    last_parent_hid = Department.get_root(biz_id).get_hash_id()
    if d_id != '0':
        department: Department = Department.find(d_id)
        if not department:
            return jsonify(msg='部门不存在'), HTTPStatus.NOT_FOUND

        children = department.get_children()
        children_ids = []
        for c in children:
            children_ids.append(c.id)
            children_ids.extend(c.get_children_ids())
        children_ids.append(department.id)
        children_ids = list(set(children_ids))
        # 除了自己与子部门及子部门下的子部门外,其他部门都能成为自己的父部门
        available_parent: List[Department] = Department.query.filter(
            Department.biz_id == biz_id,
            Department.id.notin_(children_ids)
        ).all()
        if department.parent_id:
            last_parent_hid = Department.encode_id(department.parent_id)
    else:
        available_parent: List[Department] = Department.query.filter(
            Department.biz_id == biz_id,
        ).all()
    return jsonify({
        'available_parent': [{
            "id": d.get_hash_id(),
            "name": d.name
        } for d in available_parent],
        "last_parent_id": last_parent_hid
    })


@blueprint.route('/wx_open_user', methods=['PUT'])
@root_department_require()
def admin_wx_open_user():
    """ 迁移wx_open_user中的manage_id字段 """
    # 输入int类型的biz_id
    # 查询biz_id下的私教的staff于wx_open_user
    # 将staff_id迁移到wx_open_user的manage_id
    json_data = request.get_json()
    biz_id = json_data['biz_id']

    coaches: List[Coach] = Coach.query.filter(
        Coach.biz_id == biz_id,
        Coach.in_service == true(),
        Coach.coach_type == 'private'
    ).all()

    for coach in coaches:
        staff = from_coach_get_staff(coach)
        if staff:
            wx_user: WxOpenUser = WxOpenUser.query.filter(
                WxOpenUser.coach_id == coach.id
            ).first()
            if wx_user:
                wx_user.manager_id = staff.id
    db.session.commit()
    return jsonify()


@blueprint.route('/coaches/<string:c_id>', methods=['GET'])
@leader_require()
def get_coach_brief(c_id):
    coach: Coach = Coach.find(c_id)
    if not coach:
        return jsonify(msg='教练不存在'), HTTPStatus.NOT_FOUND
    c_cache = CoachCache(coach.id)
    brief = c_cache.get("brief")
    brief.update({
        "phone_number": coach.phone_number
    })
    biz_user: BizUser = BizUser.query.filter(
        BizUser.phone_number == coach.phone_number
    ).first()
    staff: BizStaff = BizStaff.query.filter(
        BizStaff.biz_user_id == biz_user.id,
        BizStaff.biz_id == coach.biz_id
    ).first()
    if staff:
        work_reports = db.session.query(func.count(WorkReport.id)).filter(
            WorkReport.staff_id == staff.id
        ).scalar()
    else:
        work_reports = 0
    return jsonify({
        "brief": brief,
        "exps": c_cache.get("exps"),
        "privates": c_cache.get("privates"),
        "measurements": c_cache.get("measurements"),
        "work_report": work_reports
    })


@blueprint.route('/coach_and_course', methods=['GET'])
@leader_require()
def get_coach_and_course():
    biz_id = g.get('biz_id')
    store_cache = StoreBizCache(biz_id)
    all_course = [{
        "id": c.get('id'),
        "name": c.get('title')
    } for c in store_cache.courses]
    all_coach = [{
        "id": c.get('id'),
        "name": c.get('name')
    } for c in store_cache.coaches]

    return jsonify({
        "courses": all_course,
        "coaches": all_coach
    })


@blueprint.route('/trainee/<string:t_id>/plans_base', methods=['GET'])
@leader_require()
def get_base(t_id):
    """ 获取用户需求与备注 """
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    customer: Customer = Customer.query.filter(
        Customer.id == trainee.customer_id
    ).first()
    if not customer:
        return jsonify(), HTTPStatus.NOT_FOUND

    return jsonify({
        'demand': customer.demand,
        'training_note': customer.training_note
    })


@blueprint.route('/trainee/<string:t_id>/plans', methods=['GET'])
@leader_require()
def get_plans(t_id):
    """ 获取用户的所有计划 """
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    plans: List[Plan] = Plan.query.filter(
        Plan.customer_id == trainee.customer_id
    ).order_by(desc(Plan.status), asc(Plan.created_at)).all()
    res = [p.get_brief() for p in plans]
    return jsonify({
        'plans': res
    })


@blueprint.route('/trainee/<string:t_id>/plans/<string:p_id>', methods=['GET'])
@leader_require()
def get_plan(t_id, p_id):
    """ 获取计划详情 """
    plan: Plan = Plan.find(p_id)
    if not plan:
        return jsonify(msg='训练计划不存在'), HTTPStatus.NOT_FOUND
    return jsonify({
        'plan': plan.get_brief()
    })


@blueprint.route('/trainee/<string:t_id>/contracts', methods=['GET'])
@leader_require()
def get_trainee_contracts(t_id):
    """ 管理端获取学员合同列表 """
    biz_id = g.get('biz_id')
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND

    contract_ids = Beneficiary.get_contract_ids(biz_id, trainee.customer_id, trainee.phone_number)
    contracts: List[Contract] = Contract.query.filter(
        Contract.id.in_(contract_ids)
    ).order_by(desc(Contract.signed_at)).all()
    res = []
    for c in contracts:
        course_ids = c.get_courses()
        res.append({
            "id": c.get_hash_id(),
            "signed_at": c.signed_at.strftime("%m月%d日"),
            "course_names": [CourseCache(course_id).get('brief').get('title') for course_id in course_ids],
            "is_valid": c.is_valid,
            # "is_group": c.is_group,
            "created_at": c.created_at
        })
    res.sort(key=lambda x: (x['created_at']))
    return jsonify({
        "contracts": res
    })


@blueprint.route('/contracts', methods=['GET'])
@leader_require()
def get_contracts():
    """ 工作台中查看合同列表 """
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    if w_id:
        search = request.args.get('search', default=None, type=str)
        if search:
            like_str = '%'
            for w in search:
                like_str += w + '%'

            beneficiary: List[Beneficiary] = Beneficiary.query.filter(
                Beneficiary.biz_id == biz_id,
                or_(
                    Beneficiary.phone_number.ilike(like_str),
                    Beneficiary.name.ilike(like_str)
                )
            ).all()
            contract_ids = list(set([b.contract_id for b in beneficiary]))
            contracts: List[Contract] = Contract.query.filter(
                Contract.id.in_(contract_ids)
            ).order_by(desc(Contract.signed_at), desc(Contract.created_at)).all()
            res = [c.get_brief() for c in contracts]
            return jsonify({
                "all_contracts": res,
                "is_root": g.get('is_root')
            })
        else:
            contracts: List[Contract] = Contract.query.filter(
                Contract.biz_id == biz_id
            ).order_by(desc(Contract.signed_at), desc(Contract.created_at)).all()

        res = []
        last_month = ""
        month_contracts = []
        for c in contracts:
            if c.signed_at.strftime("%Y年%m月") != last_month:
                last_month = c.signed_at.strftime("%Y年%m月")
                month_contracts = []
                res.append({
                    "month": last_month,
                    "contracts": month_contracts
                })
            month_contracts.append(c.get_brief())

        return jsonify({
            "all_contracts": res,
            "is_root": g.get('is_root')
        })
    else:
        # page = request.args.get('page', default=1, type=int)
        date_str = request.args.get('date', default=None, type=str)
        if not date_str:
            date = datetime.today()
        else:
            date = datetime.strptime(date_str, '%Y.%m')
        early_month = tp.get_early_month(date)
        end_month = tp.get_end_month(date)
        contracts: List[Contract] = Contract.query.filter(
            Contract.biz_id == biz_id,
            Contract.signed_at >= early_month,
            Contract.signed_at <= end_month
        ).order_by(desc(Contract.is_valid), desc(Contract.signed_at)).all()
        res = []
        for c in contracts:
            res.append({
                "id": c.get_hash_id(),
                "signed_at": c.signed_at.strftime("%Y.%m.%d"),
                "is_valid": c.is_valid,
                "is_group": c.is_group,
                "beneficiary": c.get_beneficiary()
            })
        return jsonify({
            "contracts": res
        })


@blueprint.route('/contracts/<string:c_id>', methods=['GET'])
@leader_require()
def get_contract(c_id):
    """ 查看合同详情 """
    contract: Contract = Contract.find(c_id)
    if not contract:
        return jsonify(msg='合同不存在'), HTTPStatus.NOT_FOUND

    page = contract.get_page()
    content: List[ContractContent] = ContractContent.query.filter(
        ContractContent.contract_id == contract.id
    ).all()
    for c in content:
        coach_cache = CoachCache(c.coach_id)
        course_cache = CourseCache(c.course_id)
        coach_brief = coach_cache.get('brief')
        course_brief = course_cache.get('brief')
        coach_name = coach_brief.get('name')
        course_name = course_brief.get('title')
        brief = {
            "coach_name": coach_name,
            "course_name": course_name,
            "total": c.total,
            "attended": c.attended,
            "price": c.price,
        }
        if brief not in page['content']:
            page['content'].append(brief)

    return jsonify({
        "contract": page
    })


@blueprint.route('/contracts', methods=['POST'])
@root_department_require()
def post_contracts():
    """ 新增合同 """
    biz_id = g.get('biz_id')
    manager_id = g.get('manager_id')
    if not manager_id:
        staff_id = g.get('staff_id')
    else:
        staff_id = manager_id
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    content = json_data.get('content')
    note = json_data.get('note')
    images = json_data.get('images')
    signed_at_str = json_data.get('signed_at')
    beneficiaries = json_data.get('beneficiaries')
    if not all([content, signed_at_str, beneficiaries]):
        return jsonify(msg='请将合同填写完整'), HTTPStatus.BAD_REQUEST

    is_ok, msg, content = check_contract_content(content)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST
    signed_at = datetime.strptime(signed_at_str, '%Y-%m-%d')
    now = datetime.now()
    try:
        contract = Contract(
            biz_id=biz_id,
            content=content,
            note=note,
            signed_at=signed_at,
            created_at=now
        )
        db.session.add(contract)
        db.session.flush()
        db.session.refresh(contract)
        if images:
            contract.images = images
        if len(beneficiaries) > 1:
            contract.is_group = True
        else:
            contract.is_group = False
        # 添加合同受益人
        is_ok, msg = post_beneficiaries(biz_id, contract.id, beneficiaries)
        if not is_ok:
            return jsonify(msg=msg), HTTPStatus.BAD_REQUEST
        # 记录合同内容
        post_content(contract, content, beneficiaries)

        db.session.commit()
        # log
        post_contract_log(biz_id, contract.id, staff_id, "新增合同")
    except Exception as e:
        db.session.rollback()
        raise e
    return jsonify(msg='添加成功')


@blueprint.route('/contracts/<string:c_id>', methods=['PUT'])
@root_department_require()
def put_contract(c_id):
    biz_id = g.get('biz_id')
    manager_id = g.get('manager_id')
    if not manager_id:
        staff_id = g.get('staff_id')
    else:
        staff_id = manager_id
    contract: Contract = Contract.find(c_id)
    if not contract:
        return jsonify(msg='合同不存在'), HTTPStatus.NOT_FOUND
    if not contract.is_valid:
        return jsonify(msg='合同已失效'), HTTPStatus.BAD_REQUEST
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    images = json_data.get("images")
    if images:
        contract.images = images
        db.session.commit()
        # log
        post_contract_log(biz_id, contract.id, staff_id, "修改合同照片")
    return jsonify()


@blueprint.route('/contracts/<string:c_id>', methods=['DELETE'])
@root_department_require()
def delete_contract(c_id):
    """ 删除合同 """
    biz_id = g.get('biz_id')
    manager_id = g.get('manager_id')
    if not manager_id:
        staff_id = g.get('staff_id')
    else:
        staff_id = manager_id
    contract: Contract = Contract.find(c_id)
    if not contract:
        return jsonify(msg='合同不存在'), HTTPStatus.NOT_FOUND
    contract_content: List[ContractContent] = ContractContent.query.filter(
        ContractContent.contract_id == contract.id
    ).all()
    now = datetime.now()
    try:
        contract.is_valid = False
        contract.modified_at = now
        for c in contract_content:
            c.is_valid = False
            c.modified_at = now
        db.session.commit()
        # log
        post_contract_log(biz_id, contract.id, staff_id, "删除合同")
    except Exception as e:
        db.session.rollback()
        raise e
    return jsonify()


@blueprint.route('/contracts/<string:c_id>/note', methods=['PUT'])
@root_department_require()
def put_contract_note(c_id):
    """ 修改备注 """
    biz_id = g.get('biz_id')
    manager_id = g.get('manager_id')
    if not manager_id:
        staff_id = g.get('staff_id')
    else:
        staff_id = manager_id
    contract: Contract = Contract.find(c_id)
    if not contract:
        return jsonify(msg='合同不存在'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify()
    note = json_data.get('note')
    contract.note = note
    db.session.commit()
    # log
    post_contract_log(biz_id, contract.id, staff_id, "修改备注")
    return jsonify()


@blueprint.route('/contracts/migrate', methods=['PUT'])
@root_department_require()
def migrate_contracts():
    """ 合同迁移(主要用于用户更换了手机号的情况) """
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    old_phone_number = json_data.get('old_phone_number')
    new_phone_number = json_data.get('new_phone_number')
    if not old_phone_number or new_phone_number:
        return jsonify()
    beneficiaries: List[Beneficiary] = Beneficiary.query.filter(
        Beneficiary.biz_id == biz_id,
        Beneficiary.phone_number == old_phone_number
    ).all()
    if beneficiaries:
        for b in beneficiaries:
            b.phone_number = new_phone_number
        db.session.commit()
    return jsonify(msg='修改成功')


@blueprint.route('/trainee/<string:t_id>', methods=['PUT'])
@root_department_require()
def put_trainee(t_id):
    """ 修改学员资料(用于数据迁移) """
    trainee: Trainee = Trainee.find(t_id)
    if not trainee:
        return jsonify(msg='学员不存在'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json_data'), HTTPStatus.BAD_REQUEST

    phone_number = json_data.get('phone_number')
    name = json_data.get('name')
    age = json_data.get('age')
    gender = json_data.get('gender')
    tags = json_data.get('tags')
    note = json_data.get('note')

    if name:
        trainee.name = name
    if age:
        trainee.age = age
    if gender:
        trainee.gender = gender
    if tags or tags == []:
        trainee.tags = tags
    if note or note == "":
        trainee.note = note
    if phone_number or phone_number == "":
        trainee.phone_number = phone_number

    db.session.commit()
    trainee_cache = TraineeCache(coach_id=trainee.coach_id, customer_id=trainee.customer_id)
    trainee_cache.reload()
    return jsonify(msg='修改成功')


@blueprint.route('/change_biz', methods=['PUT'])
@root_department_require()
def change_biz():
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    change_biz_id = json_data.get('biz_id')
    change_store: StoreBiz = StoreBiz.find(change_biz_id)
    if not change_store:
        return jsonify(msg='所选门店不存在'), HTTPStatus.NOT_FOUND
    token = request.headers.get('token')
    token_cache = TokenCache(token=token)

    app_id, open_id = token_cache.get('app_id', 'open_id')

    # 获取当前用户
    wx_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.app_id == app_id,
        WxOpenUser.wx_open_id == open_id
    ).first()
    if not wx_user:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

    # 获取当前用户的staff_id
    staff_id = wx_user.manager_id

    staff: BizStaff = BizStaff.query.filter(
        BizStaff.id == staff_id
    ).first()

    # 查询所选店家相同biz_user的staff
    change_staff: BizStaff = BizStaff.query.filter(
        BizStaff.biz_user_id == staff.biz_user_id,
        BizStaff.biz_id == change_store.id
    ).first()
    if not change_staff:
        return jsonify(msg='您还不是该门店的工作人员, 请联系管理员帮您添加'), HTTPStatus.NOT_FOUND

    wx_user.login_biz_id = change_store.id
    db.session.commit()
    db.session.refresh(wx_user)

    wx_open_user_cache = WxOpenUserCache(app_id=app_id, open_id=open_id)
    # 刷新缓存中的biz_id
    wx_open_user_cache.reload()
    token, client_role = wx_open_user_cache.get('token', 'client_role')
    wx_open_user_cache.reload()
    wx_open_user_cache.set({'biz_id': change_store.id})
    if change_staff.biz_user_id == change_store.biz_user_id:
        wx_open_user_cache.upgrade_to_manager(change_staff)
        client_role = ManagerRole.role
    else:
        wx_open_user_cache.upgrade_to_staff(change_staff)
        client_role = StaffRole.role

    return jsonify({
        'token': token,
        'role': client_role,
    })


@blueprint.route('/contract_log', methods=['GET'])
@root_department_require()
def get_contract_log():
    biz_id = g.get('biz_id')
    logs: List[ContractLog] = ContractLog.query.filter(
        ContractLog.biz_id == biz_id
    ).order_by(desc(ContractLog.operated_at)).all()

    res = []
    month_logs = []
    last_month = ""
    for l in logs:
        month = l.operated_at.strftime("%Y年%m月")
        if month != last_month:
            last_month = month
            month_logs = []
            res.append({
                "month": month,
                "logs": month_logs
            })
        contract: Contract = Contract.query.filter(
            Contract.id == l.contract_id
        ).first()
        c_brief = contract.get_page()
        staff_cache = BizStaffCache(l.staff_id)
        staff = {
            "name": staff_cache.get('name'),
            "avatar": staff_cache.get('avatar'),
            "phone_number": staff_cache.get('phone_number'),
        }
        month_logs.append({
            "staff": staff,
            "contract": c_brief,
            "operation": l.operation,
            "operated_at": l.operated_at.strftime("%Y年%m月%d日 %H:%M")
        })
    return jsonify(res)
