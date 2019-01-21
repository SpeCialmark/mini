from typing import List

import copy
from flask import Blueprint
from flask import jsonify, request, g
from sqlalchemy import desc, true, func

from store.config import cfg
from http import HTTPStatus
from datetime import datetime, timedelta

from store.database import db
from store.domain.cache import BizStaffCache, CustomerCache
from store.manager.utils import get_staff, get_message_unread, get_message_count
from store.utils import time_processing as tp
from store.domain.middle import roles_required, leader_require
from store.domain.models import WorkReport, Department, BizStaff, Trainee
from store.utils.time_formatter import get_yymmdd, yymmdd_to_datetime

blueprint = Blueprint('_work_reports', __name__)


@blueprint.route('', methods=['POST'])
@roles_required()
def post_work_reports():
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    # TODO 目前只有教练能提交报告, 之后需要开发staff也可以提交报告
    staff = get_staff(w_id)
    if not staff:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    departments: List[Department] = Department.query.filter(
        Department.biz_id == staff.biz_id
    ).all()
    department_ids = list(set([d.id for d in departments if staff.id in d.members]))

    name = json_data.get('name')
    content = json_data.get('content')
    trainee_id = json_data.get('trainee_id')  # TODO 目前只有教练提交学员档案,之后扩展时再修改接口

    trainee: Trainee = Trainee.find(trainee_id)
    if not trainee:
        return jsonify(msg='报告对象不存在'), HTTPStatus.NOT_FOUND
    now = datetime.now()
    yymmdd = get_yymmdd(now)

    old_work_report: WorkReport = WorkReport.query.filter(
        WorkReport.staff_id == staff.id,
        WorkReport.yymmdd == yymmdd,
        WorkReport.customer_id == trainee.customer_id
    ).first()
    if not old_work_report:
        work_report = WorkReport(
            biz_id=biz_id,
            staff_id=staff.id,
            customer_id=trainee.customer_id,
            departments=department_ids,
            name=name,
            content=content,
            yymmdd=yymmdd,
            submitted_at=now,
            created_at=now
        )
        db.session.add(work_report)
    else:
        old_work_report.content = content
        old_work_report.modified_at = now
        old_work_report.submitted_at = now
        # 由于允许一天内重复提交报告,因此在重复提交时,重置该报告的浏览记录
        old_work_report.viewers = []

    db.session.commit()

    return jsonify(msg='提交成功')


@blueprint.route('/days', methods=['GET'])
@leader_require()
def get_days():
    biz_id = g.get('biz_id')
    staff_id = g.get('staff_id')
    manager_id = g.get('manager_id')
    viewer_id = manager_id if manager_id else staff_id
    page = request.args.get('page', default=1, type=int)
    limit = request.args.get('limit', default=14, type=int)
    today = tp.get_day_min(datetime.today())

    departments, viewer = get_departments_and_viewer(biz_id, viewer_id)
    if not viewer:
        return jsonify(msg='账号有误'), HTTPStatus.FORBIDDEN

    all_staffs = [m for d in departments for m in d.members]
    res = []
    for i in range(0, page * limit):
        day = today - timedelta(days=i)
        if (today - day).days == 0:
            day_str = "今天"
        elif (today - day).days == 1:
            day_str = "昨天"
        else:
            day_str = day.strftime("%m月%d日")

        yymmdd = get_yymmdd(day)

        # 查询所有信息中自己没有浏览过的
        unread = get_message_unread(all_staffs, viewer, yymmdd)
        message_count = get_message_count(all_staffs, yymmdd)
        res.append({
            "day_str": day_str,
            "yymmdd": yymmdd,
            "unread": unread,
            "message_count": message_count
        })

    return jsonify({
        "days": res
    })


@blueprint.route('/staffs', methods=['GET'])
@leader_require()
def get_staffs():
    """ 获取所有报告列表(根据用户身份来识别访问权限) """
    # 组长只能访问该组的内容, 管理员可以访问所有组的内容
    biz_id = g.get('biz_id')
    staff_id = g.get('staff_id')
    manager_id = g.get('manager_id')
    viewer_id = manager_id if manager_id else staff_id
    yymmdd = request.args.get('yymmdd', default=None, type=int)
    if not yymmdd:
        yymmdd = get_yymmdd(datetime.today())

    res = []
    departments, viewer = get_departments_and_viewer(biz_id, viewer_id)
    if not viewer:
        return jsonify(msg='账号有误'), HTTPStatus.FORBIDDEN

    all_staffs = []
    for d in departments:
        for staff_id in d.members:
            # # 每个组员只有一张卡片, 但一个组员如果从属多个组则可以有多张卡片(可以显示组名)
            # if {str(staff_id): d.id} not in all_staffs:
            # 每个组员只有一张卡片,卡片后没有组名
            if staff_id not in all_staffs:
                brief = WorkReport.get_message_count(staff_id, viewer.id, yymmdd)
                if brief.get('total') == 0:
                    # 没有提交过报告的不需要显示
                    continue
                s_cache = BizStaffCache(staff_id)
                brief.update({
                    "department_name": d.name,
                    "name": s_cache.get("name"),
                    "avatar": s_cache.get("avatar"),
                    "id": s_cache.get("id"),
                    "coach_id": s_cache.get("coach_id"),
                })
                res.append(brief)
                # all_staffs.append({str(staff_id): d.id})
                all_staffs.append(staff_id)

    res.sort(key=lambda x: (x['unread'], x['latest_time']), reverse=True)  # 按照未读数从大到小排序
    return jsonify({
        "work_reports": res
    })


@blueprint.route('/staffs/<string:s_id>', methods=['GET'])
@leader_require()
def get_work_reports(s_id):
    # 获取员工报告列表
    biz_id = g.get('biz_id')
    staff_id = g.get('staff_id')
    manager_id = g.get('manager_id')
    viewer_id = manager_id if manager_id else staff_id
    viewer: BizStaff = BizStaff.query.filter(
        BizStaff.id == viewer_id
    ).first()
    if not viewer:
        return jsonify(msg='账号有误'), HTTPStatus.FORBIDDEN
    staff: BizStaff = BizStaff.find(s_id)
    if not staff:
        return jsonify(msg='员工不存在'), HTTPStatus.NOT_FOUND

    yymmdd = request.args.get('yymmdd', default=None, type=int)
    if yymmdd:
        start_time = tp.get_day_min(yymmdd_to_datetime(yymmdd))
    else:
        start_time = tp.get_day_min(datetime.today())

    end_time = tp.get_day_max(start_time)
    work_reports: List[WorkReport] = WorkReport.query.filter(
        WorkReport.biz_id == biz_id,
        WorkReport.staff_id == staff.id,
        WorkReport.submitted_at >= start_time,
        WorkReport.submitted_at <= end_time
    ).order_by(desc(WorkReport.submitted_at)).all()
    res = []
    for wr in work_reports:
        customer_cache = CustomerCache(wr.customer_id)
        res.append({
            "id": wr.get_hash_id(),
            "name": wr.name,
            "avatar": customer_cache.get('avatar'),
            "is_read": bool(viewer.id in wr.viewers),
            "submitted_at": wr.submitted_at.strftime("%H:%M")
        })

    return jsonify({
        "work_reports": res
    })


@blueprint.route('/staffs/<string:s_id>/reports/<string:wr_id>', methods=['GET'])
@leader_require()
def get_work_report(s_id, wr_id):
    staff_id = g.get('staff_id')
    manager_id = g.get('manager_id')
    viewer_id = manager_id if manager_id else staff_id
    viewer: BizStaff = BizStaff.query.filter(
        BizStaff.id == viewer_id
    ).first()
    if not viewer:
        return jsonify(msg='账号有误'), HTTPStatus.FORBIDDEN

    staff: BizStaff = BizStaff.find(s_id)
    if not staff:
        return jsonify(msg='员工不存在'), HTTPStatus.NOT_FOUND

    work_report: WorkReport = WorkReport.find(wr_id)
    if not work_report:
        return jsonify(msg='报告不存在'), HTTPStatus.NOT_FOUND

    old_viewers = copy.deepcopy(work_report.viewers)
    if viewer.id not in old_viewers:
        old_viewers.append(viewer.id)
        work_report.viewers = old_viewers
        db.session.commit()
        db.session.refresh(work_report)

    viewers = []
    for v_id in work_report.viewers:
        v_cache = BizStaffCache(v_id)
        viewers.append({
            "avatar": v_cache.get('avatar'),
            "name": v_cache.get('name')
        })
    return jsonify({
        "work_report": work_report.content,
        "viewers": viewers
    })


def get_departments_and_viewer(biz_id, staff_id):
    viewer: BizStaff = BizStaff.query.filter(
        BizStaff.id == staff_id
    ).first()
    if g.get('is_root'):
        departments: List[Department] = Department.query.filter(
            Department.biz_id == biz_id,
        ).all()
    elif staff_id:
        departments: List[Department] = Department.query.filter(
            Department.leader_sid == staff_id,
            Department.is_root != true()
        ).all()
    else:
        departments = []
        viewer = None
    return departments, viewer
