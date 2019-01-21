from datetime import datetime
from http import HTTPStatus
from typing import List

from flask import Blueprint, g, jsonify, request
from sqlalchemy import asc, desc

from store.config import get_res
from store.database import db
from store.domain.cache import DiaryUnreadCache
from store.domain.key_data import get_all_type, get_nearest_record, check_key_data
from store.domain.middle import roles_required, customer_id_require, permission_required
from store.domain.models import Plan, Customer, PlanStatus
from store.domain.permission import ManagePrivateCoachPermission
from store.domain.role import CustomerRole, CoachRole
from store.utils.logs import post_log
from store.utils import time_processing as tp

blueprint = Blueprint('_plan', __name__)


@blueprint.route('/<string:p_id>/key_data_list', methods=['GET'])
@roles_required(CoachRole())
def get_key_data_list(p_id):
    """ 获取关键指标列表 """
    plan: Plan = Plan.find(p_id)
    key_data_list, _ = get_all_type(plan)
    res = [{'name': k.name, 'unit': k.unit}for k in key_data_list]
    return jsonify({
        'key_data_list': res
    })


@blueprint.route('/customer/base', methods=['GET'])
@customer_id_require()
def get_base():
    """ 获取用户需求与备注 """
    customer_id = g.get('customer_id')
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(), HTTPStatus.NOT_FOUND

    return jsonify({
        'demand': customer.demand,
        'training_note': customer.training_note
    })


@blueprint.route('/customer/base', methods=['PUT'])
@customer_id_require()
def put_base():
    """ 修改用户需求与备注 """
    customer_id = g.get('customer_id')
    customer: Customer = Customer.query.filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        return jsonify(), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    demand = json_data.get('demand')
    training_note = json_data.get('training_note')
    customer.demand = demand
    customer.training_note = training_note
    db.session.commit()

    return jsonify(msg='修改成功')


@blueprint.route('', methods=['GET'])
@customer_id_require()
def get_plans():
    """ 获取用户的所有计划 """
    customer_id = g.get('customer_id')
    plans: List[Plan] = Plan.query.filter(
        Plan.customer_id == customer_id
    ).order_by(desc(Plan.status), asc(Plan.created_at)).all()
    res = [p.get_brief() for p in plans]
    return jsonify({
        'plans': res
    })


@blueprint.route('/<string:p_id>', methods=['GET'])
@customer_id_require()
def get_plan(p_id):
    """ 获取计划详情 """
    plan: Plan = Plan.find(p_id)
    if not plan:
        return jsonify(msg='训练计划不存在'), HTTPStatus.NOT_FOUND
    return jsonify({
        'plan': plan.get_brief()
    })


@blueprint.route('/<string:p_id>', methods=['PUT'])
@roles_required(CoachRole())
def put_plan(p_id):
    """ 修改健身计划 """
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    plan: Plan = Plan.find(p_id)
    if not plan:
        return jsonify(msg='训练计划不存在'), HTTPStatus.NOT_FOUND

    plan_data = request.get_json()
    if not plan_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    if plan.status == PlanStatus.FINISH.value:
        return jsonify(msg='计划已结束'), HTTPStatus.BAD_REQUEST

    title = plan_data.get('title')
    duration = plan_data.get('duration')
    purpose = plan_data.get('purpose')
    suggestion = plan_data.get('suggestion')
    key_data = plan_data.get('key_data')
    if title:
        plan.title = title
    if duration:
        plan.duration = duration
    if purpose:
        plan.purpose = purpose

    plan.suggestion = suggestion

    is_ok, msg, key_data = check_key_data(key_data)
    if not is_ok:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST
    plan.key_data = key_data

    db.session.commit()
    DiaryUnreadCache(plan.customer_id).modified(m_type='plan')
    post_log(
        biz_id=biz_id, operator_id=w_id, operation="修改",
        operating_object_id=plan.customer_id,
        content="健身计划"
    )
    return jsonify(msg='修改成功')


@blueprint.route('/<string:p_id>', methods=['DELETE'])
@roles_required(CoachRole())
def delete_plan(p_id):
    biz_id = g.get('biz_id')
    w_id = g.get('w_id')
    plan: Plan = Plan.find(p_id)
    if not plan:
        return jsonify(msg='计划不存在'), HTTPStatus.NOT_FOUND
    db.session.delete(plan)
    db.session.commit()
    post_log(
        biz_id=biz_id, operator_id=w_id, operation="删除",
        operating_object_id=plan.customer_id,
        content="健身计划"
    )
    return jsonify(msg='删除成功')


@blueprint.route('/<string:p_id>/action', methods=['POST'])
@roles_required(CoachRole())
def action_plan(p_id):
    plan: Plan = Plan.find(p_id)
    now = datetime.now()
    if not plan:
        return jsonify(msg='计划不存在'), HTTPStatus.NOT_FOUND

    if plan.status == PlanStatus.FINISH.value:
        return jsonify(msg='计划已结束'), HTTPStatus.NOT_FOUND
    if plan.status == PlanStatus.ACTION.value:
        return jsonify(msg='计划已经启动'), HTTPStatus.NOT_FOUND

    effective_plan = Plan.get_effective_plan(plan.customer_id)
    if effective_plan:
        return jsonify(msg='已有启动中的计划'), HTTPStatus.BAD_REQUEST
    plan.effective_at = tp.get_day_min(now)
    plan.status = PlanStatus.ACTION.value
    db.session.commit()
    return jsonify()


@blueprint.route('/<string:p_id>/finish', methods=['POST'])
@roles_required(CoachRole())
def complete_plan(p_id):
    plan: Plan = Plan.find(p_id)
    now = datetime.now()
    if not plan:
        return jsonify(msg='计划不存在'), HTTPStatus.NOT_FOUND

    if plan.status == PlanStatus.FINISH.value:
        return jsonify(msg='计划已结束'), HTTPStatus.NOT_FOUND
    if plan.status == PlanStatus.READY.value:
        return jsonify(msg='计划尚未开启'), HTTPStatus.NOT_FOUND

    nearest_record = get_nearest_record(plan.customer_id, plan)
    res = []
    for r in nearest_record:
        name = r.get('name')
        target = r.get('target')
        data = r.get('data')
        initial_data = r.get('initial_data')
        if target and data:
            data = round(float(data), 1)
            target = round(float(target), 1)
            initial_data = round(float(initial_data), 1)
            if initial_data < target:
                if data == target:
                    change_str = '恭喜您!达成目标!请继续坚持.'
                elif data > target:
                    change_str = '恭喜您!超额完成目标!比目标超出了{data}{unit}.请继续坚持.'.format(data=data-target, unit=r.get('unit'))
                else:
                    change_str = '很遗憾,您没能达成目标.距目标还差{data}{unit}.请继续坚持.'.format(data=target-data, unit=r.get('unit'))
            else:
                if data == target:
                    change_str = '恭喜您!达成目标!请继续坚持.'
                elif data < target:
                    change_str = '恭喜您!超额完成目标!比目标超出了{data}{unit}.请继续坚持.'.format(data=target-data, unit=r.get('unit'))
                else:
                    change_str = '很遗憾,您没能达成目标.距目标还差{data}{unit}.请继续坚持.'.format(data=data-target, unit=r.get('unit'))
            res.append({
                'name': name,
                'change': change_str,
                'data': data,
                'target': target
            })

    # 若是提前结束则该阶段的时长为截止日期的时长
    plan.duration = (tp.get_day_min(now) - plan.effective_at).days + 1
    plan.result = res
    plan.finished_at = now
    plan.status = PlanStatus.FINISH.value
    plan.modified_at = now
    db.session.commit()
    return jsonify()


@blueprint.route('/sections', methods=['GET'])
def get_sections():
    plan_sections = get_res(directory='plan_section', file_name='plan_section.yml').get('plan_sections')
    return jsonify({
        "sections": plan_sections
    })


@blueprint.route('/migrate', methods=['PUT'])
@permission_required(ManagePrivateCoachPermission())
def migrate_plans():
    """ 迁移线上数据 """
    biz_id = g.get('biz_id')
    plan: List[Plan] = Plan.query.filter(
        Plan.biz_id == biz_id
    ).all()
    now = datetime.now()
    for p in plan:
        customer: Customer = Customer.query.filter(
            Customer.id == p.customer_id
        ).first()
        if p.demand:
            customer.demand = p.demand
        if p.note:
            customer.training_note = p.note

        if p.effective_at <= now <= p.closed_at:
            p.status = PlanStatus.ACTION.value
        elif p.effective_at > now:
            p.status = PlanStatus.READY.value
        elif p.closed_at < now:
            p.status = PlanStatus.FINISH.value
    db.session.commit()
    return jsonify()
