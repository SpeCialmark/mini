import re
from datetime import datetime
from http import HTTPStatus
from typing import List

from flask import Blueprint
from flask import jsonify, request, g
from sqlalchemy import desc, true, null, asc

from store.config import cfg, _env
from store.database import db
from store.domain.cache import AppCache
from store.domain.models import Agent, Case, Qrcode, Question, WxAuthorizer
from store.domain.wxapp import ReleaseQrcode
from store.utils.sms import verify_sms_code
from store.wxopen import agent_client, agent_agent_id

blueprint = Blueprint('_agent', __name__)


@blueprint.route('', methods=['POST'])
def post_agent():
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    name = json_data.get('name')
    phone_number = json_data.get('phone_number')
    area = json_data.get('area')
    email = json_data.get('email')  # 选填
    if not all([name, phone_number, area]):
        return jsonify(msg='请将信息填写完整'), HTTPStatus.BAD_REQUEST

    if not re.match('^\d{11}$', phone_number):
        return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST

    if area not in cfg['area'].keys():
        return jsonify(msg='地区有误'), HTTPStatus.BAD_REQUEST

    old_agent: Agent = Agent.query.filter(
        Agent.name == name,
        Agent.phone_number == phone_number
    ).first()
    if old_agent:
        return jsonify(msg='您已经是咱们的合作伙伴啦,不需要再次申请'), HTTPStatus.BAD_REQUEST

    agent = Agent(
        name=name,
        phone_number=phone_number,
        area=area,
        email=email if email else None,
        created_at=datetime.now()
    )
    db.session.add(agent)
    db.session.commit()
    db.session.refresh(agent)
    area_name = cfg['area'][area]
    send_message(agent, area_name)

    return jsonify(msg='我们已经收到您的申请,工作人员将会尽快和您联系')


@blueprint.route('/<string:a_id>', methods=['PUT'])
def put_agent(a_id):
    agent: Agent = Agent.find(a_id)
    if not agent:
        return jsonify(msg='合伙人不存在'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    name = json_data.get('name')
    phone_number = json_data.get('phone_number')
    sms_code = json_data.get('sms_code')
    area = json_data.get('area')

    verified, msg = verify_sms_code(phone_number=phone_number, sms_code=sms_code)
    if not verified:
        return jsonify(msg=msg), HTTPStatus.BAD_REQUEST

    if name and name != "":
        agent.name = name
    if phone_number and phone_number != "":
        if not re.match('^\d{11}$', phone_number):
            return jsonify(msg='手机号码格式有误'), HTTPStatus.BAD_REQUEST
        agent.phone_number = phone_number
    if area and area != "":
        if area not in cfg['area'].keys():
            return jsonify(msg='地区有误'), HTTPStatus.BAD_REQUEST
        agent.area = area

    db.session.commit()
    db.session.refresh(agent)
    return jsonify({
        'name': agent.name,
        'phone_number': agent.phone_number,
        'area': cfg['area'][agent.area]
    })


@blueprint.route('', methods=['GET'])
def get_agents():
    page = request.args.get('page', default=1, type=int)
    page_size = request.args.get('page_size', default=10, type=int)
    agents: Agent = Agent.query.paginate(page=page, per_page=page_size, error_out=False)

    if page == 1 and agents.items == []:
        return jsonify({
            'agents': []
        })

    res = [{
        'name': a.name,
        'phone_number': a.phone_number,
        'area': cfg['area'][a.area]
    } for a in agents.items]

    return jsonify({
        'agents': res
    })


@blueprint.route('/app_list', methods=['GET'])
def get_app_list():
    # 用于在后台录入案例的时候提供可选列表
    apps: List[WxAuthorizer] = WxAuthorizer.query.filter(
        WxAuthorizer.mark != null()
    ).all()
    res = [app.get_brief() for app in apps]
    return jsonify({
        'app_list': res
    })


@blueprint.route('/cases', methods=['POST'])
def post_case():
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    case_app_hid = json_data.get('case_app_id')
    case_image = json_data.get('image')
    app: WxAuthorizer = WxAuthorizer.find(case_app_hid)
    if not all([case_app_hid, case_image]):
        return jsonify(msg='请将资料填写完毕'), HTTPStatus.BAD_REQUEST

    if not app:
        return jsonify(msg='商家不存在'), HTTPStatus.NOT_FOUND

    old_case: Case = Case.query.filter(
        Case.case_app_id == app.app_id
    ).first()
    if old_case:
        return jsonify(msg='该案例已经添加过了'), HTTPStatus.BAD_REQUEST
    case = Case(
        case_app_id=app.app_id,
        image=case_image,
        created_at=datetime.now()
    )
    is_show = json_data.get('is_show')
    if is_show:
        case.is_show = is_show
    db.session.add(case)
    db.session.commit()
    return jsonify(msg='添加成功')


@blueprint.route('/cases', methods=['GET'])
def get_cases():
    cases: List[Case] = Case.query.filter(
        Case.is_show == true()
    ).all()
    res = []
    for c in cases:
        app_cache = AppCache(c.case_app_id)
        case_qrcode: Qrcode = ReleaseQrcode(c.case_app_id).get()
        case_qrcode_url = case_qrcode.get_brief()['url']
        res.append({
            'name': app_cache.get('nick_name'),
            'image': c.image,
            'qrcode': case_qrcode_url
        })
    return jsonify({
        'cases': res
    })


@blueprint.route('/cases/c_id', methods=['PUT'])
def put_case(c_id):
    case: Case = Case.find(c_id)
    if not case:
        return jsonify(msg='案例不存在'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    image = json_data.get('image')
    is_show = json_data.get('is_show')
    if image:
        case.image = image
    if is_show:
        case.is_show = is_show

    db.session.commit()
    db.session.refresh()
    return jsonify(msg='修改成功')


@blueprint.route('/questions', methods=['POST'])
def post_question():
    """ 录入问题到数据库 """
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    title = json_data.get('title')
    answer = json_data.get('answer')
    question_type = json_data.get('question_type')
    is_common = json_data.get('is_common')
    if not all([title, answer, question_type]):
        return jsonify(msg='请填写完整'), HTTPStatus.BAD_REQUEST

    old_question: Question = Question.query.filter(
        Question.title == title
    ).first()
    if old_question:
        return jsonify(msg='该问题已经被录入过了'), HTTPStatus.BAD_REQUEST

    question = Question(
        title=title,
        answer=answer,
        question_type=question_type,
        is_common=is_common,
        created_at=datetime.now()
    )
    db.session.add(question)
    db.session.commit()

    return jsonify(msg='录入成功')


@blueprint.route('/questions', methods=['GET'])
def get_questions():
    """ 获取所有问题列表 """
    q_type = request.args.get('type', default='all', type=str)
    if q_type == 'all':
        questions: List[Question] = Question.query.order_by(asc(Question.created_at)).all()
    else:
        questions: List[Question] = Question.query.filter(
            Question.order_by(asc(Question.created_at)).question_type == q_type
        ).all()
    before_sale = []
    after_sale = []
    on_sale = []
    common = []  # 常见问题
    for q in questions:

        if q.is_common:
            common.append({
                'id': q.get_hash_id(),
                'title': q.title,
            })

        if q.question_type == 'before_sale':
            before_sale.append({
                'id': q.get_hash_id(),
                'title': q.title,
            })
        elif q.question_type == 'after_sale':
            after_sale.append({
                'id': q.get_hash_id(),
                'title': q.title,
            })
        elif q.question_type == 'on_sale':
            on_sale.append({
                'id': q.get_hash_id(),
                'title': q.title,
            })

    return jsonify({
        'before_sale_questions': before_sale,
        'on_sale_questions': on_sale,
        'after_sale_questions': after_sale,
        'common_questions': common
    })


@blueprint.route('/questions/<string:q_id>', methods=['GET'])
def get_question(q_id):
    question: Question = Question.find(q_id)
    if not question:
        return jsonify(msg='问题不存在'), HTTPStatus.NOT_FOUND

    return jsonify({
        'title': question.title,
        'answer': question.answer,
        'is_common': question.is_common,
        'type': question.question_type
    })


@blueprint.route('/questions/<string:q_id>', methods=['PUT'])
def put_question(q_id):
    question: Question = Question.find(q_id)
    if not question:
        return jsonify(msg='问题不存在'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    title = json_data.get('title')
    answer = json_data.get('answer')
    question_type = json_data.get('question_type')
    is_common = json_data.get('is_common')

    if title and title != "":
        question.title = title
    if answer and answer != "":
        question.answer = answer
    if question_type and question_type != "":
        question.question_type = question_type

    question.is_common = is_common
    db.session.commit()
    db.session.refresh(question)

    return jsonify(msg='修改成功')


@blueprint.route('/areas', methods=['GET'])
def get_area():
    areas = cfg['area']
    res = []
    for k, v in areas.items():
        res.append({
            'id': k,
            'name': v
        })
    return jsonify({
        'areas': res
    })


@blueprint.route('/question_type', methods=['GET'])
def get_question_type():
    question_type = cfg['question_type']
    res = []
    for k, v in question_type.items():
        res.append({
            'key': k,
            'name': v
        })
    return jsonify({
        'question_type': res
    })


def send_message(agent: Agent, area_name):
    content = '{name}申请成为我们的{area}地区的合伙人. 手机号:{phone_number}'.format(
        name=agent.name, area=area_name, phone_number=agent.phone_number
    )
    if _env == 'dev':
        content = '测试:'
    agent_client.message.send_text(
        agent_id=agent_agent_id,
        party_ids=[cfg['party_id']['all']],
        user_ids=[],
        content=content
    )
    return
