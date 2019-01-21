from typing import List

from flask import Blueprint
from flask import jsonify, request, g
from http import HTTPStatus
from sqlalchemy import and_, func, asc, true
from sqlalchemy.sql.expression import desc, null

from store.database import db
from store.diaries.utils import get_nearest_seat_tip
from store.domain.middle import roles_required, permission_required, hide_index_video
from datetime import datetime
from store.domain.permission import ViewBizPermission, EditStorePermission, ViewBizWebPermission
from store.domain.role import AdminRole, UNDEFINED_BIZ_ID, CustomerRole
from store.domain.models import Store, ReserveEmail, Video, CheckIn, Diary, Seat, SeatStatus, Course, SeatPriority
from store.domain.cache import StoreBizCache, AppCache, CustomerCache, DiaryUnreadCache, CheckInCache, CoachCache, \
    SeatCheckCache
import copy

from store.domain.seat_code import generate_seat_code
from store.utils.helper import move
from store.utils import time_processing as tp
from store.utils.time_formatter import get_yymmdd
from store.videos.utils import check_video_info

blueprint = Blueprint('_store', __name__)


@blueprint.route('/health', methods=['GET'])
def health():
    return jsonify(msg='Hello 11train!')


@blueprint.route('/admin', methods=['POST'])
@roles_required(AdminRole(UNDEFINED_BIZ_ID))
def admin_store():
    sz_data = request.get_json()
    if not sz_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    biz_id = sz_data['biz_id']

    admin_id = g.get('admin_id')
    if not admin_id:
        return jsonify(), HTTPStatus.UNAUTHORIZED

    # sz: StoreBiz = StoreBiz.query.filter(and_(
    #     StoreBiz.id == sz_id
    # )).first()
    #
    now = datetime.now()
    #
    # if not sz:
    #     sz = StoreBiz(
    #         id=sz_id,
    #         created_at=now
    #     )
    #     db.session.add(sz)
    #     db.session.flush()
    #     db.session.refresh(sz)

    # sz.app_id = sz_data.get('app_id')
    # sz.modified_at = now

    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()

    if not store:
        store = Store(
            biz_id=biz_id,
            created_at=now
        )
        db.session.add(store)

    store.cards = sz_data['store']['cards']
    store.contact = sz_data['store']['contact']
    store.coach_indexes = sz_data['coach_indexes']
    store.course_indexes = sz_data['course_indexes']
    store.modified_at = now

    db.session.commit()

    biz_cache = StoreBizCache(biz_id)
    biz_cache.reload()

    return jsonify()


@blueprint.route('', methods=['GET'])
@permission_required(ViewBizPermission())
def get_store():
    biz_id = g.get('biz_id')
    biz_cache = StoreBizCache(biz_id)
    return jsonify({
        'store': biz_cache.get('store')
    })


@blueprint.route('/contact', methods=['GET'])
@permission_required(ViewBizPermission())
def get_contact():
    biz_id = g.get('biz_id')
    biz_cache = StoreBizCache(biz_id)
    return jsonify({
        'contact': biz_cache.get('contact')
    })


@blueprint.route('/cards', methods=['GET'])
@permission_required(ViewBizPermission())
def get_cards():
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()
    return jsonify({
        'cards': store.get_raw_cards()
    })


@blueprint.route('/cards', methods=['POST'])
@permission_required(EditStorePermission())
def post_cards():
    c_data = request.get_json()
    if not c_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()
    cards = copy.deepcopy(store.cards)

    c_ids = [c['id'] for c in cards]
    new_c_id = max(c_ids) + 1 if c_ids else 1

    now = datetime.now()
    last_index = len(cards)
    index = c_data.get('index') or last_index
    c_data.pop('index', None)
    c_data.update({'id': new_c_id})
    cards.insert(
        index, c_data
    )
    store.cards = cards
    store.modified_at = now
    db.session.commit()

    biz_cache = StoreBizCache(biz_id)
    biz_cache.reload()

    return jsonify({
        'cards': cards
    })


@blueprint.route('/cards/<int:c_id>', methods=['GET'])
@permission_required(ViewBizPermission())
def get_card(c_id):
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()
    if not store:
        return jsonify(), HTTPStatus.NOT_FOUND

    cards = copy.deepcopy(store.cards)
    card, card_index = Store.find_card(cards, c_id)
    if not card:
        return jsonify(msg='卡片不存在'), HTTPStatus.NOT_FOUND

    return jsonify({
        'card': card
    })


@blueprint.route('/cards/<int:c_id>', methods=['PUT'])
@permission_required(EditStorePermission())
def put_card(c_id):
    c_data = request.get_json()
    if not c_data:
        return jsonify(msg='No input data provided'), HTTPStatus.BAD_REQUEST

    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()
    if not store:
        return jsonify(), HTTPStatus.NOT_FOUND

    cards = copy.deepcopy(store.cards)
    card, card_index = Store.find_card(cards, c_id)
    if not card:
        return jsonify(msg='卡片不存在'), HTTPStatus.NOT_FOUND

    now = datetime.now()

    card.update(c_data)
    store.cards = cards
    store.modified_at = now
    db.session.commit()

    # card, card_index = Store.find_card(cards, c_id)
    # card.update({
    #     'index': card_index
    # })
    biz_cache = StoreBizCache(biz_id)
    biz_cache.reload()

    return jsonify({
        'card': card
    })


@blueprint.route('/cards/<int:c_id>/index/<int:n_index>', methods=['POST'])
@permission_required(EditStorePermission())
def post_card_index(c_id, n_index):
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()
    if not store:
        return jsonify(), HTTPStatus.NOT_FOUND

    cards = copy.deepcopy(store.cards)
    card, card_index = Store.find_card(cards, c_id)
    if not card:
        return jsonify(msg='卡片不存在'), HTTPStatus.NOT_FOUND

    if n_index < 0 or n_index >= len(cards):
        return jsonify(msg='invalid index range'), HTTPStatus.BAD_REQUEST

    now = datetime.now()

    cards = move(cards, card_index, n_index)

    store.cards = cards
    store.modified_at = now
    db.session.commit()

    biz_cache = StoreBizCache(biz_id)
    biz_cache.reload()

    return jsonify({
        'cards': cards
    })


@blueprint.route('/cards/<int:c_id>', methods=['DELETE'])
@permission_required(EditStorePermission())
def delete_card(c_id):
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()
    if not store:
        return jsonify(), HTTPStatus.NOT_FOUND

    cards = copy.deepcopy(store.cards)
    card, card_index = Store.find_card(cards, c_id)
    if not card:
        return jsonify(msg='卡片不存在'), HTTPStatus.NOT_FOUND

    del cards[card_index]

    now = datetime.now()
    store.cards = cards
    store.modified_at = now
    db.session.commit()

    biz_cache = StoreBizCache(biz_id)
    biz_cache.reload()
    return jsonify({
        'cards': cards
    })


@blueprint.route('/emails', methods=['GET'])
@permission_required(ViewBizWebPermission())
def get_emails():
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()
    if not store:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND

    return jsonify({
        'emails': store.emails if store.emails else []
    })


@blueprint.route('/emails', methods=['PUT'])
@permission_required(EditStorePermission())
def put_emails():
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()
    if not store:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND

    new_emails = request.get_json()
    if not new_emails:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    store.emails = new_emails
    db.session.commit()
    db.session.refresh(store)

    return jsonify({
        'emails': store.emails
    })


@blueprint.route('/reservation_emails', methods=['GET'])
@permission_required(ViewBizWebPermission())
def get_reservation_emails():
    biz_id = g.get('biz_id')
    page = request.args.get('page', default=1, type=int)
    emails: ReserveEmail = ReserveEmail.query.filter(
        ReserveEmail.biz_id == biz_id
    ).order_by(
        desc(ReserveEmail.exp_date), desc(ReserveEmail.exp_time)
    ).paginate(page=page, per_page=10, error_out=False)

    if page == 1 and emails.items == []:
        return jsonify({
            'emails': [],
            'page_count': emails.pages,  # 总页数
        })

    res = [e.get_brief() for e in emails.items]
    return jsonify({
        'emails': res,
        'page_count': emails.pages,  # 总页数
    })


@blueprint.route('/update/company_profile', methods=['PUT'])
@permission_required(EditStorePermission())
def put_company_profile():
    """ 此接口只用于将场地介绍更新为公司简介 """
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(and_(
        Store.biz_id == biz_id
    )).first()
    cards = store.get_raw_cards()
    new_cards = copy.deepcopy(cards)
    for c in new_cards:
        if 'title' in c.keys():
            if c.get('title') == '场地介绍':
                c['title'] = '公司简介'
    store.cards = new_cards
    db.session.commit()
    db.session.refresh(store)
    return jsonify({
        'cards': store.get_raw_cards()
    })


@blueprint.route('/index_video', methods=['PUT'])
@permission_required(EditStorePermission())
def put_index_video():
    biz_id = g.get('biz_id')
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST

    video_data = json_data.get('video')
    file_id = video_data.get('fileId')
    video: Video = Video.find(file_id)
    if not video:
        return jsonify(msg='视频尚未上传完毕'), HTTPStatus.BAD_REQUEST

    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    if not store:
        return jsonify(msg='店家不存在'), HTTPStatus.NOT_FOUND

    store.video_fileid = file_id
    db.session.commit()
    return jsonify(msg='发布成功')


@blueprint.route('/index_video', methods=['GET'])
@roles_required()
@hide_index_video()
def get_store_video():
    biz_id = g.get('biz_id')
    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    if not store:
        return jsonify(msg='店家不存在'), HTTPStatus.NOT_FOUND
    store_cache = StoreBizCache(biz_id)
    customer_app_id = store_cache.get('customer_app_id')
    app_cache = AppCache(customer_app_id)
    store_name = app_cache.get('nick_name')

    if not store.video_fileid:
        return jsonify({
            'video': {}
        })
    video: Video = Video.find(store.video_fileid)
    if not video:
        return jsonify({
            'video': {}
        })
    video = check_video_info(video)  # 校验首页视频封面
    return jsonify({
        'video': video.get_brief(),
        'store_name': store_name
    })


@blueprint.route('/personal_card', methods=['GET'])
@roles_required(CustomerRole())
def get_personal_card():
    """ 首页获取个人卡片 """
    biz_id = g.get('biz_id')
    app_id = g.get('app_id')
    c_id = CustomerRole(biz_id).get_id(g.role)

    app_cache = AppCache(app_id)
    app_img = app_cache.get('head_img')
    tips = get_diary_tips(c_id)
    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    slogan = store.get_slogan()

    today_min = tp.get_day_min(datetime.today())
    today_max = tp.get_day_max(datetime.today())
    # 查询是否打卡
    check_in: CheckIn = CheckIn.query.filter(
        CheckIn.biz_id == biz_id,
        CheckIn.customer_id == c_id,
        CheckIn.created_at >= today_min,
        CheckIn.created_at <= today_max
    ).first()

    avatar = CustomerCache(c_id).get('avatar')
    check_in_cache = CheckInCache(biz_id)
    customers = check_in_cache.get_customer_briefs(customer_id=c_id)
    # +1是因为在列表中已经把自己剔除了
    if len(customers) + 1 < 5:
        # 当前健身人数少于5人时，显示本月排行榜
        early_month = tp.get_early_month(datetime.today())
        end_month = tp.get_end_month(datetime.today())

        check_ins = db.session.query(
            CheckIn.customer_id, func.count(CheckIn.check_in_date)
        ).filter(
            CheckIn.check_in_date >= early_month,
            CheckIn.check_in_date <= end_month,
            CheckIn.biz_id == biz_id
        ).order_by(
            desc(func.count(CheckIn.check_in_date)), asc(func.max(CheckIn.check_in_date))
        ).group_by(CheckIn.customer_id).all()

        customers = [{
            'avatar': CustomerCache(c[0]).get('avatar'),
            'nick_name': CustomerCache(c[0]).get('nick_name')
        } for c in check_ins[:3]] if check_ins else []
    check_in_count = db.session.query(func.count(CheckIn.customer_id)).filter(
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= today_min,
        CheckIn.check_in_date <= today_max
    ).scalar()
    return jsonify({
        'avatar': avatar,
        'tips': tips,
        'slogan': slogan,
        'app_img': app_img,
        'customers': customers[:7],
        'check_in_id': check_in.get_hash_id() if check_in else None,
        'check_in_count': check_in_count
    })


@blueprint.route('/seat/brief', methods=['GET'])
@roles_required(CustomerRole())
def get_seat_brief():
    """ 客户端首页获取课程信息 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)

    yymmdd = get_yymmdd(datetime.now())
    # 已上的课程(私教课)
    seat: Seat = Seat.query.filter(
        Seat.is_valid == true(),
        Seat.customer_id == c_id,
        Seat.status == SeatStatus.ATTENDED.value,
        Seat.yymmdd == yymmdd,
        Seat.priority == SeatPriority.PRIVATE.value,
        Seat.is_check != true()  # 未核销的
    ).order_by(asc(Seat.start)).first()
    if not seat:
        return jsonify({
            "seat_brief": None
        })

    check_cache = SeatCheckCache(seat.id)
    code = check_cache.get('code')
    c_cache = CoachCache(seat.coach_id)
    c_brief = c_cache.get('brief')
    course_img = ''
    seat_brief = {
        "id": seat.get_hash_id(),
        "time": "{start_time}-{end_time}".format(
            start_time=seat.start_time.strftime("%H:%M"), end_time=seat.end_time.strftime("%H:%M")
        ),
        "coach": c_brief.get('name'),
        "name": '',
        "course_img": course_img,
        "code": code
    }
    if seat.course_id:
        course: Course = Course.query.filter(
            Course.id == seat.course_id
        ).first()
        if course:
            seat_brief.update({
                "course_img": course.images[0],
                "name": course.title
            })

    return jsonify({
        "seat_brief": seat_brief
    })


@blueprint.route('/seat/<string:s_id>/code', methods=['GET'])
@roles_required(CustomerRole())
def get_seat_code(s_id):
    """ 客户确认上课, 获取课程码 """
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)

    seat: Seat = Seat.find(s_id)
    if not seat:
        return jsonify(msg='课程不存在'), HTTPStatus.NOT_FOUND
    if seat.customer_id != c_id:
        return jsonify(msg='非法操作'), HTTPStatus.BAD_REQUEST
    if seat.is_check:
        return jsonify(msg='该课程已被核销'), HTTPStatus.BAD_REQUEST
    if seat.priority != SeatPriority.PRIVATE.value:
        return jsonify(msg='非私教课无需核销'), HTTPStatus.BAD_REQUEST
    course_id = seat.course_id
    if not course_id:
        return jsonify(msg='请联系教练设置课时类型'), HTTPStatus.BAD_REQUEST

    code = generate_seat_code(seat)
    return jsonify({
        "code": code
    })


def get_diary_tips(c_id):
    today_min = tp.get_day_min(datetime.today())
    today_max = tp.get_day_max(datetime.today())
    last_week = tp.get_last_n_day(today_min, 7)
    tips = []
    # 一周内打卡次数
    recent = db.session.query(func.count(CheckIn.id)).filter(
        CheckIn.customer_id == c_id,
        CheckIn.check_in_date >= last_week,
        CheckIn.check_in_date <= today_max
    ).scalar()
    if recent == 0:
        recent_str = '🏥 你不健身的借口是什么？\n🤒规律的健身让你远离亚健康'
    elif recent == 1:
        recent_str = '💪 每一天向好身材更进一步！'
    elif recent == 2:
        recent_str = '🏅  一周两练，你已经超越了大多数人。'
    else:
        recent_str = '🏋 继续坚持，良好的健身习惯是完美身材的保证'

    tips.append(recent_str)

    diary_unread_cache = DiaryUnreadCache(c_id)
    images_unread = diary_unread_cache.get_unread('images')
    note_unread = diary_unread_cache.get_unread('note')
    training_unread = diary_unread_cache.get_unread('training')
    plan_unread = diary_unread_cache.get_unread('plan')
    mg_unread = diary_unread_cache.get_unread('mg')
    record_unread = diary_unread_cache.get_unread('record')

    if training_unread.get('unread'):
        tips.append(training_unread.get('tip'))

    if mg_unread.get('unread'):
        tips.append(mg_unread.get('tip'))

    if plan_unread.get('unread'):
        tips.append(plan_unread.get('tip'))

    if record_unread.get('unread'):
        tips.append(record_unread.get('tip'))

    if images_unread.get('unread'):
        tips.append(images_unread.get('tip'))

    if note_unread.get('unread'):
        diary: Diary = Diary.query.filter(
            Diary.customer_id == c_id,
            Diary.recorded_at == today_min
        ).first()
        if diary and diary.coach_note:
            for coach_note in diary.coach_note:
                c_cache = CoachCache(coach_note.get('coach_id'))
                brief = c_cache.get('brief')
                n_str = '💬 {coach_name}教练说：{coach_note}'.format(coach_name=brief.get('name'), coach_note=coach_note.get('note'))
                tips.append(n_str)

    seat_tip = get_nearest_seat_tip(today_min, c_id)
    if seat_tip:
        tips.append(seat_tip)
    return tips
