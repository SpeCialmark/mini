import json
import math
import random
import sys
from http import HTTPStatus
from typing import List
import requests
from flask import Blueprint, g, jsonify, request
from sqlalchemy import and_, func, asc, desc
from store.admin_panel.apis import get_checked_dict
from store.cache import lock_redis_store
from store.database import db
from store.domain.cache import AppCache, CheckInCache, CustomerCache, AppAuditCache
from store.domain.wxapp import ReleaseQrcode
from store.domain.middle import roles_required, permission_required
from store.domain.permission import ViewBizPermission
from store.domain.role import CustomerRole
from store.domain.models import CheckIn, Customer, Store, Qrcode, StoreBiz
import datetime
from store.utils.image import get_random_excitation, get_random_high_img, get_random_width_img
from PIL import Image, ImageDraw, ImageFont
from store.utils.oss import bucket
import io
import tempfile
from store.config import cfg, _env
from store.utils import time_processing as tp
import redis_lock

blueprint = Blueprint('_check_in', __name__)
gd_map_accessKey = '2cf77237ab1e722a93335c56571f9f7d'


@blueprint.route('/fitness', methods=['GET'])
@roles_required(CustomerRole())
def get_fitness():
    biz_id = g.get('biz_id')
    check_in_cache = CheckInCache(biz_id)
    cache_date = datetime.datetime.strptime(check_in_cache.get('date'), '%Y.%m.%d %H:%M:%S')
    now = datetime.datetime.now()
    today_min = tp.get_day_min(now)

    if cache_date != today_min:
        CheckInCache(biz_id).reload()

    briefs = check_in_cache.get('briefs')
    random_briefs = []
    if len(briefs) > 8:
        # 如果打卡人数超过8人
        # 随机显示8个
        while len(random_briefs) < 8:
            random_brief = random.choice(briefs)
            if random_brief not in random_briefs:
                random_briefs.append(random_brief)
    else:
        random_briefs = briefs

    res = []
    for brief in random_briefs:
        customer_id = brief.get('customer_id')
        check_in_time = datetime.datetime.strptime(brief.get('check_in_time'), '%Y.%m.%d %H:%M:%S')
        c_cache = CustomerCache(customer_id)
        avatar = c_cache.get('avatar')
        nick_name = c_cache.get('nick_name')
        train_time = (now - check_in_time).total_seconds()
        check_in_count = db.session.query(func.count(CheckIn.id)).filter(
            CheckIn.customer_id == customer_id
        ).scalar()
        if 3600 > train_time:
            mm = math.ceil(train_time / 60)
            train_time_str = "{mm}分钟前开始健身".format(mm=mm)
            res.append({
                'avatar': avatar,
                'nick_name': nick_name,
                'train_time_str': train_time_str,
                'check_in_count': check_in_count,
                'train_time': train_time  # 排序用
            })
        elif train_time >= 3600:
            hh = int(train_time / 3600)
            mm = int((train_time - hh*3600)/60)
            train_time_str = "{hh}小时{mm}分钟前开始健身".format(hh=hh, mm=mm)
            res.append({
                'avatar': avatar,
                'nick_name': nick_name,
                'train_time_str': train_time_str,
                'check_in_count': check_in_count,
                'train_time': train_time  # 排序用
            })
    res.sort(key=lambda x: (x['train_time']))
    return jsonify({
        'fitness': res
    })


@blueprint.route('/excitation', methods=['GET'])
def get_excitation():
    i_type = request.args.get('type', default='high', type=str)
    if i_type == 'width':
        # 宽图
        image = get_random_width_img()
    else:
        # 长图
        image = get_random_high_img()
    words = get_random_excitation()
    return jsonify({
        'excitation': {
            'words': words,
            'image': image
        }
    })


@blueprint.route('/records', methods=['POST'])
@permission_required(ViewBizPermission())
@roles_required(CustomerRole())
def post_records():
    """ 根据地理位置打卡 """
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    now = datetime.datetime.now()

    record_util = RecordUtil(biz_id=biz_id, c_id=customer_id)
    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    if not store:
        return jsonify(msg='门店不存在'), HTTPStatus.NOT_FOUND
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    locations = json_data.get('locations')  # type: List
    if not all([locations]):
        return jsonify(msg='获取地理位置失败'), HTTPStatus.BAD_REQUEST
    # 获取商家的地理位置(经纬度)
    # latitude: 纬度, longitude: 经度
    to_latitude, to_longitude = store.get_position()

    origins = ""
    accuracies = []
    for index, l in enumerate(locations):
        # 前端进过筛选后同时发送多个坐标点到后台
        from_latitude = l.get('latitude')
        from_longitude = l.get('longitude')
        accuracy = l.get('accuracy')
        accuracies.append(accuracy)
        if index != 0:
            origins += '|{f_longitude},{f_latitude}'.format(f_longitude=from_longitude, f_latitude=from_latitude)
        else:
            origins += '{f_longitude},{f_latitude}'.format(f_longitude=from_longitude, f_latitude=from_latitude)

    gd_d_url = """https://restapi.amap.com/v3/distance?key={key}&origins={origins}&destination={t_longitude},{t_latitude}&output=json&type=0""".format(
        origins=origins, t_longitude=to_longitude, t_latitude=to_latitude,
        key=gd_map_accessKey
    )
    gd_r = requests.get(gd_d_url)
    gd_response_data = json.loads(gd_r.content)
    if not gd_response_data:
        return jsonify(msg='too fast'), HTTPStatus.BAD_REQUEST

    response = gd_response_data.get('results')
    distances = [int(res.get('distance')) for res in response]
    min_distance = min(distances)
    if min_distance > 300:
        return jsonify(), HTTPStatus.BAD_REQUEST

    # 打卡并返回打卡结果
    is_checked, check_in_hid = record_util.post_check_in()

    # 获取今日最开始的时间
    today = tp.get_day_min(now)
    tomorrow = tp.get_next_day(today)

    # 总打卡
    record = record_util.get_sum_record()

    # 月打卡
    month_sum = record_util.get_month_sum(today)

    # 最近打卡
    recent = record_util.get_recent()

    # 今日排名
    rank = record_util.get_rank(today=today, tomorrow=tomorrow)

    check_in_data = {
        "sum": record,
        "month_sum": month_sum,
        "recent_situation": recent,
        "today": today.strftime("%Y.%m.%d"),
        "check_in_id": check_in_hid,
        "is_checked": is_checked,
        "rank": rank
    }
    check_in_cache = CheckInCache(biz_id)
    check_in_cache.reload()
    return jsonify(check_in_data)


@blueprint.route('/records/year/<int:year>/month/<int:month>', methods=['GET'])
@permission_required(ViewBizPermission())
@roles_required(CustomerRole())
def get_records(month, year):
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    record_util = RecordUtil(biz_id=biz_id, c_id=customer_id)

    day_min = tp.get_day_min(datetime.datetime.now())

    today = datetime.datetime(year=year, month=month, day=1)
    # 获取当月天数
    days_of_month = tp.get_day_of_month(today)  # (4, 30)
    # 遍历打卡历史
    # 日历数据
    month_record = record_util.get_month_record(today=today, days_of_month=days_of_month)
    # 每月打卡次数
    month_sum = record_util.get_month_sum(today=today)
    # 总打卡次数
    record_sum = record_util.get_sum_record()

    check_in: CheckIn = CheckIn.query.filter(and_(
        CheckIn.check_in_date >= day_min,
        CheckIn.customer_id == customer_id,
        CheckIn.biz_id == biz_id,
    )).first()
    if check_in:
        check_time = check_in.check_in_date.strftime("%H:%M")
    else:
        check_time = False

    return jsonify({
        "check_time": check_time,
        "month_sum": month_sum,
        "month_record": month_record,
        "sum": record_sum,
    })


@blueprint.route('/records/<string:h_id>', methods=['GET'])
@permission_required(ViewBizPermission())
@roles_required(CustomerRole())
def get_check_in(h_id):
    biz_id = g.get('biz_id')

    check_in = CheckIn.find(h_id)
    if not check_in:
        return jsonify(msg='打卡信息不存在'), HTTPStatus.NOT_FOUND
    # end_date = tp.get_day_max(datetime.datetime.today())
    # start_date = tp.get_day_min(end_date - datetime.timedelta(days=15))

    checkin_cid = check_in.customer_id
    record_util = RecordUtil(biz_id=biz_id, c_id=checkin_cid)
    customer: Customer = Customer.query.filter(Customer.id == checkin_cid).first()
    # bfp = BodyData.get_last_record(customer.id, BFP.name)
    # 总打卡
    sum_record = record_util.get_sum_record()
    # 月打卡
    month_sum = record_util.get_month_sum(today=check_in.check_in_date)
    health_record = {
        'gender': customer.gender,
        'step': customer.step_count[-1].get('step') if customer.step_count else 0,
        # 'weight_change': '%.1f' % BodyData.get_record_change(customer.id, start_date, end_date, Weight.name),
        # 'bfp': bfp or 0
    }

    checked = {
        'sum': sum_record,
        'month_sum': month_sum,
        'today': check_in.check_in_date.strftime("%Y.%m.%d"),
        'image': check_in.image or get_random_high_img()
    }

    user_info = {
        'avatarUrl': customer.avatar,
        'nickName': customer.nick_name
    }
    return jsonify({
        'checked': checked,
        'userInfo': user_info,
        'health_record': health_record,
        'is_auditing': AppAuditCache(biz_id=biz_id).is_auditing(request.headers)  # 审核开关,用于隐藏上传按钮
    })


@blueprint.route('/records/<string:h_id>/images', methods=['POST'])
@permission_required(ViewBizPermission())
@roles_required(CustomerRole())
def post_share_image(h_id: str):
    biz_id = g.get('biz_id')
    app_id = g.get('app_id')
    date = request.get_json()
    if not date:
        return jsonify(msg='获取数据失败'), HTTPStatus.BAD_REQUEST

    image_url = date['image_url']
    words = date['words']
    check_in: CheckIn = CheckIn.find(h_id)
    customer: Customer = Customer.query.filter(Customer.id == check_in.customer_id).first()

    if not check_in:
        return jsonify(msg='获取签到数据失败'), HTTPStatus.NOT_FOUND

    store: Store = Store.query.filter(
        Store.biz_id == biz_id
    ).first()
    biz_hid = StoreBiz.hash_ids.encode(biz_id)
    app_cache = AppCache(app_id=app_id)

    qrcode: Qrcode = ReleaseQrcode(app_id=app_id).get()
    qr_code_url = qrcode.get_brief()['url']
    avatar_url = customer.avatar
    name = customer.get_hash_id()
    address = store.get_address()
    store_name = app_cache.get('nick_name')

    record_util = RecordUtil(biz_id=biz_id, c_id=check_in.customer_id)
    generate_pic = GeneratePic(photo=image_url, words=words, record_util=record_util, check_in=check_in)
    # 拼接图片
    back_ground = generate_pic.create_pic(avatar_url=avatar_url, qr_code_url=qr_code_url)
    # 绘制文字
    share_pic = generate_pic.draw_words(back_ground=back_ground, address=address, store_name=store_name)
    # 将数据保存到临时文件
    tmp = save_jpg_temp_file(share_pic)
    # 上传到oss
    image_url = upload_img(tmp, biz_hid, name)

    return jsonify({
        'image_url': image_url,
    })


@blueprint.route('/ranking', methods=['GET'])
@permission_required(ViewBizPermission())
@roles_required(CustomerRole())
def get_check_profile():
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    today = datetime.datetime.date(datetime.datetime.today())

    today_min = tp.get_day_min(today)
    today_max = tp.get_day_max(today)

    # 获取当前周日
    sunday = tp.get_sunday(today)  # 6.13周三-->sunday = 6.10
    saturday = tp.get_saturday(today)  # saturday = 6.16
    saturday_max = tp.get_day_max(saturday)

    # 获取当前月初和月末
    # 月初
    early_month = tp.get_early_month(today)
    # 月末
    end_month = tp.get_end_month(today)

    check_ins: List[CheckIn] = CheckIn.query.filter(
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= today_min,
        CheckIn.check_in_date <= today_max,
    ).order_by(asc(CheckIn.check_in_date)).all()

    day_details = []
    if check_ins:
        own_checkin: CheckIn = CheckIn.query.filter(and_(
            CheckIn.customer_id == customer_id,
            CheckIn.biz_id == biz_id,
            CheckIn.check_in_date >= today_min,
            CheckIn.check_in_date <= today_max,
        )).first()
        for check_in in check_ins:
            checked_dict = get_checked_dict(check_in)
            day_details.append(checked_dict)

        if own_checkin:
            checked_dict = get_checked_dict(own_checkin)
            checked_dict['rank'] = own_checkin.rank
        else:
            checked_dict = {"check_time": False}
        day_details.insert(0, checked_dict)  # 将用户本人放到第一条

    week_details = get_detail(start_time=sunday, end_time=saturday_max, biz_id=biz_id, customer_id=customer_id)
    month_details = get_detail(start_time=early_month, end_time=end_month, biz_id=biz_id, customer_id=customer_id)

    return jsonify({
        "day": day_details[:21],  # 只显示前20位数据, 第一条是本人
        "week": week_details[:21],
        "month": month_details[:21],
    })


@blueprint.route('/ranking_more', methods=['GET'])
@permission_required(ViewBizPermission())
@roles_required(CustomerRole())
def get_ranking_more():
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)
    today = datetime.datetime.date(datetime.datetime.today())

    today_min = tp.get_day_min(today)
    today_max = tp.get_day_max(today)

    ranking_type = request.args.get('type', RankingType.Month, type=str)  # 默认是月的排行
    page = request.args.get('page', 1, type=int)

    if ranking_type == RankingType.Day:
        check_ins: CheckIn = CheckIn.query.filter(
            CheckIn.biz_id == biz_id,
            CheckIn.check_in_date >= today_min,
            CheckIn.check_in_date <= today_max,
        ).order_by(asc(CheckIn.check_in_date)).paginate(page=page, per_page=20, error_out=False)

        day_details = []
        if check_ins.items:
            own_checkin: CheckIn = CheckIn.query.filter(and_(
                CheckIn.customer_id == customer_id,
                CheckIn.biz_id == biz_id,
                CheckIn.check_in_date >= today_min,
                CheckIn.check_in_date <= today_max,
            )).first()
            for check_in in check_ins.items:
                checked_dict = get_checked_dict(check_in)
                day_details.append(checked_dict)

            if page == 1:
                if own_checkin:
                    checked_dict = get_checked_dict(own_checkin)
                    checked_dict['rank'] = own_checkin.rank
                else:
                    checked_dict = {"check_time": False}

                day_details.insert(0, checked_dict)  # 将用户本人放到第一条
        return jsonify({'ranking': day_details,
                        'has_next': check_ins.has_next})

    elif ranking_type == RankingType.Week:
        # 获取当前周日
        sunday = tp.get_sunday(today)  # 6.13周三-->sunday = 6.10
        saturday = tp.get_saturday(today)  # saturday = 6.16
        saturday_max = tp.get_day_max(saturday)
        week_details, has_next = get_detail_more(start_time=sunday, end_time=saturday_max, biz_id=biz_id,
                                                 customer_id=customer_id,
                                                 page=page)
        return jsonify({'ranking': week_details,
                        'has_next': has_next})
    elif ranking_type == RankingType.Month:
        # 获取当前月初和月末
        # 月初
        early_month = tp.get_early_month(today)
        # 月末
        end_month = tp.get_end_month(today)
        month_details, has_next = get_detail_more(start_time=early_month, end_time=end_month, biz_id=biz_id,
                                                  customer_id=customer_id,
                                                  page=page)
        return jsonify({'ranking': month_details,
                        'has_next': has_next})
    else:
        return jsonify(msg='type error'), HTTPStatus.BAD_REQUEST


@blueprint.route('/profile', methods=['GET'])
@permission_required(ViewBizPermission())
@roles_required(CustomerRole())
def get_check_record():
    """个人中心打卡信息"""
    biz_id = g.get('biz_id')
    customer_id = CustomerRole(biz_id=biz_id).get_id(g.role)

    record_util = RecordUtil(biz_id=biz_id, c_id=customer_id)

    now = datetime.datetime.now()
    today = tp.get_day_min(now)
    today_max = tp.get_day_max(now)

    sum_record = record_util.get_sum_record()
    month_sum = record_util.get_month_sum(today)

    check_in_cache = CheckInCache(biz_id)
    briefs = check_in_cache.get('briefs')
    avatars = []
    for brief in briefs:
        check_in_customer_cache = CustomerCache(brief.get('customer_id'))
        avatars.append(check_in_customer_cache.get('avatar'))
    customer_cache = CustomerCache(customer_id)
    if customer_cache.get('avatar') in avatars:
        avatars.remove(customer_cache.get('avatar'))

    check_in_count = db.session.query(func.count(CheckIn.customer_id)).filter(
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= today,
        CheckIn.check_in_date <= today_max
    ).scalar()

    check_in: CheckIn = CheckIn.query.filter(
        CheckIn.biz_id == biz_id,
        CheckIn.customer_id == customer_id,
        CheckIn.check_in_date >= today,
        CheckIn.check_in_date <= today_max
    ).first()

    return jsonify({
        "check_in_id": check_in.get_hash_id() if check_in else None,
        "check_in_time": check_in.check_in_date.strftime("%H:%M") if check_in else None,
        "month_record": {
            "month_sum": month_sum,
            "month": today.month,
        },
        "sum": sum_record,
        "avatar": customer_cache.get('avatar'),
        'avatars': avatars[:7] if len(avatars) > 8 else avatars,  # 头像列表
        "check_in_count": check_in_count
    })


def get_detail(start_time, end_time, biz_id, customer_id):
    # 分组查询
    # 首先按照打卡次数由多到少排列, 并列的情况下按照最新打卡时间的由早到晚排列
    check_ins = db.session.query(
        CheckIn.customer_id, func.count(CheckIn.check_in_date)
    ).filter(and_(
        CheckIn.check_in_date >= start_time,
        CheckIn.check_in_date <= end_time,
        CheckIn.biz_id == biz_id
    )).order_by(
        desc(func.count(CheckIn.check_in_date)), asc(func.max(CheckIn.check_in_date))
    ).group_by(CheckIn.customer_id).all()

    own_checkin: CheckIn = CheckIn.query.filter(and_(
        CheckIn.customer_id == customer_id,
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= start_time,
        CheckIn.check_in_date <= end_time,
    )).first()

    # print(check_ins)  # [(3,3),(2,3)]
    check_in = CheckIn()  # 创建一个对象用于储存信息
    details = []
    for index, check in enumerate(check_ins):
        check_in.customer_id = check[0]
        check_in.count_num = check[1]
        checked_dict = get_checked_dict(check_in)
        details.append(checked_dict)

        if customer_id == check_in.customer_id:
            checked_dict['rank'] = index + 1
            details.insert(0, checked_dict)

    if not own_checkin:
        checked_dict = {"count": False}
        details.insert(0, checked_dict)  # 将用户本人放到第一条

    return details


def circle(ima, r3):
    # 生成圆形

    size = ima.size
    # 因为是要圆形，所以需要正方形的图片
    r2 = min(size[0], size[1])
    if size[0] != size[1]:
        ima = ima.resize((r2, r2), Image.ANTIALIAS)

    # 最后生成圆的半径
    # r3 = 80
    imb = Image.new('RGBA', (r3 * 2, r3 * 2), (255, 255, 255, 0))
    pima = ima.load()  # 像素的访问对象
    pimb = imb.load()
    r = float(r2 / 2)  # 圆心横坐标

    for i in range(r2):
        for j in range(r2):
            lx = abs(i - r)  # 到圆心距离的横坐标
            ly = abs(j - r)  # 到圆心距离的纵坐标
            l = (pow(lx, 2) + pow(ly, 2)) ** 0.5  # 三角函数 半径

            if l < r3:
                pimb[i - (r - r3), j - (r - r3)] = pima[i, j]
    # imb.save("test_circle.png")
    return imb


class GeneratePic(object):

    def __init__(self, photo, words, record_util, check_in):
        self.photo = photo
        self.words = words
        self.record_util = record_util
        self.check_in = check_in
        self.base_path = sys.path[0] + '/res/'

    def cut_pic(self, im):
        # 裁减边框
        x_size, y_size = im.size[0] - 2, im.size[1] - 2
        im = im.crop((2, 2, x_size, y_size))
        return im

    def create_pic(self, avatar_url, qr_code_url):
        # ================================打开图片文件==================================
        photo = Image.open(requests.get(self.photo, stream=True).raw).convert('RGBA')
        check = Image.open(self.base_path + 'material/check.png').convert('RGBA')
        checked = Image.open(self.base_path + 'material/checked.png').convert('RGBA')
        # ===========================打开数据库中的图片===================================
        qr_code = Image.open(requests.get(qr_code_url, stream=True).raw).convert('RGBA')
        avatar = Image.open(requests.get(avatar_url, stream=True).raw).convert('RGBA')

        if photo.size[0] > 754:
            photo.thumbnail((754, photo.size[1]), Image.ANTIALIAS)  # 按比例缩放
            self.photo = photo
        else:
            photo = photo.resize((photo.size[0] * 2, photo.size[1] * 2), Image.ANTIALIAS)
            photo.thumbnail((754, photo.size[1]), Image.ANTIALIAS)
            self.photo = photo

        back_ground = Image.new('RGBA', (750, photo.size[1] + 434), '#ffffff').convert('RGBA')  # 白底
        avatar = avatar.resize((170, 170), Image.ANTIALIAS)
        qr_code = qr_code.resize((100, 100), Image.ANTIALIAS)
        white_avatar = Image.new("RGBA", (avatar.size[0] + 10, avatar.size[1] + 10), '#ffffff')  # 头像白边
        # ================================裁减图片======================================
        avatar = self.cut_pic(avatar)
        checked = self.cut_pic(checked)
        check = self.cut_pic(check)
        qr_code = self.cut_pic(qr_code)
        avatar = circle(avatar, 80)  # 将头像裁剪为圆形
        white_avatar = circle(white_avatar, 90)
        # qr_code = circle(qr_code, 60)

        # ================================透明背景======================================
        p_a = photo.split()[3]
        a_a = avatar.split()[3]
        q_a = qr_code.split()[3]
        w_a = white_avatar.split()[3]

        back_ground.paste(photo, (0, 0), mask=p_a)
        back_ground.paste(white_avatar, (30, photo.size[1] - 68), mask=w_a)
        back_ground.paste(avatar, (40, photo.size[1] - 58), mask=a_a)
        back_ground.paste(qr_code, (90, photo.size[1] + 300), mask=q_a)

        check_x = 0
        checked_a = checked.split()[3]
        check_a = check.split()[3]
        recent = self.record_util.get_recent()
        # recent = [1, 1, 1, 1, 1, 0, 0]  # for test
        for check_in_recent in recent[::-1]:
            if check_in_recent:
                back_ground.paste(checked, (280 + check_x, photo.size[1] + 44), mask=checked_a)
            else:
                back_ground.paste(check, (280 + check_x, photo.size[1] + 44), mask=check_a)

            check_x += checked.size[0] + 6

        return back_ground

    def draw_text_border(self, font, box, words, word_draw):
        x, y = box
        word_draw.text((x + 1, y), words, font=font, fill='#696969')
        word_draw.text((x - 1, y), words, font=font, fill='#696969')
        word_draw.text((x, y + 1), words, font=font, fill='#696969')
        word_draw.text((x, y - 1), words, font=font, fill='#696969')

    def draw_words(self, back_ground, address, store_name):
        word_draw = ImageDraw.Draw(back_ground)
        day_font = ImageFont.truetype(self.base_path + 'font/arialbd.ttf', size=100)  # 大数字的大小100px
        date_font = ImageFont.truetype(self.base_path + 'font/arial.ttf', size=28)  # 小数字的大小28px
        keep_font = ImageFont.truetype(self.base_path + 'font/msyh.ttf', size=28)  # 坚持健身大小28px
        motivation_font = ImageFont.truetype(self.base_path + 'font/msyh.ttf', size=36)  # 激励语大小36px
        frequency_font = ImageFont.truetype(self.base_path + 'font/msyh.ttf', size=24)  # 打卡频率24px
        record_font = ImageFont.truetype(self.base_path + 'font/arialbd.ttf', size=56)  # 打卡次数与排名大小56px
        store_font = ImageFont.truetype(self.base_path + 'font/msyhbd.ttf', size=28)  # 地址栏大小28px

        # ==============================左上角======================================
        keep_str = '坚持健身'
        day_sum = str(self.record_util.get_sum_record())
        date_str = self.check_in.check_in_date.strftime("%Y.%m.%d")
        up_line_size = (24, 83, 168, 83)
        down_line_size = (24, 179, 168, 179)
        # day_sum = '888'  # for test
        if 34 + day_font.size * len(day_sum) / 2 > 168:  # 3位数以上
            up_line_size = (24, 83, 64 + day_font.size * len(day_sum) / 2, 83)
            down_line_size = (24, 179, 64 + day_font.size * len(day_sum) / 2, 179)

        # 位数处理
        if len(day_sum) == 1:
            self.draw_text_border(keep_font, (114, 135), '天', word_draw)
            word_draw.text((114, 135), '天', font=keep_font, fill='#ffffff')

            self.draw_text_border(day_font, (53, 79), day_sum, word_draw)
            word_draw.text((53, 79), day_sum, font=day_font, fill='#ffffff')
        else:
            word_draw.text((up_line_size[2] - 28, 135), '天', font=keep_font, fill='#ffffff')
            word_draw.text((24, 79), day_sum, font=day_font, fill='#ffffff')

        self.draw_text_border(date_font, (24, 185), date_str, word_draw)
        word_draw.text((24, 185), date_str, font=date_font, fill='#ffffff')

        self.draw_text_border(keep_font, (24, 36), keep_str, word_draw)
        word_draw.text((24, 36), keep_str, font=keep_font, fill='#ffffff')

        word_draw.line(up_line_size, fill='#ffffff', width=2)  # 第1根线
        word_draw.line(down_line_size, fill='#ffffff', width=2)  # 第2根线
        # ===============================激励语=====================================
        motivation_str = self.words
        if len(motivation_str) > 30:
            return jsonify(msg='字数超过30个')
        if len(motivation_str) > 15:
            motivation_str = motivation_str[:15] + '\n' + motivation_str[15:]
            word_draw.text((180, 779), motivation_str, font=motivation_font, fill='#ffffff')
        else:
            word_draw.text((200, 819), motivation_str, font=motivation_font, fill='#ffffff')

        # ===============================打卡频率====================================
        frequency_str = '打卡频率  (最近7天)'
        frequency_str_y = self.photo.size[1] + 74
        word_draw.text((280, frequency_str_y), frequency_str, font=frequency_font, fill='#a4a4a4')

        # ===============================打卡次数与排名===============================
        month_sum = self.record_util.get_month_sum(today=self.check_in.check_in_date)
        rank = self.check_in.rank
        month_str = '本月健身打卡'
        rank_str = '今天打卡排名'
        sum_y = self.photo.size[1] + 150  # 两个数字的位置
        str_y = self.photo.size[1] + 225  # 两组文字的位置

        # 位数处理
        # month_sum = 31  # for test
        if len(str(month_sum)) == 1:
            word_draw.text((204, sum_y), str(month_sum), font=record_font, fill='#f75900')
        elif len(str(month_sum)) == 2:
            word_draw.text((184, sum_y), str(month_sum), font=record_font, fill='#f75900')

        # 位数处理
        # rank = 888  # for test
        if len(str(rank)) == 1:
            word_draw.text((520, sum_y), str(rank), font=record_font, fill='#f75900')
        elif len(str(rank)) == 2:
            word_draw.text((500, sum_y), str(rank), font=record_font, fill='#f75900')
        else:
            word_draw.text((484, sum_y), str(rank), font=record_font, fill='#f75900')

        word_draw.text((136, str_y), month_str, font=keep_font, fill='#101010')
        word_draw.text((449, str_y), rank_str, font=keep_font, fill='#101010')

        # ===============================地址栏=====================================
        store_name_y = self.photo.size[1] + 312
        address_y = self.photo.size[1] + 352
        if len(address) > 20:
            address = address[:20] + '\n' + address[20:]

        if len(address) > 40:
            address = address[:20] + '\n' + address[21:41] + '\n' + address[41:]

        word_draw.text((259, store_name_y), store_name, font=store_font, fill='#666666')
        word_draw.text((259, address_y), address, font=frequency_font, fill='#666666')

        # =============================转换图片模式===================================
        share_pic = back_ground.convert(mode='RGB')

        return share_pic


def save_jpg_temp_file(share_pic):
    # 文件保存
    share_pic_bytes = io.BytesIO()
    share_pic.save(share_pic_bytes, format='JPEG')
    share_pic_bytes = share_pic_bytes.getvalue()
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(share_pic_bytes)
    tmp.seek(0)
    return tmp


def save_png_temp_file(share_pic):
    # 文件保存
    share_pic_bytes = io.BytesIO()
    share_pic.save(share_pic_bytes, format='PNG')
    share_pic_bytes = share_pic_bytes.getvalue()
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(share_pic_bytes)
    tmp.seek(0)
    return tmp


def upload_img(tmp, biz_hid, name):
    # 文件上传
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    file_name = 'share_pic' + name + str(now) + '.jpg'
    _dir = cfg['aliyun_oss']['user_check_in_path']
    if _env == 'dev':
        _dir = 'dev/' + _dir
    key = _dir.format(biz_hid=biz_hid, date=date_str, file_name=file_name)
    bucket.put_object_from_file(key=key, filename=tmp.name)
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    tmp.close()  # 删除临时文件
    return image_url


class RecordUtil:

    def __init__(self, biz_id, c_id):
        self.biz_id = biz_id
        self.c_id = c_id

    def post_check_in(self):
        # 查询是否打卡
        # 获取今日的时间段
        now = datetime.datetime.now()
        day_max = tp.get_day_max(now)
        day_min = tp.get_day_min(now)
        with redis_lock.Lock(lock_redis_store,
                             'check_in-{customer_id}'.format(customer_id=self.c_id), expire=60, auto_renewal=True):
            check_in: CheckIn = CheckIn.query.filter(and_(
                CheckIn.biz_id == self.biz_id,
                CheckIn.customer_id == self.c_id,
                CheckIn.check_in_date >= day_min,
                CheckIn.check_in_date <= day_max)).first()

            if check_in:
                return True, check_in.get_hash_id()
            else:
                # 未打卡
                rank = db.session.query(func.count(CheckIn.customer_id)).filter(and_(
                    CheckIn.biz_id == self.biz_id,
                    CheckIn.check_in_date >= day_min,
                    CheckIn.check_in_date <= day_max,
                )).scalar()

                check_in = CheckIn(
                    biz_id=self.biz_id,
                    customer_id=self.c_id,
                    check_in_date=now,
                    created_at=now,
                    rank=rank + 1)

                db.session.add(check_in)
                db.session.commit()
                db.session.refresh(check_in)

            return False, check_in.get_hash_id()

    def get_sum_record(self):
        # 总打卡
        check_ins = db.session.query(func.count(CheckIn.customer_id)).filter(and_(
            CheckIn.customer_id == self.c_id,
            CheckIn.biz_id == self.biz_id
        )).scalar()

        return check_ins

    def get_month_sum(self, today):
        # 月打卡
        # 月初
        early_month = tp.get_early_month(today)
        # 月末
        end_month = tp.get_end_month(today)
        # 查询
        check_ins = db.session.query(func.count(CheckIn.customer_id)).filter(and_(
            CheckIn.customer_id == self.c_id,
            CheckIn.biz_id == self.biz_id,
            CheckIn.check_in_date <= end_month,
            CheckIn.check_in_date >= early_month,
        )).scalar()
        return check_ins

    def get_recent(self):
        # 获取最近打卡情况
        recent = list()
        today = datetime.datetime.today()
        today_min = tp.get_day_min(today)
        today_max = tp.get_day_max(today)
        last_week = today_min - datetime.timedelta(days=7)

        week_check_in: List[CheckIn] = CheckIn.query.filter(and_(
            CheckIn.biz_id == self.biz_id,
            CheckIn.customer_id == self.c_id,
            CheckIn.check_in_date <= today_max,
            CheckIn.check_in_date >= last_week,
        )).all()

        check_in_dates = [check_in.check_in_date.strftime("%Y.%m.%d") for check_in in week_check_in]

        while today_min > last_week:
            today_str = today_min.strftime("%Y.%m.%d")
            if today_str in check_in_dates:
                recent.append(True)
            else:
                recent.append(False)

            today_min -= datetime.timedelta(days=1)
        return recent

    def get_rank(self, today, tomorrow):
        # 获取排名
        ranking: CheckIn = CheckIn.query.filter(and_(
            CheckIn.biz_id == self.biz_id,
            CheckIn.customer_id == self.c_id,
            CheckIn.check_in_date < tomorrow,
            CheckIn.check_in_date >= today,
        )).first()

        rank = ranking.rank
        return rank

    def get_month_record(self, today, days_of_month):
        # 月初
        early_month = tp.get_early_month(today)
        # 月末
        end_month = tp.get_end_month(today)
        year = early_month.year
        month = early_month.month

        check_ins: List[CheckIn] = CheckIn.query.filter(and_(
            CheckIn.biz_id == self.biz_id,
            CheckIn.customer_id == self.c_id,
            CheckIn.check_in_date >= early_month,
            CheckIn.check_in_date <= end_month
        )).all()
        check_in_dates = [check_in.check_in_date.strftime('%d') for check_in in check_ins]

        month_record = [self.get_check_in_dict(check_in_dates, year, month, day)
                        for day in range(1, days_of_month + 1)]
        return month_record

    def get_check_in_dict(self, check_in_dates, year, month, day):
        check_in_dict = dict()
        if ("%02d" % day) in check_in_dates:
            check_in_dict['day'] = day
            check_in_dict['sign'] = True
            today = datetime.datetime(year, month, day)
            tomorrow = tp.get_next_day(today)
            rank = self.get_rank(today=today, tomorrow=tomorrow)
            check_in_dict['rank'] = rank

            check_in: CheckIn = CheckIn.query.filter(and_(
                CheckIn.check_in_date >= today,
                CheckIn.check_in_date <= tomorrow,
                CheckIn.biz_id == self.biz_id,
                CheckIn.customer_id == self.c_id,
            )).first()
            check_in_dict['check_id'] = check_in.get_hash_id()
        else:
            check_in_dict['day'] = day
            check_in_dict['sign'] = False
        return check_in_dict

    def get_check_in_time(self, today_min, today_max):
        check_in: CheckIn = CheckIn.query.filter(and_(
            CheckIn.biz_id == self.biz_id,
            CheckIn.customer_id == self.c_id,
            CheckIn.check_in_date >= today_min,
            CheckIn.check_in_date <= today_max,
        )).first()

        if check_in:
            return check_in.check_in_date.strftime("%H:%M")
        else:
            return False


def get_detail_more(start_time, end_time, biz_id, customer_id, page):
    # 分组查询
    # 首先按照打卡次数由多到少排列, 并列的情况下按照最新打卡时间的由早到晚排列
    check_ins = db.session.query(
        CheckIn.customer_id, func.count(CheckIn.check_in_date)
    ).filter(and_(
        CheckIn.check_in_date >= start_time,
        CheckIn.check_in_date <= end_time,
        CheckIn.biz_id == biz_id
    )).order_by(
        desc(func.count(CheckIn.check_in_date)), asc(func.max(CheckIn.check_in_date))
    ).group_by(CheckIn.customer_id).paginate(page=page, per_page=20, error_out=False)

    own_checkin: CheckIn = CheckIn.query.filter(and_(
        CheckIn.customer_id == customer_id,
        CheckIn.biz_id == biz_id,
        CheckIn.check_in_date >= start_time,
        CheckIn.check_in_date <= end_time,
    )).first()

    # print(check_ins)  # [(3,3),(2,3)]
    check_in = CheckIn()  # 创建一个对象用于储存信息
    details = []
    if page == 1:
        # 第一页的时候获取本人的排名
        all_check_ins = db.session.query(
            CheckIn.customer_id, func.count(CheckIn.check_in_date)
        ).filter(and_(
            CheckIn.check_in_date >= start_time,
            CheckIn.check_in_date <= end_time,
            CheckIn.biz_id == biz_id
        )).order_by(
            desc(func.count(CheckIn.check_in_date)), asc(func.max(CheckIn.check_in_date))
        ).group_by(CheckIn.customer_id).all()

        if not own_checkin:
            checked_dict = {"count": False}
            details.insert(0, checked_dict)  # 将用户本人放到第一条
        else:
            for index, check in enumerate(all_check_ins):
                check_in.customer_id = check[0]
                check_in.count_num = check[1]
                checked_dict = get_checked_dict(check_in)

                if customer_id == check_in.customer_id:
                    checked_dict['rank'] = index + 1
                    details.insert(0, checked_dict)
                    break

    for index, check in enumerate(check_ins.items):
        check_in.customer_id = check[0]
        check_in.count_num = check[1]
        checked_dict = get_checked_dict(check_in)
        details.append(checked_dict)

    return details, check_ins.has_next


class RankingType:
    Day = 'day'
    Week = 'week'
    Month = 'month'
