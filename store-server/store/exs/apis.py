from typing import List
from flask import Blueprint
from flask import jsonify, request, g
from store.domain.role import AdminRole, UNDEFINED_BIZ_ID
from store.domain.middle import roles_required, customer_id_require
from store.domain.models import Ex, ExProperty, Gender, ExHistory, Trainee, DUMMY_ID
from store.domain.cache import CustomerCache
from http import HTTPStatus
from datetime import datetime
from store.config import cfg
from store.database import db
from store.domain.cache import ExCache
from sqlalchemy import or_, and_, asc, true, desc
import re
from sqlalchemy.dialects.postgresql import HSTORE, hstore, array
from store.domain.role import CustomerRole, CoachRole

blueprint = Blueprint('_exs', __name__)

en_word = re.compile('^[a-zA-Z]+$')


def get_brief_card(ex_cache: ExCache, gender: int):
    title, pictures = ex_cache.get('title', 'pictures')
    if gender == Gender.FEMALE:
        illustration = cfg['aliyun_oss']['cdn_host'] + '/' +\
                       cfg['aliyun_oss']['ex_path'].format(file_name=pictures['F'])
    else:
        illustration = cfg['aliyun_oss']['cdn_host'] + '/' + \
                       cfg['aliyun_oss']['ex_path'].format(file_name=pictures['M'])
    return {
        'id': Ex.encode_id(ex_cache.id),
        'title': title,
        'illustration': illustration
    }


def get_illustration(ex: Ex, gender) -> str:
    if gender == Gender.FEMALE:
        illustration = cfg['aliyun_oss']['cdn_host'] + '/' +\
                       cfg['aliyun_oss']['ex_path'].format(file_name=ex.pictures['F'])
    else:
        illustration = cfg['aliyun_oss']['cdn_host'] + '/' + \
                       cfg['aliyun_oss']['ex_path'].format(file_name=ex.pictures['M'])
    return illustration


@blueprint.route('', methods=['GET'])
@customer_id_require()
def get_exs():
    customer_id = g.customer_id
    gender = CustomerCache(customer_id).get('gender')

    category = request.args.get('category', None, type=str)
    muscle_group = request.args.get('muscle_group', None, type=str)
    recent = request.args.get('recent', 0, type=int)
    search: str = request.args.get('search', '', type=str)

    page = request.args.get('page', 0, type=int)
    page_count = 15
    offset = page * page_count

    if muscle_group:
        # 1、胸肌（胸肌）
        # 2、肩部肌群（颈部肌群、肩部）
        # 3、背部肌群（背阔肌、上背肌)
        # 4、手臂（肱二头肌、肱三头肌、前臂、手腕）
        # 5、臀部肌群（臀部肌群）
        # 6、腿部肌群（膝关节、股四头肌、大腿后侧肌、小腿肌群、脚踝）
        # 7、腰腹肌群（腹肌、侧腹肌、下背肌、脊柱）
        if muscle_group not in ['胸肌', '肩部肌群', '背部肌群', '手臂', '臀部肌群', '腿部肌群', '腰腹肌群']:
            return jsonify(
                msg='muscle_group取值为胸肌，肩部肌群，背部肌群，手臂，臀部肌群，腿部肌群，腰腹肌群'), HTTPStatus.BAD_REQUEST

        if muscle_group == '胸肌':
            array_str = """ ARRAY[CAST('chest' as varchar)] """
        elif muscle_group == '肩部肌群':
            array_str = """ ARRAY[CAST('neck-upper-traps' as varchar), CAST('shoulders' as varchar)] """
        elif muscle_group == '背部肌群':
            array_str = """ ARRAY[CAST('middle-back-lats' as varchar), CAST('upper-back-lower-traps' as varchar)] """
        elif muscle_group == '手臂':
            array_str = """
ARRAY[CAST('biceps' as varchar), CAST('triceps' as varchar), CAST('forearms' as varchar), CAST('wrists' as varchar)] """
        elif muscle_group == '臀部肌群':
            array_str = """ ARRAY[CAST('glutes-hip-flexors' as varchar)] """
        elif muscle_group == '腿部肌群':
            array_str = """ ARRAY[CAST('knees' as varchar), CAST('quadriceps' as varchar),
             CAST('hamstrings' as varchar), CAST('calves' as varchar),CAST('ankles' as varchar)] """
        elif muscle_group == '腰腹肌群':
            array_str = """ ARRAY[CAST('abs' as varchar), CAST('obliques' as varchar),
                        CAST('lower-back' as varchar), CAST('spine' as varchar)] """

        rows = db.engine.execute(
            """
           SELECT id, title, full_name, pictures from ex where ex.primary_mg && {array_str} limit {page_count} offset {offset}
            """.format(array_str=array_str, page_count=page_count, offset=offset)
        )
        exs = []
        for r in rows:
            e_id, e_title, e_full_name, e_pictures = r

            if gender == Gender.FEMALE:
                illustration = cfg['aliyun_oss']['cdn_host'] + '/' + \
                               cfg['aliyun_oss']['ex_path'].format(file_name=e_pictures['F'])
            else:
                illustration = cfg['aliyun_oss']['cdn_host'] + '/' + \
                               cfg['aliyun_oss']['ex_path'].format(file_name=e_pictures['M'])

            exs.append({
                'id': Ex.encode_id(e_id),
                'title': e_title,
                'illustration': illustration
            })

        result = {
            'exs': exs,
            'page': page
        }
        return jsonify(result)

    if recent == 1:
        rs: List[ExProperty] = ExProperty.query.filter(and_(
            ExProperty.customer_id == customer_id)).order_by(
            desc(ExProperty.last_recorded_at)).limit(page_count).offset(offset).all()

        exs = []
        for r in rs:
            if r.ex_id != int(DUMMY_ID):
                exs.append(get_brief_card(ExCache(r.ex_id), gender))
            else:
                exs.append({
                    'id': DUMMY_ID,
                    'title': r.ex_title
                })
        return jsonify({
            'exs': exs,
            'page': page
        })
    if search:
        search = search.strip()
        if not search:
            exs = Ex.query.filter(and_(
                Ex.is_official == true()
            )).order_by(Ex.id.asc()).limit(page_count).offset(offset).all()
        else:
            words = search.split()
            like_str = '%'
            for w in words:
                like_str += w + '%'
            if en_word.match(words[0]):
                exs = Ex.query.filter(and_(
                    Ex.is_official == true(),
                    Ex.full_name.ilike(like_str)
                )).order_by(Ex.id.asc()).limit(page_count).offset(offset).all()
            else:
                exs = Ex.query.filter(and_(
                    Ex.is_official == true(),
                    Ex.title.ilike(like_str)
                )).order_by(Ex.id.asc()).limit(page_count).offset(offset).all()

        result = {
            'exs': [get_brief_card(ExCache(ex.id), gender) for ex in exs],
            'page': page
        }
        return jsonify(result)

    return jsonify(msg='参数不对'), HTTPStatus.BAD_REQUEST


def some_day_ago(now, diary_date):
    delta = now.date() - diary_date.date()
    if delta.days == 0:
        time_str = '今天'
    elif delta.days == 1:
        time_str = '昨天'
    elif delta.days == 2:
        time_str = '前天'
    else:
        time_str = '{}天前'.format(delta.days)
    return time_str


@blueprint.route('/<string:ex_hid>', methods=['GET'])
@customer_id_require()
def get_ex(ex_hid):
    customer_id = g.customer_id
    gender = CustomerCache(customer_id).get('gender')

    title = request.args.get('title', default=None, type=str)
    _MAX_HIS_COUNT = 20     # 最多显示多少条历史记录
    now = datetime.now()
    if ex_hid == DUMMY_ID:
        if not title:
            return jsonify(msg='该动作不存在'), HTTPStatus.NOT_FOUND
        res = {
            'id': DUMMY_ID,
            'title': title,
        }
        his: List[ExHistory] = ExHistory.query.filter(
            ExHistory.customer_id == customer_id,
            ExHistory.ex_id == int(DUMMY_ID),
            ExHistory.ex_title == title
        ).order_by(desc(ExHistory.recorded_at)).limit(_MAX_HIS_COUNT).all()

        dis_his = [{
            'sets': ex_h.sets,
            'note': ex_h.note,
            'date': ex_h.diary_date.strftime('%Y年%m月%d日'),
            'date_desc': some_day_ago(now, ex_h.diary_date)} for ex_h in his]
        res.update({'history': dis_his})
    else:
        ex: Ex = Ex.find(ex_hid)
        if not ex:
            return jsonify(msg='该动作不存在'), HTTPStatus.NOT_FOUND
        if gender == Gender.FEMALE:
            illustration = cfg['aliyun_oss']['cdn_host'] + '/' + \
                           cfg['aliyun_oss']['ex_path'].format(file_name=ex.pictures['F'])
        else:
            illustration = cfg['aliyun_oss']['cdn_host'] + '/' + \
                           cfg['aliyun_oss']['ex_path'].format(file_name=ex.pictures['M'])
        res = {
            'id': ex_hid,
            'title': ex.title,
            'title_en': ex.full_name,
            'illustration': illustration,
            'desc': ex.describe,
            'primary_mg': ex.primary_mg,
            'secondary_mg': ex.secondary_mg
        }
        his = ExHistory.query.filter(
            ExHistory.customer_id == customer_id,
            ExHistory.ex_id == ex.id
        ).order_by(desc(ExHistory.recorded_at)).limit(_MAX_HIS_COUNT).all()
        dis_his = [{
            'sets': ex_h.sets,
            'note': ex_h.note,
            'date': ex_h.diary_date.strftime('%Y年%m月%d日'),
            'date_desc': some_day_ago(now, ex_h.diary_date)} for ex_h in his]
        res.update({'history': dis_his})
    return jsonify({
        'ex': res
    })


@blueprint.route('/admin', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def admin_post_ex():
    ex_data = request.get_json()
    if not ex_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    if ex_data.get('record_method') not in ['weight*reps', 'reps', 'time', 'distance']:
        return jsonify(msg='Unknown record method'), HTTPStatus.BAD_REQUEST

    ex_id = ex_data['id']
    now = datetime.now()

    title = ex_data['title']
    same_name = Ex.query.filter(
        Ex.is_official == true(),
        Ex.id != ex_id,
        Ex.title == title).first()
    if same_name:
        return jsonify(msg='已经有相同名称的动作了. 请改个新的名称.'), HTTPStatus.BAD_REQUEST

    ex: Ex = Ex.query.filter(Ex.id == ex_id).first()
    if not ex:
        ex = Ex(
            id=ex_id,
            is_official=True,
            created_at=now
        )
        db.session.add(ex)

    ex.name_en = ex_data.get('name_en')
    ex.full_name = ex_data.get('full_name')

    ex.title = ex_data.get('title')
    ex.subtitle = ex_data.get('subtitle')
    ex.record_method = ex_data.get('record_method')
    ex.pictures = ex_data.get('pictures')
    ex.describe = ex_data.get('describe')
    ex.primary_mg = ex_data.get('primary_mg')
    ex.secondary_mg = ex_data.get('secondary_mg')
    ex.modified_at = now

    e_related = []
    r_related = []

    for e in ex_data.get('related_exs') or []:
        try:
            r_ex: Ex = Ex.query.filter(Ex.id == int(e['ex']['id'])).first()
        except TypeError:
            print('***********')
            print(ex_data)
        if r_ex:
            r_related.append({
                'ex': {
                    'id': e['ex']['id'],
                    'title': r_ex.title,
                    # 'full_name': r_ex.full_name,
                    # 'primary_mg': r_ex.primary_mg
                }
            })
            e_related.append({
                'ex': {'id': e['ex']['id']}
            })
        else:
            r_related.append({
                'ex': {
                    'id': e['ex']['id'],
                    'msg': '404'
                }
            })
    ex.related_exs = e_related

    db.session.commit()
    return jsonify(r_related)


@blueprint.route('/<string:ex_hid>/property', methods=['GET'])
@customer_id_require()
def get_ex_property(ex_hid):
    customer_id = g.customer_id
    gender = CustomerCache(customer_id).get('gender')

    ex_title = request.args.get('title', default=None, type=str)

    default_method = {
        'record_method': 'weight*reps',
        'unit': 'kg'
    }
    if ex_hid == DUMMY_ID:
        if not ex_title:
            return jsonify(msg='该动作不存在'), HTTPStatus.NOT_FOUND
        ex_property: ExProperty = ExProperty.query.filter(
            ExProperty.customer_id == customer_id,
            ExProperty.ex_id == int(DUMMY_ID),
            ExProperty.ex_title == ex_title
        ).first()
        p_dict = {
            'id': DUMMY_ID,
            'title': ex_title
        }
        if not ex_property:
            p_dict.update(default_method)
        else:
            p_dict.update({
                'record_method': ex_property.record_method,
                'unit': ex_property.unit if ex_property.unit else ''
            })
    else:
        ex: Ex = Ex.find(ex_hid)
        if not ex:
            return jsonify(msg='该动作不存在'), HTTPStatus.NOT_FOUND
        ex_property: ExProperty = ExProperty.query.filter(
            ExProperty.customer_id == customer_id,
            ExProperty.ex_id == ex.id
        ).first()

        p_dict = {
            'id': ex_hid,
            'title': ex.title,
            'illustration': get_illustration(ex, gender)
        }

        if not ex_property:
            if ex.record_method == 'weight*reps':
                p_dict.update({
                    'record_method': ex.record_method,
                    'unit': 'kg'
                })
            elif ex.record_method == 'reps':
                p_dict.update({
                    'record_method': ex.record_method,
                    'unit': ''
                })
            elif ex.record_method == 'time':
                p_dict.update({
                    'record_method': ex.record_method,
                    'unit': '秒'
                })
            else:
                p_dict.update(default_method)
        else:
            p_dict.update({
                'record_method': ex_property.record_method,
                'unit': ex_property.unit if ex_property.unit else ''
            })
    return jsonify(p_dict)


@blueprint.route('/<string:ex_hid>/property', methods=['PUT'])
@customer_id_require()
def put_ex_property(ex_hid):
    customer_id = g.customer_id
    gender = CustomerCache(customer_id).get('gender')

    ex_title = request.args.get('title', default=None, type=str)
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    record_method = json_data.get('record_method')
    if record_method not in ['weight*reps', 'reps', 'time']:
        return jsonify(msg='Unknown record method'), HTTPStatus.BAD_REQUEST

    unit = json_data.get('unit')

    now = datetime.now()
    if ex_hid == DUMMY_ID:
        if not ex_title:
            return jsonify(msg='该动作不存在'), HTTPStatus.NOT_FOUND
        ex_title = ex_title.strip()
        if not ex_title:
            return jsonify(msg='请输入动作名称'), HTTPStatus.NOT_FOUND
        ex_property: ExProperty = ExProperty.query.filter(
            ExProperty.customer_id == customer_id,
            ExProperty.ex_id == int(DUMMY_ID),
            ExProperty.ex_title == ex_title
        ).first()
        if not ex_property:
            ex_property = ExProperty(
                customer_id=customer_id,
                ex_id=DUMMY_ID,
                ex_title=ex_title,
                last_recorded_at=now,
                created_at=now,
            )
            db.session.add(ex_property)
        p_dict = {
            'id': DUMMY_ID,
            'title': ex_title
        }
    else:
        ex: Ex = Ex.find(ex_hid)
        if not ex:
            return jsonify(msg='该动作不存在'), HTTPStatus.NOT_FOUND
        ex_property: ExProperty = ExProperty.query.filter(
            ExProperty.customer_id == customer_id,
            ExProperty.ex_id == ex.id
        ).first()
        if not ex_property:
            ex_property = ExProperty(
                customer_id=customer_id,
                ex_id=ex.id,
                last_recorded_at=now,
                created_at=now
            )
            db.session.add(ex_property)
        p_dict = {
            'id': ex_hid,
            'title': ex.title,
            'illustration': get_illustration(ex, gender)
        }
    if record_method:
        ex_property.record_method = record_method
        ex_property.unit = unit

    db.session.commit()
    p_dict.update({
        'record_method': record_method,
        'unit': unit
    })

    return jsonify(p_dict)
