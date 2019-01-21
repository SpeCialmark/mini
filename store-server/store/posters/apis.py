import re
import io
from datetime import datetime
from http import HTTPStatus

from flask import Blueprint, send_file
from flask import jsonify, request, g
from sqlalchemy import true
from store.config import cfg, _env
from store.database import db
from store.domain.cache import StoreBizCache, CustomerCache, AppCache
from store.domain.middle import roles_required, permission_required
from store.domain.models import Customer, Salesman, Qrcode, GroupReport, CommodityType, Goods, Course, \
    ShareType, Share, CheckIn, StoreBiz
from store.domain.role import CustomerRole
from store.domain.wxapp import UnlimitedCode, ReleaseQrcode
from store.posters.utils import generate_group_report_poster, generate_check_in_poster
from store.utils.oss import bucket
from store.utils.picture_processing import save_jpg_temp_file, save_png_temp_file

blueprint = Blueprint('_posters', __name__)


# @blueprint.route('/qrcode', methods=['GET'])
# def get_qrcode():
#     s_id = 11
#     salesman: Salesman = Salesman.query.filter(
#         Salesman.id == s_id
#     ).first()
#     brief = salesman.get_brief()
#     store_cache = StoreBizCache(biz_id=salesman.biz_id)
#     customer_app_id = store_cache.get('customer_app_id')
#     qrcode: Qrcode = SalesmanQrcode(app_id=customer_app_id, salesman=salesman).get()
#     url = qrcode.get_brief()['url']
#     brief.update({'url': url})
#     return jsonify({
#         'salesman': brief
#     })
#
#
# @blueprint.route('/templates', methods=['GET'])
# def get_templates():
#     poster_templates: List[PosterTemplate] = PosterTemplate.query.filter().all()
#     res = [p.get_brief() for p in poster_templates]
#     return jsonify(res)
#
#
# @blueprint.route('/templates/<string:t_id>', methods=['GET'])
# def get_template_detail(t_id):
#     poster_template: PosterTemplate = PosterTemplate.find(t_id)
#
#     return jsonify(poster_template.get_brief())


@blueprint.route('/group_report/<string:r_id>', methods=['GET'])
@roles_required(CustomerRole())
def get_group_report_poster(r_id):
    biz_id = g.get('biz_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    store_cache = StoreBizCache(biz_id)
    customer_app_id = store_cache.get('customer_app_id')
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号异常'), HTTPStatus.NOT_FOUND
    group_report: GroupReport = GroupReport.find(r_id)
    if not group_report:
        return jsonify(msg='该拼团不存在'), HTTPStatus.BAD_REQUEST
    private_parameter = group_report.activity.private_parameter
    commodity_type = private_parameter.get('type')
    commodity_id = private_parameter.get('id')
    if commodity_type == CommodityType.Goods:
        goods: Goods = Goods.find(commodity_id)
        if not goods:
            return jsonify(msg='商品不存在'), HTTPStatus.NOT_FOUND
        image = goods.images[0]
    elif commodity_type == CommodityType.Course:
        course: Course = Course.find(commodity_id)
        image = course.images[0]
        if not course:
            return jsonify(msg='商品不存在'), HTTPStatus.NOT_FOUND
    else:
        return jsonify(msg='商品类别错误'), HTTPStatus.BAD_REQUEST

    path_id = 'A'  # 这个ID由客户端定义, 但是得注意版本兼容性
    code_mode = 1
    scene = '{code_mode}&{path_id}&{r_id}'.format(code_mode=code_mode, path_id=path_id, r_id=group_report.get_hash_id())
    qrcode = UnlimitedCode(app_id=customer_app_id).get_raw_code(scene)
    poster = generate_group_report_poster(qrcode, group_report.activity.name, image, customer.avatar)

    poster_bytes = io.BytesIO()
    poster.save(poster_bytes, format='PNG')
    poster_bytes.seek(0)
    file_name = 'poster.png'
    res = send_file(poster_bytes, attachment_filename=file_name, mimetype='image/png', as_attachment=true)
    return res


@blueprint.route('/check_in/<string:ch_id>', methods=['POST'])
@roles_required(CustomerRole())
def post_check_in_poster(ch_id):
    biz_id = g.get('biz_id')
    app_id = g.get('app_id')
    c_id = CustomerRole(biz_id).get_id(g.role)
    customer: Customer = Customer.query.filter(
        Customer.id == c_id
    ).first()
    if not customer:
        return jsonify(msg='账号有误'), HTTPStatus.NOT_FOUND
    check_in: CheckIn = CheckIn.find(ch_id)
    if not check_in:
        return jsonify(msg='打卡信息不存在'), HTTPStatus.NOT_FOUND

    json_data = request.get_json()
    image = json_data.get('image')
    step_count = json_data.get('step_count')
    # 健康数据
    record_data = json_data.get('record')

    image_dir = cfg['aliyun_oss']['biz_res_dir'].format(biz_hid=StoreBiz.encode_id(biz_id), folder='tmp')
    if _env == 'dev':
        image_dir = 'dev/' + image_dir

    if re.search(image_dir, image):
        # 如果图片为自主上传的图片则将该图片路径与该打卡关联(生命周期为5天)
        check_in.image = image
        check_in.modified_at = datetime.now()
        db.session.commit()

    qrcode: Qrcode = ReleaseQrcode(app_id=app_id).get()
    app_cache = AppCache(app_id=app_id)
    store_name = app_cache.get('nick_name')

    poster = generate_check_in_poster(qrcode, customer, image, step_count, record_data, check_in, store_name)
    tmp = save_jpg_temp_file(poster)
    # 上传到oss
    now = datetime.now()
    file_name = customer.get_hash_id() + now.strftime('%Y%m%d%H%M%S') + '.jpg'
    _dir = cfg['aliyun_oss']['user_check_in_path']
    if _env == 'dev':
        _dir = 'dev/' + _dir
    key = _dir.format(biz_hid=StoreBiz.encode_id(biz_id), file_name=file_name)
    bucket.put_object_from_file(key=key, filename=tmp.name)
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    tmp.close()  # 删除临时文件
    return jsonify({
        'image_url': image_url
    })
