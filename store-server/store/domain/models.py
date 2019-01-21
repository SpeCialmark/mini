import json
import time
from typing import List
from abc import ABCMeta, abstractmethod
from store.database import db
from sqlalchemy.dialects.postgresql import JSONB
from hashids import Hashids
from store.config import cfg, _env, get_res
from enum import IntEnum
from datetime import datetime, timedelta
from sqlalchemy import UniqueConstraint, desc, true, asc, func, or_

from store.utils.oss import encode_app_id
from store.utils.image import get_random_avatar
from werkzeug.security import generate_password_hash, check_password_hash

DUMMY_ID = '0'


class Hashable(object):
    hash_ids: Hashids = None

    @classmethod
    def find(cls, h_id):
        s_id = cls.decode_id(h_id)
        if s_id is None:
            return None
        s = cls.query.filter(cls.id == s_id).first()
        return s

    @classmethod
    def encode_id(cls, db_id: int) -> str:
        return cls.hash_ids.encode(db_id)

    @classmethod
    def decode_id(cls, h_id: str):
        # 解码h_id,方便查询缓存
        ids = cls.hash_ids.decode(h_id)
        if not ids:
            return None
        s_id = ids[0]
        return s_id

    def get_hash_id(self) -> str:
        return self.hash_ids.encode(self.id)


class AppMark(IntEnum):
    CUSTOMER = 1
    COACH = 2
    BOSS = 3


class WxAuthorizer(db.Model, Hashable):
    id = db.Column(db.Integer, primary_key=True)
    app_id = db.Column(db.String, unique=True, nullable=False, index=True)

    is_authorized = db.Column(db.Boolean, default=True)
    refresh_token = db.Column(db.String)
    """ 
    https://api.weixin.qq.com/cgi-bin/component/api_query_auth?component_access_token=xxxx
    接口调用凭据刷新令牌（在授权的公众号具备API权限时，才有此返回值），刷新令牌主要用于第三方平台获取和刷新已授权用户的access_token，只会在授权时刻提供，请妥善保存。 一旦丢失，只能让用户重新授权，才能再次拿到新的刷新令牌 
    """

    nick_name = db.Column(db.String)
    """ 授权方昵称 """
    head_img = db.Column(db.String)
    """ 授权方头像 """
    verify_type_info = db.Column(JSONB)
    """ 授权方认证类型，-1代表未认证，0代表微信认证 """
    user_name = db.Column(db.String)
    """ 小程序的原始ID """
    signature = db.Column(db.String)
    """ 帐号介绍 """
    principal_name = db.Column(db.String)
    """ 小程序的主体名称 """

    business_info = db.Column(JSONB)
    """ 功能的开通状况 """

    qrcode_url = db.Column(db.String)
    """ 二维码图片的URL，开发者最好自行也进行保存 """
    mini_program_info = db.Column(JSONB)
    """ miniprograminfo, 可根据这个字段判断是否为小程序类型授权 """

    func_info = db.Column(JSONB)
    """
    小程序授权给开发者的权限集列表，ID为17到19时分别代表： 17.帐号管理权限 18.开发管理权限 19.客服消息管理权限 请注意： 1）该字段的返回不会考虑小程序是否具备该权限集的权限（因为可能部分具备）。
    """
    authorizer_info = db.Column(JSONB)
    """ https://api.weixin.qq.com/cgi-bin/component/api_get_authorizer_info """

    option = db.Column(JSONB)
    """ 授权方的选项设置信息 """

    mark = db.Column(db.Integer)
    """ 指明用户端, 还是教练端, BOSS端 """

    template_id = db.Column(db.Integer, default=0)
    """  StoreTemplate id """

    biz_id = db.Column(db.Integer, index=True)
    """ biz_id """

    """ 检查基本信息  """
    check_info_time = db.Column(db.DateTime)
    check_info_result = db.Column(JSONB)

    """ 设置模板 """
    set_template = db.Column(JSONB)
    set_template_time = db.Column(db.DateTime)
    set_template_result = db.Column(JSONB)

    """ 设置数据库 """
    set_db = db.Column(JSONB)
    set_db_time = db.Column(db.DateTime)
    set_db_result = db.Column(JSONB)

    """ 提交代码 """
    commit = db.Column(JSONB)
    commit_time = db.Column(db.DateTime)
    commit_result = db.Column(JSONB)

    """ 提交审核 """
    submit = db.Column(JSONB)
    submit_time = db.Column(db.DateTime)
    submit_result = db.Column(JSONB)

    """ 审核 """
    # audit = db.Column(JSONB)
    audit_time = db.Column(db.DateTime)
    audit_result = db.Column(JSONB)

    """ 发版 """
    release = db.Column(JSONB)
    release_time = db.Column(db.DateTime)
    release_result = db.Column(JSONB)

    auto_release = db.Column(db.Boolean, default=True)
    """ 审核过后自动发布  """

    created_at = db.Column(db.DateTime, nullable=False)
    authorized_at = db.Column(db.DateTime)
    unauthorized_at = db.Column(db.DateTime)
    modified_at = db.Column(db.DateTime)

    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-wx_authorizer')

    def get_page(self):
        return {
            'app_id': self.app_id,
            'is_authorized': self.is_authorized,
            'nick_name': self.nick_name,
            'head_img': self.head_img,
            'verify_type_info': self.verify_type_info,
            'user_name': self.user_name,
            'signature': self.signature,
            'principal_name': self.principal_name,
            'business_info': self.business_info,
            'mini_program_info': self.mini_program_info,
            'func_info': self.func_info,
            'option': self.option,
            'authorized_at': self.authorized_at
        }

    def __str__(self):
        return 'user_name:{user_name}, nick_name:{nick_name}, principal_name:{principal_name}, app_id:{app_id}'.format(
            user_name=self.user_name, nick_name=self.nick_name, principal_name=self.principal_name, app_id=self.app_id
        )

    def get_brief(self):
        return {
            'id': self.get_hash_id(),
            'nick_name': self.nick_name,
            'head_img': self.head_img,
            'mark': AppMark(self.mark).name.lower()
        }


class Customer(db.Model, Hashable):
    """ 普通用户 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True, nullable=False)

    w_id = db.Column(db.Integer, unique=True, nullable=False)
    """ WxOpenUser id """

    avatar = db.Column(db.String)
    nick_name = db.Column(db.String)

    salesman_id = db.Column(db.Integer, index=True, default=0)
    """ 会籍id(用于记录该用户是否是通过会籍进入的) """
    from_share_id = db.Column(db.Integer, default=0)
    """ 通过此share_id进入(默认为0,如果用户是新用户且是通过分享的方式进入小程序则绑定该分享id) """
    is_login = db.Column(db.Boolean, default=False)
    """ 是否登录 """
    phone_number = db.Column(db.String)
    """ 手机号码(可以通过该手机号来校验此customer是否是salesman) """
    name = db.Column(db.String)
    """ 姓名(到店登记时输入) """
    tags = db.Column(db.JSON)
    """ 标签(客户可自己输入,用做智能推荐的素材) """
    belong_salesman_id = db.Column(db.Integer, index=True, default=0)
    """ 所属会籍(第一次获取到用户手机号码的会籍) """
    height = db.Column(db.Integer)
    """ 身高(cm) """
    step_count = db.Column(JSONB)
    # [{'step_count': 2333, 'data': '2018-11-11 11:11:11'}]
    """ 步数(只存30天) """
    gender = db.Column(db.Integer)
    """ 性别(1男,2女) """
    birthday = db.Column(db.String)
    """ 生日 """
    demand = db.Column(db.ARRAY(db.String), default=[])
    """ 会员需求(根据体侧结果或会员口述进行填写) """
    training_note = db.Column(db.String)
    """ 训练备注(会员填写) """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-customer')

    def get_step_count(self) -> list:
        return self.step_count[-7:] if self.step_count else None

    def get_base_info(self) -> dict:
        return {
            'gender': self.gender,
            'height': self.height,
            'birthday': self.birthday or ''
        }


class WxOpenUser(db.Model):
    """ 登录到平台的微信小程序用户, 会切换不同的角色， 普通用户，管理员，会员 """
    id = db.Column(db.Integer, primary_key=True)
    wx_open_id = db.Column(db.String, index=True, nullable=False)
    app_id = db.Column(db.String, index=True, nullable=False)
    login_biz_id = db.Column(db.Integer, index=True)
    """ 登陆的biz_id(用于切换门店) """

    session_key = db.Column(db.String)
    wx_info = db.Column(JSONB)
    """ 性别 0：未知、1：男、2：女  """

    role = db.Column(db.String)
    customer_id = db.Column(db.Integer, default=0)  # 非空唯一, 由代码控制
    manager_id = db.Column(db.Integer, default=0)
    coach_id = db.Column(db.Integer, default=0)  # 非空唯一, 由代码控制 教练角色

    login_at = db.Column(db.DateTime)
    token = db.Column(db.String)
    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    __table_args__ = (
        UniqueConstraint('wx_open_id', 'app_id', name='_open_id_app_id'),
    )


class BizUser(db.Model, Hashable):
    """ 商家用户 """
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String, unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String)

    name = db.Column(db.String)
    token = db.Column(db.String)
    login_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-biz_user')

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)


class StoreTemplate(db.Model):
    """ 模板 """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True)
    """ 唯一name, 内部使用 """

    title = db.Column(db.String)

    app_mark = db.Column(db.Integer)

    """ 显示给客户端 """
    wx_template_id = db.Column(db.Integer)
    """ 小程序模板库的 """
    version = db.Column(db.String)
    """ 小程序的版本号 """
    ext_json_format = db.Column(JSONB)
    description = db.Column(db.String)

    params_desc = db.Column(JSONB)

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    def get_admin_page(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'title': self.title,
            'wx_template_id': self.wx_template_id,
            'version': self.version,
            'ext_json_format': self.ext_json_format,
            'params_desc': self.params_desc,
            'description': self.description,
            'created_at': self.created_at.strftime('%-m月%-d日 %H:%M'),
            'modified_at': self.modified_at.strftime('%-m月%-d日 %H:%M') if self.modified_at else None,
        }

    @property
    def is_available(self):
        return bool(self.wx_template_id) and bool(self.ext_json_format)

    def get_brief(self) -> dict:
        return {
            'id': self.id,
            'title': self.title
        }


class StoreBiz(db.Model, Hashable):
    """ 商家主体 """
    id = db.Column(db.Integer, primary_key=True)
    biz_user_id = db.Column(db.Integer, index=True)

    name = db.Column(db.String)
    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    settings = db.Column(db.JSON)
    """ 自定义配置 """

    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-store_biz')


class WxMsgTemplate(db.Model):
    """ 微信模板消息, 目前在代码把short_id和app_id作为唯一, 但是数据库不做强制 """
    id = db.Column(db.Integer, primary_key=True)
    app_id = db.Column(db.String, index=True)
    template_id = db.Column(db.String)
    """ 用于发送时候的template_id """
    title = db.Column(db.String)
    """ 标题 """
    short_id = db.Column(db.String)
    """ 样板id """

    keyword_id_list = db.Column(db.ARRAY(db.Integer))
    created_at = db.Column(db.DateTime, nullable=False)


class Store(db.Model):
    """ 门店 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True, unique=True)

    template_id = db.Column(db.Integer, default=0)
    cards = db.Column(JSONB)
    contact = db.Column(JSONB)

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    course_indexes = db.Column(db.ARRAY(db.Integer))
    coach_indexes = db.Column(db.ARRAY(db.Integer))
    emails = db.Column(JSONB)
    """ 接收预约到店的邮箱(支持多个) """
    video_fileid = db.Column(JSONB)
    """ 首页展示视频fileid """

    # default_coach_permission = db.Column(db.ARRAY(db.String), default=[ViewBizPermission.name, ViewBizWebPermission.name,])
    # """ 商家的默认教练权限 """

    def get_raw_cards(self):
        return self.cards

    @staticmethod
    def find_card(cards, c_id):
        for card_index, card in enumerate(cards):
            if card['id'] == c_id:
                return card, card_index
        return None, None

    @staticmethod
    def get_view(cards):
        pass

    def get_address(self):
        for card in self.cards:
            if 'contact' in card.keys():
                for contact in card['contact']:
                    if 'address' in contact.keys():
                        return contact['address']
        else:
            return '暂无地址数据'

    def get_position(self):
        for card in self.cards:
            if 'contact' in card.keys():
                for contact in card['contact']:
                    if 'latitude' and 'longitude' in contact.keys():
                        return contact['latitude'], contact['longitude']
        else:
            return 0, 0

    def get_business_hours(self):
        for card in self.cards:
            if card.get('type') == 'business-hours':
                begin_str = card.get('begin')
                end_str = card.get('end')
                begin_hh = int(begin_str.split(':')[0])
                begin_mm = int(begin_str.split(':')[1])
                begin = begin_hh * 60 + begin_mm
                end_hh = int(end_str.split(':')[0])
                end_mm = int(end_str.split(':')[1])
                end = end_hh * 60 + end_mm
                return begin, end
        # 如果没有设置, 返回8:00, 23:00, 在预约时需要做逻辑判断
        return 480, 1380

    def get_slogan(self):
        for card in self.cards:
            if card.get('title') == 'slogan':
                return card.get('text')
        return "Fitness diary 健身日记"


class Qrcode(db.Model):
    """ 小程序二维码, app_id 和 name构成唯一, 注意filename, 避免覆盖 """
    id = db.Column(db.Integer, primary_key=True)
    # biz_id = db.Column(db.Integer, index=True)
    app_id = db.Column(db.String, index=True)
    name = db.Column(db.String)
    description = db.Column(db.String)

    app_nick_name = db.Column(db.String)
    app_head_img = db.Column(db.String)

    file_name = db.Column(db.String)

    is_limit = db.Column(db.Boolean)
    """ 是否有数量限制 """
    path = db.Column(db.String)
    """ is_limit类型的, 不能为空，最大长度 128 字节 """
    scene = db.Column(db.String)
    """ 最大32个可见字符，只支持数字，大小写英文以及部分特殊字符：!#$&'()*+,/:;=?@-._~，其它字符请自行编码为合法字符（因不支持%，中文无法使用 urlencode 处理，请使用其他编码方式） """
    page = db.Column(db.String)
    """ 必须是已经发布的小程序存在的页面（否则报错），例如 "pages/index/index" ,根路径前不要填加'/',不能携带参数（参数请放在scene字段里），如果不填写这个字段，默认跳主页面 """

    width = db.Column(db.Integer)
    """ 二维码的宽度 """
    auto_color = db.Column(db.Boolean)
    """ 自动配置线条颜色，如果颜色依然是黑色，则说明不建议配置主色调  """
    line_color = db.Column(JSONB)
    is_hyaline = db.Column(db.Boolean)

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    __table_args__ = (
        UniqueConstraint('name', 'app_id', name='_name_app_id'),
    )

    def get_brief(self):
        hid = encode_app_id(self.app_id)
        cdn_host: str = cfg['aliyun_oss']['cdn_host']
        qrcode_path = cfg['aliyun_oss']['qrcode_path'].format(app_hid=hid, file_name=self.file_name)
        if _env == 'dev':
            qrcode_path = 'dev/' + qrcode_path
        url = cdn_host + '/' + qrcode_path
        return {
            'name': self.name,
            'url': url
        }


class Course(db.Model, Hashable):
    """ 课程 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)

    title = db.Column(db.String)
    price = db.Column(db.String)
    images = db.Column(JSONB)

    content = db.Column(JSONB)
    course_type = db.Column(db.String)  # 课程类别(私教或团课)

    videos = db.Column(db.ARRAY(db.Integer), default=[])
    """ 视频id """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-course')

    def get_brief(self) -> dict:
        return {
            'id': self.get_hash_id(),
            'title': self.title,
            'image': self.images[0] if self.images and len(self.images) else None,
            'price': self.price or '',
            'type': self.course_type,
            'content': self.content,
        }

    def get_page(self) -> dict:
        return {
            'id': self.get_hash_id(),
            'title': self.title,
            'images': self.images,
            'price': self.price or '',
            'content': self.content,
            'type': self.course_type,
        }

    def get_videos(self) -> list:
        vs = []
        if self.videos:
            videos: List[Video] = Video.query.filter(
                Video.id.in_(self.videos)
            ).all()
            vs.extend(videos)
        vs.sort(key=lambda x: (x.created_at), reverse=True)
        return vs


class Coach(db.Model, Hashable):
    """ 教练 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    # biz_user_id = db.Column(db.Integer)

    name = db.Column(db.String)
    images = db.Column(JSONB)
    """ 教练相册 """
    avatar = db.Column(db.String)
    """ 头像(v11.17以上版本) """
    cover = db.Column(db.String)
    """ 卡片封面(v11.17以上版本) """

    good_at = db.Column(JSONB)
    trainer_cases = db.Column(JSONB)
    content = db.Column(JSONB)
    courses = db.Column(JSONB)

    phone_number = db.Column(db.String)
    coach_type = db.Column(db.String, nullable=False)

    exp_reservation = db.Column(db.Boolean, default=False)
    """ 允许约体验课 """
    exp_price = db.Column(db.Integer, default=0)
    """ 体验课价格(默认为免费) """
    permission_list = db.Column(db.ARRAY(db.String))
    """ 权限列表(支持修改,创建时赋予默认权限) """
    # [[6, "COACH", "put", 2], [6, "feed", "all", null], [6, "biz", "get", null], [6, "web", "get", null]]
    in_service = db.Column(db.Boolean, default=True)
    """ 是否在职 """
    not_in_service_at = db.Column(db.DateTime)
    """ 离职时间 """
    videos = db.Column(db.ARRAY(db.Integer), default=[])
    """ 视频id """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-coach')

    @classmethod
    def get(cls, c_id):
        c = cls.query.filter(cls.id == c_id).first()
        return c

    def get_brief(self) -> dict:
        return {
            'id': self.get_hash_id(),
            'name': self.name,
            'images': self.images,
            'good_at': self.good_at,
            'type': self.coach_type,
            "exp_reservation": self.exp_reservation if self.exp_reservation else False,
            'avatar': self.avatar if self.avatar else self.images[0],  # 新版头像
            'image': self.avatar if self.avatar else self.images[0],  # 兼容之前版本(版本更新完成字段迁移后将此字段删除)
            'cover': self.cover
        }

    def get_page(self) -> dict:
        courses_brief = []
        if self.courses:
            for cc in self.courses:
                c: Course = Course.query.filter(Course.id == cc['id']).first()
                if c:
                    courses_brief.append(c.get_brief())

        return {
            'id': self.get_hash_id(),
            'name': self.name,
            'images': self.images,
            'good_at': self.good_at,
            'content': self.content,
            'trainer_cases': self.trainer_cases,
            'courses': courses_brief or [],
            'phone_number': self.phone_number,
            'type': self.coach_type,
            'avatar': self.avatar,
            'image': self.avatar if self.avatar else self.images[0],
            'cover': self.cover
        }

    def get_videos(self) -> list:
        vs = []
        if self.videos:
            videos: List[Video] = Video.query.filter(
                Video.id.in_(self.videos)
            ).all()
            vs.extend(videos)
        vs.sort(key=lambda x: (x.created_at), reverse=True)
        return vs


class PhotoWall(db.Model, Hashable):
    """ 照片墙(每张图片单独一条记录) """
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-photo_wall')
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True, nullable=False)
    coach_id = db.Column(db.Integer, index=True)
    """ 每个教练都有自己的照片墙 """
    photo = db.Column(db.String)
    """ 图片url """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    @staticmethod
    def get_photos(coach_id):
        photo_wall: List[PhotoWall] = PhotoWall.query.filter(
            PhotoWall.coach_id == coach_id
        ).order_by(desc(PhotoWall.created_at)).all()
        if not photo_wall:
            return []
        return [{"id": p.get_hash_id(), "photo": p.photo} for p in photo_wall]


class Manager(db.Model):
    """ 课程 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True, nullable=False)

    # open_user_id = db.Column(db.Integer)
    """ 一开始可能为空，如果从管理后台创建的 """
    # login_c_id = db.Column(db.Integer)
    """ 以哪个customer_id 登录的 """
    # wx_open_id = db.Column(db.String, index=True)
    # session_key = db.Column(db.String)

    phone_number = db.Column(db.String, index=True)
    # biz_id = db.Column(db.Integer, index=True)

    # login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)


class Book(db.Model):
    """ 预约 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer)

    customer_id = db.Column(db.Integer)
    phone_number = db.Column(db.String)
    book_time = db.Column(db.String)
    book_datetime = db.Column(db.DateTime)

    name = db.Column(db.String)
    avatar = db.Column(db.String)
    wx = db.Column(db.String)
    course = db.Column(db.String)
    created_at = db.Column(db.DateTime, nullable=False)

    def get_page(self) -> dict:
        return {
            'phone_number': self.phone_number,
            'time': self.get_readable_time(),
            'name': self.name,
            'course': self.course,
            'wx': self.wx,
            'avatar': self.avatar or get_random_avatar(),
            'created_at': self.created_at.strftime('%-m月%-d %H:%M')
        }

    def get_readable_time(self):
        now = datetime.now()
        time_str = ''

        if self.book_datetime:
            delta = self.book_datetime.date() - now.date()
            if delta.days == 0:
                time_str = '今天'
            elif delta.days == 1:
                time_str = '明天'
            elif delta.days == 2:
                time_str = '后天'
            time_str = time_str + self.book_datetime.strftime('%-m月%-d日 %H:%M')
        return time_str


class MgrMessage(db.Model):
    """ 管理员消息 """
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer)

    content = db.Column(JSONB)

    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, nullable=False)


class GroupCourse(db.Model):
    """Group Course Info"""
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    biz_id = db.Column(db.Integer, index=True)
    group_time_id = db.Column(db.Integer, index=True)

    start_time = db.Column(db.Integer)
    end_time = db.Column(db.Integer)
    week = db.Column(db.Integer)

    place = db.Column(db.String)
    place_id = db.Column(db.Integer, index=True)

    course_id = db.Column(db.Integer)
    coach_id = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    def get_brief(self) -> dict:
        return {
            'start_time': self.start_time,
            'end_time': self.end_time,
            'week': self.week,
            'place': self.place,
            'course_id': self.course_id,
            'coach_id': self.coach_id,
            'place_id': self.place_id
        }


class GroupTime(db.Model, Hashable):
    """Group Time Info"""
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    biz_id = db.Column(db.Integer, index=True)
    start_date = db.Column(db.Date)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-group_time')

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)


class CheckIn(db.Model, Hashable):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    biz_id = db.Column(db.Integer, index=True, nullable=False)
    customer_id = db.Column(db.Integer, index=True, nullable=False)
    check_in_date = db.Column(db.DateTime, index=True)
    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    rank = db.Column(db.Integer)
    image = db.Column(db.String)
    """ 自定义的图片 """
    # words = db.Column(db.String)
    # """ 自定义的激励语 """
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-check_in')


class Feed(db.Model, Hashable):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    biz_id = db.Column(db.Integer, index=True)
    images = db.Column(JSONB)
    words = db.Column(db.String)
    coach_id = db.Column(db.Integer)
    """ 教练以自己的名义发送 """
    video = db.Column(JSONB)
    """ 视频的id和url """
    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-feed')


class Trainee(db.Model, Hashable):
    """" 学员 """
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    coach_id = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer, index=True)

    name = db.Column(db.String)

    total_lessons = db.Column(db.Integer, default=0)
    # TODO 新版本课时不再使用该字段
    """ 总课时 """
    attended_lessons = db.Column(db.Integer, default=0)
    """ 已经上课的课时 """
    is_exp = db.Column(db.Boolean, default=False)
    """ 是否是体验会员 """
    is_bind = db.Column(db.Boolean, default=False)
    """ 是否是私教 """
    is_measurements = db.Column(db.Boolean, default=False)
    """ 是否是体测会员 """
    accepted_at = db.Column(db.DateTime)
    """ 接受成为体测会员的时间 """
    phone_number = db.Column(db.String)

    bind_at = db.Column(db.DateTime)
    """ 绑定时间 """
    unbind_at = db.Column(db.DateTime)
    """ 解绑时间 """
    note = db.Column(db.JSON)
    """ 备注 """
    tags = db.Column(db.JSON)
    """ 标签 """
    gender = db.Column(db.Integer)
    """ 性别 """
    age = db.Column(db.Integer)
    """ 年龄 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-trainee')
    __table_args__ = (
        UniqueConstraint('coach_id', 'customer_id', name='_coach_id_customer_id'),
    )

    def get_brief(self) -> dict:
        return {
            'name': self.name
        }

    def get_detail(self) -> dict:
        return {
            'name': self.name,
            'gender': self.gender,
            'age': self.age if self.age else "",
            'tags': self.tags if self.tags else [],
            'note': self.note if self.note else "",
        }

    @property
    def remained_lesson(self) -> int:
        return self.total_lessons - self.attended_lessons


class BaseSeat(object):
    min_interval = 5

    @property
    def time_id(self):
        hour = int(self.start / 60)
        minute = self.start - hour * 60
        return self.yymmdd * 10000 + hour * 100 + minute

    @property
    def slices(self) -> set:
        return set(range(self.start, self.end, self.min_interval))

    @property
    def end_time(self) -> datetime:
        year = int(self.yymmdd / 10000)
        month = int((self.yymmdd - year * 10000) / 100)
        day = self.yymmdd - year * 10000 - month * 100
        hour = int(self.end / 60)
        minute = self.end - hour * 60
        end_time = datetime(year=year, month=month, day=day, hour=hour, minute=minute)
        return end_time

    @property
    def start_time(self) -> datetime:
        year = int(self.yymmdd / 10000)
        month = int((self.yymmdd - year * 10000) / 100)
        day = self.yymmdd - year * 10000 - month * 100
        hour = int(self.start / 60)
        minute = self.start - hour * 60
        start_time = datetime(year=year, month=month, day=day, hour=hour, minute=minute)
        return start_time


class SeatStatus(IntEnum):
    CONFIRM_EXPIRED = -100  # 确认过期
    AVAILABLE = 0           # 可预约
    BREAK = 100             # 休息
    CONFIRM_REQUIRED = 200  # 待确认
    CONFIRMED = 300         # 已确认
    ATTENDED = 400          # 已上课


class SeatPriority(IntEnum):
    # 数字越大, 优先级越高
    EXPERIENCE = 100       # 体验课
    PRIVATE = 200          # 私教课


class Seat(db.Model, BaseSeat, Hashable):
    id = db.Column(db.Integer, primary_key=True)
    coach_id = db.Column(db.Integer, index=True)
    yymmdd = db.Column(db.Integer, index=True)
    """ 比如20180701, int """
    start = db.Column(db.Integer)
    """ 比如480, 代表8:00 """
    end = db.Column(db.Integer)

    status = db.Column(db.Integer)
    priority = db.Column(db.Integer)
    """ 优先级 """
    is_valid = db.Column(db.Boolean, default=True)
    """ 是否有效, 默认是有效的, cancel之后将失效 """

    customer_id = db.Column(db.Integer, index=True)

    reserved_at = db.Column(db.DateTime)
    """ 学员发起时间  """

    confirmed_at = db.Column(db.DateTime)
    """ 教练确认时间 """

    canceled_at = db.Column(db.DateTime)
    """ 教练取消时间 """

    note = db.Column(db.String)
    """ 备注(教练设置休息时可以输入) """
    is_check = db.Column(db.Boolean, default=False)
    """ 核销状态(未核销, 已核销) """
    checked_at = db.Column(db.DateTime)
    """ 核销时间 """
    course_id = db.Column(db.Integer)
    """ 课程id """
    is_group = db.Column(db.Boolean)
    """ 销课类型(单人\多人) """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-seat')

    @property
    def duration(self) -> int:
        return self.end - self.start


class SeatCheckLog(db.Model):
    """ 销课记录表 """
    id = db.Column(db.Integer, primary_key=True, index=True)
    biz_id = db.Column(db.Integer, index=True)
    seat_id = db.Column(db.Integer)
    """ 课程id """
    name = db.Column(db.String)
    """ 上课用户姓名 """
    phone_number = db.Column(db.String)
    """ 上课用户手机号码 """
    checked_at = db.Column(db.DateTime)
    """ 核销时间 """


class FormId(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.String)
    app_id = db.Column(db.String)
    """ 发送后跳转进入的app_id """
    open_id = db.Column(db.String, index=True)
    """ 接收者的open_id """
    expire_at = db.Column(db.Integer, index=True)
    """ 过期时间(时间戳) """
    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)


class WxMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    app_id = db.Column(db.String)
    """ 发送后跳转进入的app_id """
    open_id = db.Column(db.String, index=True)
    """ 接收者的open_id """
    task = db.Column(db.String)
    """ 任务 """
    # "send binding message to coach 1"
    publish_at = db.Column(db.DateTime)
    """ 任务时间 """
    result = db.Column(db.JSON)
    """ 任务执行结果(返回的信息) """
    # {'errcode': 0,'errmsg': 'ok'} or
    # {'errcode: 41029, 'errmsg': 'form id used count reach limit hint: [5Usq0175ge31]'}
    executed_at = db.Column(db.DateTime)
    """ 任务执行时间 """
    data = db.Column(db.JSON)
    """ 发送信息时的参数 """
    is_completed = db.Column(db.Boolean)
    """ 是否被执行 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)


class LessonRecordStatus(IntEnum):
    RECHARGE = 100  # 续课
    ATTENDED = 200  # 已上课
    CANCEL = -100  # 教练操作取消
    DEDUCTION = -200  # 减少课时


class LessonRecord(db.Model):
    # TODO 课程核销版本上线后上课记录不再使用此表, 而是直接通过seat的is_check来进行查询
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, index=True)
    coach_id = db.Column(db.Integer)
    status = db.Column(db.Integer)
    """ 状态 """
    executed_at = db.Column(db.DateTime)
    """ 执行时间 """
    charge = db.Column(db.Integer)
    """ 费用 """

    seat_id = db.Column(db.Integer)
    """ 课程ID """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)


class Beneficiary(db.Model):
    """ 合同受益人表(用于记录一份合同中的受益人) """
    # 本表用于记录用户签订合同的情况(方便查询)
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    contract_id = db.Column(db.Integer, index=True)
    """ 合同id """
    customer_id = db.Column(db.Integer)
    """ 录入合同时,用户可能还未登陆过,因此可以为空 """
    name = db.Column(db.String)
    """ 姓名 """
    phone_number = db.Column(db.String)
    """ 手机号 """

    @staticmethod
    def get_contract_ids(biz_id, customer_id=None, phone_number=None):
        if not customer_id and not phone_number:
            return []
        if customer_id:
            beneficiaries: List[Beneficiary] = Beneficiary.query.filter(
                Beneficiary.biz_id == biz_id,
                Beneficiary.customer_id == customer_id,
            ).all()
        elif phone_number:
            beneficiaries: List[Beneficiary] = Beneficiary.query.filter(
                Beneficiary.biz_id == biz_id,
                Beneficiary.phone_number == phone_number,
            ).all()
        else:
            beneficiaries: List[Beneficiary] = Beneficiary.query.filter(
                Beneficiary.biz_id == biz_id,
                or_(
                    Beneficiary.customer_id == customer_id,
                    Beneficiary.phone_number == phone_number,
                )
            ).all()
        contract_ids = [b.contract_id for b in beneficiaries]
        return contract_ids


class ContractContent(db.Model):
    """ 合同内容(课程名字\课时\价格) """
    # 该表用做课时记录
    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, index=True)
    """ 合同id """
    course_id = db.Column(db.Integer)
    """ 课程id """
    coach_id = db.Column(db.Integer)
    """ 教练id """
    total = db.Column(db.Integer)
    """ 购买课时 """
    attended = db.Column(db.Integer)
    """ 已上课时 """
    price = db.Column(db.Float)
    """ 价格 """
    is_valid = db.Column(db.Boolean, default=True)
    """ 是否正在生效(删除合同后失效) """
    is_group = db.Column(db.Boolean)
    """ 是否是多人合同 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    @staticmethod
    def get_remainder_lesson(customer_id, course_id, is_group):
        contract_ids = Contract.get_customer_valid_contract_ids(customer_id)
        lesson: List[ContractContent] = ContractContent.query.filter(
            ContractContent.course_id == course_id,
            ContractContent.is_group == is_group,
            ContractContent.is_valid == true(),
            ContractContent.contract_id.in_(contract_ids)
        ).all()
        total = 0
        attended = 0
        for l in lesson:
            total += l.total
            attended += l.attended
        remainder = total - attended
        return remainder


class Contract(db.Model, Hashable):
    """ 合同 """
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-contract')
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    content = db.Column(JSONB, default=[])
    """ 合同内容(课程名字\课时\价格) """
    # [{course_id: 'xx', price: '199.9', total: '10', coach_id: 'xx'}, {}, {}]
    signed_at = db.Column(db.DateTime, nullable=False)
    """ 签订时间 """
    canceled_at = db.Column(db.DateTime)
    """ 取消时间 """
    note = db.Column(db.String)
    """ 备注 """
    images = db.Column(db.ARRAY(db.String), default=[])
    """ 合同照片 """
    is_valid = db.Column(db.Boolean, default=True)
    """ 是否正在生效(删除合同后失效) """
    is_group = db.Column(db.Boolean)
    """ 是否是多人合同 """

    created_at = db.Column(db.DateTime)
    modified_at = db.Column(db.DateTime)

    def get_courses(self):
        content: List[ContractContent] = ContractContent.query.filter(
            ContractContent.contract_id == self.id
        ).all()
        # 返回合同中购买的所有课程的id
        return list(set([c.course_id for c in content if c.course_id]))

    def get_beneficiary(self):
        beneficiary: List[Beneficiary] = Beneficiary.query.filter(
            Beneficiary.contract_id == self.id
        ).all()
        if not beneficiary:
            return []
        return [{"name": b.name, "phone_number": b.phone_number} for b in beneficiary]

    def get_brief(self):
        brief = {
            "id": self.get_hash_id(),
            "signed_at": self.signed_at.strftime("%Y年%m月%d日"),
            "is_valid": self.is_valid,
        }
        beneficiary = self.get_beneficiary()
        brief.update({
            "name": beneficiary[0].get('name'),
            "phone_number": beneficiary[0].get('phone_number'),
            "is_group": self.is_group
        })
        return brief

    def get_page(self):
        page = {
            "signed_at": self.signed_at.strftime("%Y-%m-%d"),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M"),
            "note": self.note,
            "is_valid": self.is_valid,
            "content": [],
            "beneficiary": self.get_beneficiary(),
            "images": self.images
        }
        return page

    @staticmethod
    def get_customer_valid_contract_ids(customer_id):
        # 获取该用户所有正在生效的合同
        beneficiary: List[Beneficiary] = Beneficiary.query.filter(
            Beneficiary.customer_id == customer_id
        ).all()
        contract_ids = [b.contract_id for b in beneficiary]
        contracts: List[Contract] = Contract.query.filter(
            Contract.is_valid == true(),
            Contract.id.in_(contract_ids)
        ).all()
        return [c.id for c in contracts]

    @property
    def customer_ids(self):
        beneficiary: List[Beneficiary] = Beneficiary.query.filter(
            Beneficiary.contract_id == self.id
        ).all()
        return [b.customer_id for b in beneficiary]


class ContractLog(db.Model):
    id = db.Column(db.Integer, index=True, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    contract_id = db.Column(db.Integer, index=True)
    """ 合同id """
    operation = db.Column(db.String)
    """ 操作(新增/删除) """
    staff_id = db.Column(db.Integer)
    """ 操作者的staff_id """
    operated_at = db.Column(db.DateTime)
    """ 操作时间 """


class ClientInfo(db.Model):
    """ 商家初始信息表(销售人员为商家注册时使用) """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    phone_number = db.Column(db.String)
    address = db.Column(db.String)
    note = db.Column(db.String)

    # created_at = db.Column(db.DateTime)
    # modified_at = db.Column(db.DateTime)


class BizStaff(db.Model, Hashable):
    """ biz下面的成员管理 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True, nullable=False)
    biz_user_id = db.Column(db.Integer, db.ForeignKey('biz_user.id'), index=True, nullable=False)
    biz_user: BizUser = db.relationship(BizUser, backref='biz_staff_biz_user')

    roles = db.Column(db.ARRAY(db.String))
    """ biz_user, manager, private_coach """

    permission = db.Column(JSONB)
    permission_list = db.Column(db.ARRAY(db.String))

    name = db.Column(db.String)

    # allow_web_login = db.Column(db.Boolean)
    """ 是否允许网页登录 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-biz_staff')

    def get_name(self):
        if self.name:
            return self.name
        else:
            return self.biz_user.name or self.biz_user.phone_number

    def get_brief(self) -> dict:
        return {
            'id': self.get_hash_id(),
            'name': self.get_name(),
            'phone_number': self.biz_user.phone_number,
            'permission_list': self.permission_list,
            'roles': self.roles,
        }

    @staticmethod
    def phone_find(biz_id, phone_number):
        biz_user: BizUser = BizUser.query.filter(
            BizUser.phone_number == phone_number
        ).first()
        if not biz_user:
            return None
        staff: BizStaff = BizStaff.query.filter(
            BizStaff.biz_id == biz_id,
            BizStaff.biz_user_id == biz_user.id
        ).first()
        if not staff:
            return None
        return staff


class SeatTrigger(db.Model, Hashable):
    """ 为固定时间段来的客户进行提前预约 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer)
    coach_id = db.Column(db.Integer)
    week = db.Column(db.Integer)
    """ 周几 """
    start = db.Column(db.Integer)
    """ 起始时间 """
    end = db.Column(db.Integer)
    """ 结束时间 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-seat_trigger')

    def get_brief(self) -> dict:
        start_hh = int(self.start / 60)
        start_mm = self.start - start_hh * 60
        end_hh = int(self.end / 60)
        end_mm = self.end - end_hh * 60

        return {
            'id': self.get_hash_id(),
            'week': self.get_week_str(),
            'time': '{}:{:02d}-{}:{:02d}'.format(start_hh, start_mm, end_hh, end_mm)
        }

    def get_week_str(self) -> str:
        if self.week == 0:
            week_str = "Sun"
        elif self.week == 1:
            week_str = "Mon"
        elif self.week == 2:
            week_str = "Tue"
        elif self.week == 3:
            week_str = "Wed"
        elif self.week == 4:
            week_str = "Thu"
        elif self.week == 5:
            week_str = "Fri"
        elif self.week == 6:
            week_str = "Sat"
        else:
            week_str = ''
        return week_str


class MonthReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer)
    coach_id = db.Column(db.Integer, index=True)
    yymm = db.Column(db.Integer)
    private_count = db.Column(db.Integer)
    """ 私教学员人数 """
    exp_count = db.Column(db.Integer)
    """ 体验课时数 """
    total_lesson = db.Column(db.Integer)
    """ 总课时 """
    average = db.Column(db.Float)
    """ 日均课时(只算私教课) """
    trainee_ranking = db.Column(db.JSON)
    """ 会员上课排行榜 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    def get_brief(self) -> dict:
        return {
            'trainees_number': self.private_count,
            'total': self.total_lesson,
            'average': self.average,
            'exp': self.exp_count,
        }


class Video(db.Model):
    # TODO feed_id
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    uploaded_by = db.Column(JSONB)
    """ 上传者 """
    # {'role': 'coach', 'object_id': 2} or {'role': 'biz_user': 'object_id': 1}

    file_id = db.Column(db.String, index=True)
    """ 视频的文件id """
    url = db.Column(db.String)
    """ 视频的播放地址 """
    title = db.Column(db.String)
    """ 视频的标题 """
    poster = db.Column(db.String)
    """ 封面 """
    size = db.Column(db.Float)
    """ 视频大小(MB) """
    video_type = db.Column(db.String)
    """ 视频格式(mp4等) """
    height = db.Column(db.Integer)
    """ 高度 """
    width = db.Column(db.Integer)
    """ 宽度 """
    classification_id = db.Column(db.Integer)
    """ 视频分类Id(控制台中分类管理的ID) """
    duration = db.Column(db.Integer)
    """ 视频时长(秒) """
    video_info = db.Column(db.JSON)
    """ 视频信息详情 """
    places = db.Column(db.ARRAY(db.Integer), default=[])
    """ 场地id """
    courses = db.Column(db.ARRAY(db.Integer), default=[])
    """ 课程id """
    coaches = db.Column(db.ARRAY(db.Integer), default=[])
    is_valid = db.Column(db.Boolean, default=True)
    """ 是否有效 """
    tags = db.Column(JSONB)
    """ 标签(不做单个元素的修改,每次修改直接复写该字段) """
    # [{'type': 'coach', 'ids': []}, {'type': 'course', 'ids': []}, {'type': 'place', 'ids': []}]
    code_rate = db.Column(db.Integer)
    """ 码率(视频长度除以大小,向下取整 单位:KB/S) """
    hd_url = db.Column(db.String)
    """ 高清播放地址 """
    fhd_url = db.Column(db.String)
    """ 全高清(超清)播放地址 """
    sd_url = db.Column(db.String)
    """ 标清播放地址 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    def get_brief(self) -> dict:
        return {
            "file_id": self.file_id,
            "url": self.url,
            "title": self.title if self.title else '',
            "poster": self.poster,
            "height": self.height if self.height else 750,  # 防止请求腾讯云保存数据时为空的问题
            "width": self.width if self.width else 750,  # 防止请求腾讯云保存数据时为空的问题
            "duration": self.get_duration(),
            "code_rate": "%d KB/S" % self.code_rate if self.code_rate else 0,
            "hd_url": self.hd_url or "",
            "fhd_url": self.fhd_url or "",
            "sd_url": self.sd_url or ""
        }

    def get_duration(self):
        if not self.duration:
            return "00:00"
        minute = int(self.duration / 60)
        second = self.duration - minute*60
        return '%02d:%02d' % (minute, second)

    # def get_detail(self) -> dict:
    #     """ 获取视频详情 """
    #     detail = json.loads(self.video_info)
    #
    #     return detail

    def get_page(self) -> dict:
        return {
            'title': self.title if self.title else '',
            'poster': self.poster,
            'url': self.url,
            'code_rate': "%d KB/S" % self.code_rate if self.code_rate else 0,
            'hd_url': self.hd_url or "",
            'fhd_url': self.fhd_url or "",
            "sd_url": self.sd_url or ""

        }

    @staticmethod
    def find(file_id):
        video: Video = Video.query.filter(
            Video.file_id == file_id
        ).first()
        return video

    def get_thumb(self):
        thumbs: List[Thumb] = Thumb.query.filter(
            Thumb.video_id == self.id
        ).all()
        if thumbs:
            return {
                'customers': [thumb.customer_id for thumb in thumbs],
                'thumb_count': len(thumbs)
            }
        return {
            'customers': [],
            'thumb_count': 0,
        }


class Place(db.Model, Hashable):
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String)
    """ 场地名称 """
    courses = db.Column(JSONB)
    """ 场地课程 """
    videos = db.Column(db.ARRAY(db.Integer), default=[])
    """ 视频id(列表) """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-place')

    @staticmethod
    def get_biz_places(biz_id) -> list:
        places: List[Place] = Place.query.filter(
            Place.biz_id == biz_id
        ).order_by(desc(Place.created_at)).all()
        return [place.get_name() for place in places]

    def get_name(self) -> dict:
        return {
            'id': self.get_hash_id(),
            'name': self.name
        }

    def get_videos(self) -> list:
        vs = []
        if self.videos:
            videos: List[Video] = Video.query.filter(
                Video.id.in_(self.videos)
            ).all()
            vs.extend(videos)
        vs.sort(key=lambda x: (x.created_at), reverse=True)
        return vs


class Thumb(db.Model):
    """ 点赞记录表 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer, index=True)
    feed_id = db.Column(db.Integer, index=True)
    video_id = db.Column(db.Integer, index=True)

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)


class ReserveEmail(db.Model):
    """ 预约到店邮件表 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String)
    phone_number = db.Column(db.String)
    exp_date = db.Column(db.DateTime)
    exp_time = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    def get_brief(self) -> dict:
        hh = int(self.exp_time / 60)
        mm = self.exp_time - hh * 60
        return {
            'name': self.name,
            'phone_number': self.phone_number,
            'date': self.exp_date.strftime('%-m月%-d日 ') + "%02d:%02d" % (hh, mm)
        }


class Registration(db.Model, Hashable):
    """ 前台登记表(新会员) """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String)
    phone_number = db.Column(db.String)
    mini_salesman_id = db.Column(db.Integer, index=True)
    """ 小程序中绑定的会籍 """
    belong_salesman_name = db.Column(db.String)
    """ 到店后分配的会籍(不一定已经录入在数据库中,因此只保存名字) """
    belong_salesman_id = db.Column(db.Integer, index=True)
    """ 到店后分配的会籍id """
    reservation_date = db.Column(db.DateTime)
    """ 预约日期(如果客户没有预约而是前台直接录入则时间为录入当天) """
    reservation_time = db.Column(db.Integer)
    """ 预约时间(可以为无) """
    is_arrived = db.Column(db.Boolean, default=False)
    """ 是否到店 """
    arrived_at = db.Column(db.DateTime)
    """ 到店时间(日期＋时间) """
    note = db.Column(db.String)
    """ 备注 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-registration')

    def get_brief(self) -> dict:
        brief = {
            'id': self.get_hash_id(),
            'name': self.name,
            'phone_number': self.phone_number,
            'date': self.get_date(),
            'belong_salesman': self.get_belong_salesman(),
            'arrived_at': self.get_arrived_time(),
            'is_arrived': self.is_arrived,
            'reservation_time_str': self.get_reservation_time(),
            'reservation_time': self.reservation_time,
            'note': self.note or '无'
        }

        return brief

    def get_arrived_time(self) -> str:
        if not self.arrived_at:
            return ''
        return self.arrived_at.strftime('%H:%M') + '到店'

    def get_reservation_time(self) -> str:
        if not self.reservation_time or self.reservation_time == "":
            return '无'
        hh = int(self.reservation_time / 60)
        mm = self.reservation_time - hh * 60
        if self.reservation_time > 720:
            return '下午 ' + "%02d:%02d" % (hh, mm)
        return '上午 ' + "%02d:%02d" % (hh, mm)

    def get_date(self) -> str:
        if not self.reservation_date:
            return '无'
        return self.reservation_date.strftime('%Y-%m-%d')

    def get_belong_salesman(self):
        s: Salesman = Salesman.query.filter(
            Salesman.id == self.belong_salesman_id
        ).first()
        if not s:
            return {
                "id": None,
                "name": "无"
            }
        return {
            "id": s.get_hash_id(),
            "name": s.name
        }


class Salesman(db.Model, Hashable):
    """ 会籍人员表 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)

    name = db.Column(db.String)
    """ 姓名 """
    phone_number = db.Column(db.String)
    """ 电话 """
    wechat = db.Column(db.String)
    """ 微信 """
    avatar = db.Column(db.String)
    """ 头像 """
    title = db.Column(db.String)
    """ 头衔 """
    is_official = db.Column(db.Boolean)
    """ 是否是官方会籍 """
    email = db.Column(db.String)
    """ 邮箱(用于发送接待客户的信息) """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-salesman')

    def get_brief(self) -> dict:
        return {
            'id': self.get_hash_id(),
            'avatar': self.avatar,
            'name': self.name,
            'phone_number': self.phone_number,
            'wechat': self.wechat,
            'title': self.title,
            'email': self.email
        }


class ShareType(IntEnum):
    APP = 1     # 转发
    QRCODE = 2      # 小程序码


class Share(db.Model):
    """ 分享, 小程序码, 转发页面 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    type = db.Column(db.Integer)
    """ 1转发, 2小程序码 """

    path = db.Column(db.String)
    """ 页面路径 """
    params = db.Column(db.String)
    """ 参数 """
    page = db.Column(db.String)
    """ 跳转页面 """

    shared_customer_id = db.Column(db.Integer)    # 分享者(用户)
    shared_coach_id = db.Column(db.Integer)    # 分享者(教练)
    shared_salesman_id = db.Column(db.Integer)  # 分享者(会籍)

    created_at = db.Column(db.DateTime, nullable=False)


class ShareVisit(db.Model):
    """ 访问分享页面的记录 """
    id = db.Column(db.Integer, primary_key=True)
    share_id = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False)


class ShareVisitor(db.Model):
    """ 访问分享页面的人次记录 """
    id = db.Column(db.Integer, primary_key=True)
    share_id = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer)
    is_new_comer = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, nullable=False)


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String)
    content = db.Column(db.Text)

    created_at = db.Column(db.DateTime, nullable=False)


class Agent(db.Model, Hashable):
    """ 合伙人 """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    """ 姓名 """
    phone_number = db.Column(db.String)
    """ 手机号码 """
    area = db.Column(db.Integer)
    """ 区域(可以考虑使用地区代号) """
    email = db.Column(db.String)
    """ 邮箱 """

    created_at = db.Column(db.DateTime, nullable=False)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-agent')


class Case(db.Model, Hashable):
    """ 合伙案例 """
    id = db.Column(db.Integer, primary_key=True)
    case_app_id = db.Column(db.String, db.ForeignKey('wx_authorizer.app_id'), index=True, nullable=False)
    case_app: WxAuthorizer = db.relationship(WxAuthorizer, backref='case_app_wx_app')
    image = db.Column(db.String)
    """ 案例宣传图(仅1张) """
    is_show = db.Column(db.Boolean, default=False)
    """ 是否展示在首页 """
    created_at = db.Column(db.DateTime, nullable=False)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-case')


class Question(db.Model, Hashable):
    """ 常见问题 """
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String)
    """ 问题的内容 """
    answer = db.Column(db.Text)
    """ 答案 """
    question_type = db.Column(db.String)
    """ 问题分类 """
    is_common = db.Column(db.Boolean, default=False)
    """ 是否是常见问题 """
    created_at = db.Column(db.DateTime, nullable=False)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-question')


class Coupon(db.Model, Hashable):
    """ 优惠券(每个商家可以自定义自己的券) """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String)
    """ 优惠券的名字 """
    validity_period = db.Column(db.Integer, default=30)
    """ 有效期(7/15/30天) """
    description = db.Column(db.String)
    """ 描述 """
    switch = db.Column(db.Boolean, default=True)
    """ 开关 """
    effective_at = db.Column(db.DateTime)
    """ 生效日期 """
    expire_at = db.Column(db.DateTime)
    """ 失效日期 """
    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-coupon')

    def get_validity_period(self) -> int:
        # 目前只有7\15\30天可以让用户选择,若不选择则默认30天
        if not self.validity_period:
            self.validity_period = 30

        return self.validity_period

    def get_brief(self) -> dict:
        return {
            'id': self.get_hash_id(),
            'name': self.name,
            'switch': self.switch,
            'description': self.description,
            'validity_period': self.get_validity_period(),  # TODO 新版的优惠券上线并完成数据迁移后该字段可以废弃
            'effective_at': self.effective_at.strftime('%Y-%m-%d') if self.effective_at else '',
            'expire_at': self.expire_at.strftime('%Y-%m-%d') if self.expire_at else ''
        }

    @staticmethod
    def get_all_coupons(biz_id) -> list:
        coupons: List[Coupon] = Coupon.query.filter(
            Coupon.biz_id == biz_id,
            Coupon.switch == true()
        ).all()
        return coupons


class CouponReport(db.Model):
    """ 优惠券领取及使用详情 """
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, index=True)
    """ 用户id """
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), index=True, nullable=False)
    """ 优惠劵id """
    coupon: Coupon = db.relationship(Coupon, backref='coupon_report_coupon')
    """ 优惠劵对象 """
    salesman_id = db.Column(db.Integer, index=True)
    """ 会籍id """
    expire_at = db.Column(db.DateTime, nullable=False)
    """ 过期时间 """
    effective_at = db.Column(db.DateTime)
    """ 生效日期 """
    is_used = db.Column(db.Boolean, default=False)
    """ 是否使用过(过期视为使用过) """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    def get_brief(self) -> dict:
        expire_at = self.expire_at.strftime('%Y-%m-%d')
        is_used = self.is_used
        brief = self.coupon.get_brief()
        brief.update({'validity_period': expire_at})
        brief.update({'is_used': is_used})
        return brief


# class PosterTemplate(db.Model, Hashable):
#     id = db.Column(db.Integer, primary_key=True)
#     url = db.Column(db.String)
#     content = db.Column(db.ARRAY(db.String))
#
#     created_at = db.Column(db.DateTime, nullable=False)
#     modified_at = db.Column(db.DateTime)
#     hash_ids = Hashids(salt=cfg['hashids_salt'] + '-poster_template')
#
#     def get_brief(self) -> dict:
#         return {
#             "id": self.get_hash_id(),
#             "url": self.url,
#             "content": self.content
#         }


class ActivityStatus(IntEnum):
    """ 活动的状态 """
    READY = 0  # 未开始(即将开始)
    ACTION = 1  # 进行中
    END = -1  # 已结束
    CLOSE = -2  # 已关闭(商家手动关闭)


class GroupStatus(IntEnum):
    """ 团的状态 """
    FAIL = -1  # 成团失败
    STANDBY = 0  # 待成团(已开团)
    SUCCESS = 1  # 成团成功
    COMPLETED = 2  # 活动完成(成团后,团的生命周期结束时为此状态)


class OrderStatus(IntEnum):
    """ 订单状态 """
    # TODO
    DEFAULT = 0


class CommodityType:
    # 货物类别
    Goods = 'goods'
    Course = 'course'
    All = [Goods, Course]


class EventType:
    # 新增活动类别时在此添加
    Group = 'group'  # 拼团活动
    All = [Group]


class Activity(db.Model, Hashable):
    """ 商家录入的活动 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String)
    """ 标题 """
    start_date = db.Column(db.DateTime, nullable=False)
    """ 活动开始的时间 """
    end_date = db.Column(db.DateTime)
    """ 活动结束的时间 """
    rules = db.Column(JSONB)
    """ 优惠规则 """
    join_price = db.Column(db.Float, default=0)
    """ 参团价格(为0即免费参团) """
    status = db.Column(db.Integer)
    """ 该活动的状态(ActivityStatus中的状态) """
    cover_image = db.Column(db.String)
    """ 封面图(用于拼团列表页) """
    event_type = db.Column(db.String, index=True, nullable=False)
    """ 活动类别 """
    private_parameter = db.Column(JSONB)
    """ 私有参数(不同的活动类型的私有参数不一致,使用json来保存,并在接口中进行校验) """
    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-group_active')

    def get_brief(self) -> dict:
        brief = {
            "id": self.get_hash_id(),
            "name": self.name,
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "end_date": self.end_date.strftime("%Y-%m-%d"),
            "status": self.status,
            "cover_image": self.cover_image,
            "size": self.get_size(),
            "time_limit": self.get_limit_time(),
            "rules": self.rules,
            "private_parameter": self.private_parameter
        }

        return brief

    def get_limit_time(self) -> dict:
        limit_time = self.private_parameter.get('limit_time')

        if limit_time >= 1440:
            dd = limit_time // 1440
            hh = (limit_time - 1440*dd) // 60
            mm = limit_time - 1440*dd - hh*60
            return {
                "day": dd,
                "hour": hh,
                "minutes": mm,
            }
        else:
            hh = limit_time // 60
            mm = limit_time - hh * 60
            return {
                "day": None,
                "hour": hh,
                "minutes": mm,
            }

    def get_size(self) -> dict:
        min_size = self.private_parameter.get('min_size')
        max_size = self.private_parameter.get('max_size')
        if not (min_size and max_size):
            return {}
        return {
            "min_size": min_size,
            "max_size": max_size,
        }

    def get_mini_brief(self) -> dict:
        join_count = self.get_join_count()
        brief = {
            "id": self.get_hash_id(),
            "title": self.name,
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "end_date": self.end_date.strftime("%Y-%m-%d"),
            "rules": self.rules,
            "join_count": join_count,
            "cover_image": self.cover_image,
            "type": self.private_parameter.get('type')
        }
        commodity_type = self.private_parameter.get('type')
        commodity_id = self.private_parameter.get('id')
        if commodity_type == CommodityType.Goods:
            goods: Goods = Goods.find(commodity_id)
            if not goods:
                brief.update({
                    'images': [],
                    'price': '',
                    'description': ''
                })
            brief.update({
                'images': goods.images,
                'price': goods.price,
                'description': goods.description
            })
        elif commodity_type == CommodityType.Course:
            course: Course = Course.find(commodity_id)
            if not course:
                brief.update({
                    'images': [],
                    'price': '',
                    'description': ''
                })
            description = ''
            for content in course.content:
                if content.get('title') == '课程介绍':
                    description = content.get('text')

            brief.update({
                'images': course.images,
                'price': self.private_parameter.get('price'),
                'description': description
            })
        return brief

    def get_group_reports(self, first_status, end_status) -> list:
        group_reports: List[GroupReport] = GroupReport.query.filter(
            GroupReport.biz_id == self.biz_id,
            GroupReport.activity_id == self.id,
            GroupReport.status >= first_status,
            GroupReport.status <= end_status,
        ).all()
        return group_reports

    def get_join_count(self) -> int:
        group_reports = self.get_group_reports(GroupStatus.STANDBY.value, GroupStatus.SUCCESS.value)
        join_count = 0
        for group_report in group_reports:
            join_count += group_report.members_count
        return join_count


class Goods(db.Model, Hashable):
    """ 商品信息表 """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String)
    """ 商品名 """
    price = db.Column(db.Float)
    """ 价格 """
    description = db.Column(db.String)
    """ 描述 """
    images = db.Column(JSONB)
    """ 商品图片 """
    # type = db.Column(db.String)
    # """ 商品类别 """
    stock = db.Column(db.Integer)
    """ 库存 """
    is_shelf = db.Column(db.Boolean, default=True)
    """ 是否上架(删除商品时不删除数据,只修改此字段) """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-goods')

    def get_brief(self) -> dict:
        return {
            'id': self.get_hash_id(),
            'name': self.name,
            'price': self.price,
            'description': self.description,
            'images': self.images if self.images else [],
            'stock': self.stock,
            'is_shelf': self.is_shelf
        }


class GroupReport(db.Model, Hashable):
    """ 拼团信息表(开团的时候会创建一条记录) """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    leader_cid = db.Column(db.Integer, index=True)
    """ 团长的customer_id(目前主要是会籍的c_id) """
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), index=True, nullable=False)
    """ 拼团的id """
    activity: Activity = db.relationship(Activity, backref='group_report_activity')
    """ 活动对象 """
    status = db.Column(db.Integer, default=GroupStatus.STANDBY.value)
    """ 该拼团的状态(开团时默认为待成团) """
    closed_at = db.Column(db.DateTime, nullable=False)
    """ 关团时间 """
    success_at = db.Column(db.DateTime)
    """ 成团时间 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-group_leader')

    def get_brief(self) -> dict:
        brief = {
            "id": self.get_hash_id(),
            "title": self.activity.name,
            "closed_at": int((time.mktime(self.closed_at.timetuple()) + self.closed_at.microsecond / 1E6) * 1000),
            "status": self.status,
            "members_count": self.members_count,
            "first_member": {},
            "group_members": [],
            "cover_image": self.activity.cover_image,
            "rules": self.activity.rules,
            "created_at": self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
        group_members = self.group_members
        size = self.activity.get_size()
        if group_members:
            brief.update({
                "first_member": group_members[-1],
                "group_members": group_members
            })
        if size:
            lack_count = size.get('min_size') - self.members_count
            if lack_count <= 0:
                lack_count = 0
            brief.update({
                "lack_count": lack_count,
                "min_size": size.get('min_size'),
                "max_size": size.get('max_size')
            })

        return brief

    @property
    def group_members(self) -> list:
        # 获取该团的参团人员信息
        res = []
        group_members: List[GroupMember] = GroupMember.query.filter(
            GroupMember.biz_id == self.biz_id,
            GroupMember.group_report_id == self.id
        ).order_by(desc(GroupMember.created_at)).all()
        # 按照参团的先后顺序抓取
        from store.domain.cache import CustomerCache
        for group_member in group_members:
            c_cache = CustomerCache(group_member.customer_id)
            nick_name, avatar, phone_number = c_cache.get('nick_name', 'avatar', 'phone_number')
            res.append({
                'c_id': group_member.customer_id,
                'nick_name': nick_name,
                'avatar': avatar,
                'phone_number': phone_number,
                'join_date': group_member.created_at.strftime('%Y-%m-%d'),
                'created_at': group_member.created_at.strftime('%Y-%m-%d %H:%M')  # 用于排序
            })
        return res

    @property
    def members_count(self) -> int:
        group_members_count = db.session.query(func.count(GroupMember.customer_id)).filter(
            GroupMember.biz_id == self.biz_id,
            GroupMember.group_report_id == self.id
        ).scalar()

        return group_members_count


class GroupMember(db.Model, Hashable):
    """ 参团成员表(会员点击参团时生成一条记录) """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer, index=True)
    """ 成员的c_id """
    group_report_id = db.Column(db.Integer, db.ForeignKey('group_report.id'), index=True, nullable=False)
    """ 参团的id """
    group_report: GroupReport = db.relationship(GroupReport, backref='group_member_group_leader')
    """ 拼团信息 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-group_member')


class PlanStatus(IntEnum):
    READY = 0  # 未开始
    ACTION = 1  # 进行中
    FINISH = -1  # 已结束


class Plan(db.Model, Hashable):
    """ 健身计划(将会员的训练成果数据化) """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer, index=True)
    demand = db.Column(db.ARRAY(db.String), default=[])
    """ 会员需求(根据体侧结果或会员口述进行填写)(完成版本迁移后删除该字段) """
    title = db.Column(db.String)
    """ 阶段名称 """
    purpose = db.Column(db.String)
    """ 目的 """
    key_data = db.Column(JSONB)
    """ 关键指标(预期目标,使用进度条来表示, 为空时告知用户填写,不显示进度条) """
    # [
    #     {
    #         'name': '体重',  # KeyDataType中的字段
    #         'target': '85.0',  # 预期目标
    #         'initial_data': '75.5',  # 创建计划时的数值
    #         'unit': 'kg'  # 单位
    #     },
    #     {
    #         'name': '体脂肪率',
    #         'target': None,  # 允许为空
    #         'initial_data': None,  # 允许为空
    #         'unit': '无'
    #     },
    # ]
    suggestion = db.Column(db.String)
    """ 训练建议(饮食方案\睡眠作息等, 教练填写) """
    result = db.Column(JSONB)
    """ 训练成果(计划结束时填写) """
    note = db.Column(db.String)
    """ 备注(会员填写)(完成版本迁移后删除该字段) """
    effective_at = db.Column(db.DateTime)
    """ 生效日期 """
    closed_at = db.Column(db.DateTime)
    """ 结束日期(完成版本迁移后删除该字段) """
    duration = db.Column(db.Integer)
    """ 计划时长 """
    status = db.Column(db.Integer, default=0)
    """ 状态 """
    finished_at = db.Column(db.DateTime)
    """ 结束日期 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-plan')

    def get_brief(self) -> dict:
        today = datetime.today()
        return {
            'id': self.get_hash_id(),
            'title': self.title,
            'purpose': self.purpose,
            'duration': self.duration,
            'past': (today - self.effective_at).days + 1 if self.effective_at else 0,
            'suggestion': self.suggestion,
            'key_data': self.get_key_data(),
            'status': self.status,
            'finished_at': self.finished_at.strftime('%Y-%m-%d') if self.finished_at else None,
            'effective_at': self.effective_at.strftime('%Y-%m-%d') if self.finished_at else None,
            'created_at': self.created_at.strftime('%Y-%m-%d'),
            'result': self.result if self.result else []
        }

    def get_key_data(self):
        return self.key_data or []

    @staticmethod
    def get_effective_plan(customer_id):
        plan: Plan = Plan.query.filter(
            Plan.customer_id == customer_id,
            Plan.status == PlanStatus.ACTION.value
        ).first()
        return plan


class Diary(db.Model, Hashable):
    """ 日记(一天一条) """
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer, index=True)

    recorded_at = db.Column(db.DateTime)
    """ 记录时间(以天为单位) """
    coach_note = db.Column(JSONB, default=[])
    """ 教练评语(记录) """
    customer_note = db.Column(db.String)
    """ 本人评语(记录) """
    check_in_data = db.Column(JSONB)
    """ 打卡数据(打卡时间\排名\次数等) """
    images = db.Column(JSONB)
    """ 用户上传的图片 """
    body_data = db.Column(JSONB, default=[])
    """ 当天的体测数据(同类数据只取最新的值) """
    """
    [{
        'name': '体重',
        'data': '70.1',
        'unit': 'kg'
      },
    {
        'name': '身高',
        'data': '170.1',
        'unit': 'cm'
      }]
    """
    primary_mg = db.Column(db.ARRAY(db.String))
    """ 主练肌肉 """
    secondary_mg = db.Column(db.ARRAY(db.String))
    """ 副练肌肉 """
    training_type = db.Column(db.ARRAY(db.String))
    """ 训练类型 """
    workout = db.Column(JSONB)
    """ 动作记录 """
    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-diary')

    __table_args__ = (
        UniqueConstraint('customer_id', 'recorded_at', name='_diary_customer_id_recorded_at'),
    )

    def get_brief(self, trainee_id=None) -> dict:
        return {
            'id': self.get_hash_id(),
            'customer_note': self.customer_note,
            'coach_note': self.coach_note,
            'check_in_data': self.check_in_data,  # TODO ?
            'images': self.get_image(),
            'body_data': self.get_body_data(),
            'primary_mg': self.primary_mg or [],
            'training_type': self.get_training_type(trainee_id),
            'date': self.recorded_at.strftime('%m.%d')
        }

    def get_body_data(self):
        plan: Plan = Plan.query.filter(
            Plan.customer_id == self.customer_id,
            Plan.status == PlanStatus.ACTION.value
        ).first()
        if not plan:
            return self.body_data

        body_data = self.body_data
        # 获取正在生效的计划, 比对关键指标
        p_key_data = plan.get_key_data()
        if not p_key_data:
            return self.body_data
        for key_data in p_key_data:
            for b_data in body_data:
                if key_data.get('name') == b_data.get('name'):
                    # 数据类型与关键指标一致时,增加起始与目标值
                    b_data.update({
                        'target': key_data.get('target'),  # 预期目标
                        'initial_data': key_data.get('initial_data'),
                    })

        return body_data

    def get_image(self):
        if not self.images:
            return []
        images: List[DiaryImage] = DiaryImage.query.filter(
            DiaryImage.customer_id == self.customer_id,
            DiaryImage.image.in_(self.images)
        ).all()
        res = [{'image': i.image, 'id': i.get_hash_id()} for i in images]
        return res

    def get_training_type(self, trainee_id=None):
        if not self.training_type:
            return []
        if trainee_id:
            # 教练端(蓝色icon)
            training_type = get_res(directory='training_type', file_name='training_type.yml').get('c_training_type')
        else:
            # 客户端(绿色icon)
            training_type = get_res(directory='training_type', file_name='training_type.yml').get('training_type')
        res = []
        for st in self.training_type:
            for t in training_type:
                if st == t.get('title'):
                    res.append({
                        'title': st,
                        'icon': t.get('icon'),
                    })
        return res

    def get_coach_note(self, coach_id):
        if not self.coach_note:
            return {}
        for note in self.coach_note:
            if note.get('coach_id') == coach_id:
                return note
        return {}


class DiaryImage(db.Model, Hashable):
    """ 健身相册 """
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, index=True)
    image = db.Column(db.String)
    diary_id = db.Column(db.Integer, index=True)
    created_at = db.Column(db.DateTime, nullable=False)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-diary_image')
    __table_args__ = (
        UniqueConstraint('id', 'diary_id', name='_image_id_diary_id'),
    )


class Order(db.Model, Hashable):
    # TODO
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    flow_code = db.Column(db.String, index=True, nullable=False)
    """ 流水号 """
    status = db.Column(db.Integer, index=True, default=OrderStatus.DEFAULT)
    """ 订单状态 """
    customer_id = db.Column(db.Integer, index=True)
    """ 客户 """
    goods_price = db.Column(db.Float)
    """ 商品价格 """
    goods_id = db.Column(db.Integer, index=True)
    """ 商品id """
    amount = db.Column(db.Float)
    """ 交易金额(用户实际支付金额) """
    note = db.Column(db.String)
    """ 备注 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-order')


class BodyData(db.Model):
    """ 体测数据 """
    # 每次操作都新增一条记录
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    customer_id = db.Column(db.Integer, index=True)
    record_type = db.Column(db.String)
    """ 数据类别 """
    data = db.Column(db.String)
    """ 数据 """
    recorded_at = db.Column(db.DateTime)
    """ 记录日期 """

    @staticmethod
    def get_all_record(c_id, d_type: str):
        # 获取体测数据纪录
        record: List[BodyData] = BodyData.query.filter(
            BodyData.customer_id == c_id,
            BodyData.record_type == d_type,
        ).order_by(asc(BodyData.recorded_at)).all()
        res = [{d_type: r.data, 'date': r.recorded_at.strftime('%Y-%m-%d %H:%M:%S')} for r in record]
        return res

    @staticmethod
    def get_record(c_id, d_type: str) -> list:
        # 获取最新的7次体测数据纪录
        record: List[BodyData] = BodyData.query.filter(
            BodyData.customer_id == c_id,
            BodyData.record_type == d_type,
        ).order_by(asc(BodyData.recorded_at)).all()
        res = [{d_type: r.data, 'date': r.recorded_at.strftime('%Y-%m-%d %H:%M:%S')} for r in record]
        return res[-7:]

    @staticmethod
    def get_last_record(c_id, d_type):
        # 获取最近一次的体测数据
        record: BodyData = BodyData.query.filter(
            BodyData.record_type == d_type,
            BodyData.customer_id == c_id,
        ).order_by(desc(BodyData.recorded_at)).first()
        if not record:
            return None
        return record.data

    @staticmethod
    def get_last_record_object(c_id, d_type):
        record: BodyData = BodyData.query.filter(
            BodyData.record_type == d_type,
            BodyData.customer_id == c_id,
        ).order_by(desc(BodyData.recorded_at)).first()
        if not record:
            return None
        return {
            d_type: record.data,
            'date': record.recorded_at.strftime('%Y-%m-%d %H:%M:%S')
        }

    @staticmethod
    def get_record_change(c_id, start_date, end_date, d_type):
        # 获取某类数据在某段时间内的变化的绝对值
        records: List[BodyData] = BodyData.query.filter(
            BodyData.record_type == d_type,
            BodyData.customer_id == c_id,
            BodyData.recorded_at >= start_date,
            BodyData.recorded_at <= end_date,
        ).order_by(desc(BodyData.recorded_at)).all()
        if not records:
            return 0
        res = round(float(records[-1].data), 1) - round(float(records[0].data), 1)
        return abs(res)

    @staticmethod
    def get_all_type_record(customer_id):
        records: List[BodyData] = BodyData.query.filter(
            BodyData.customer_id == customer_id
        ).order_by(asc(BodyData.recorded_at)).all()

        all_type = []
        for r in records:
            if r.record_type not in all_type:
                all_type.append(r.record_type)

        res = {}
        for r_type in all_type:
            t_records = [r for r in records if r.record_type == r_type]
            t_res = [{r_type: r.data, 'date': r.recorded_at.strftime('%Y-%m-%d %H:%M:%S')} for r in t_records]
            res.update({
                r_type: t_res[-7:] if t_res else None,
                'first_record': t_res[0] if t_records else None
            })

        return res

    @staticmethod
    def get_first_record(customer_id, d_type):
        # 获取最初的数据
        record: BodyData = BodyData.query.filter(
            BodyData.customer_id == customer_id,
            BodyData.record_type == d_type
        ).order_by(asc(BodyData.recorded_at)).first()
        if not record:
            return 0
        return record.data


mg_map = {
    'abs': '腹肌',
    'ankles': '脚踝',
    'biceps': '肱二头肌',
    'calves': '小腿肌群',
    'chest': '胸肌',
    'forearms': '前臂',
    'glutes-hip-flexors': '臀部肌群',
    'hamstrings': '大腿后侧肌',
    'knees': '膝关节',
    'lower-back': '下背肌',
    'middle-back-lats': '背阔肌',
    'neck-upper-traps': '颈部肌群',
    'obliques': '侧腹肌',
    'quadriceps': '股四头肌',
    'shoulders': '肩部',
    'spine': '脊柱',
    'triceps': '肱三头肌',
    'upper-back-lower-traps': '上背肌',
    'wrists': '手腕'
}


class Gender(IntEnum):
    """ 性别 0：未知、1：男、2：女  """
    MALE = 1
    FEMALE = 2
    UNKNOWN = 0


class Ex(db.Model, Hashable):
    """ 动作表 """
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-ex')

    id = db.Column(db.Integer, primary_key=True)
    is_official = db.Column(db.Boolean)

    name_en = db.Column(db.String)
    full_name = db.Column(db.String, unique=True)

    title = db.Column(db.String, nullable=False)
    # subtitle = db.Column(db.String)

    pictures = db.Column(JSONB)
    primary_mg = db.Column(db.ARRAY(db.String))
    secondary_mg = db.Column(db.ARRAY(db.String))

    describe = db.Column(JSONB)
    """ 文字介绍 """

    related_exs = db.Column(JSONB)
    """ 相关动作 """

    record_method = db.Column(db.String, nullable=False)
    """ 每组动作的默认记录方式, 暂时先设置为不可更新. 更新比较麻烦 """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)


class ExProperty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ex_id = db.Column(db.Integer, index=True)
    ex_title = db.Column(db.String, index=True)
    customer_id = db.Column(db.Integer, index=True, nullable=False)

    record_method = db.Column(db.String)
    unit = db.Column(db.String)

    last_recorded_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint('ex_id', 'ex_title', 'customer_id', name='_ex_property_ex'),
    )


class OperationLog(db.Model):
    """ 操作日志 """
    # [2018年12月06日 15:33:32] 教练主管：李志昂 修改了 苏家小妖的体测数据
    # [operated_at] {operator} {operation}了 {operating_object}的{content}
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    operator_id = db.Column(db.Integer, index=True)
    """ 操作者的wx_open_id """
    operating_object_id = db.Column(db.Integer, index=True)
    """ 操作对象的customer_id """
    operation = db.Column(db.String)
    """ 执行的操作 """
    content = db.Column(db.String)
    """ 操作的内容 """
    operated_at = db.Column(db.DateTime, nullable=False)
    """ 操作时间 """


class ExHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ex_id = db.Column(db.Integer, index=True)
    ex_title = db.Column(db.String, index=True)
    customer_id = db.Column(db.Integer, index=True, nullable=False)

    diary_id = db.Column(db.Integer)
    diary_date = db.Column(db.DateTime, nullable=False)

    sets = db.Column(JSONB)
    work = db.Column(db.Float)

    note = db.Column(db.String)

    recorded_at = db.Column(db.DateTime, nullable=False, index=True)
    """ 记录时间 """
    created_at = db.Column(db.DateTime, nullable=False)


class WorkReport(db.Model, Hashable):
    """ 工作报告 """
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-work_report')
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    staff_id = db.Column(db.Integer, index=True)
    """ 提交报告的staff """
    customer_id = db.Column(db.Integer, index=True)
    """ 报告的customer_id """
    content = db.Column(JSONB)
    """ 报告的内容(目前只有当日的健身日记) """
    departments = db.Column(db.ARRAY(db.Integer))
    """ 所属部门(可多个) """
    # {"customer_note": "xx", "coach_notes": [{"avatar":"xx", "note": "xx"}], "primary_mg": [],
    # "training_type": [], "body_data": [], "images": [], "seat_tip": [], "work_out": [], ...}
    submitted_at = db.Column(db.DateTime)
    """ 提交时间 """
    name = db.Column(db.String)
    """ 报告对象的名字 """
    viewers = db.Column(db.ARRAY(db.Integer), default=[])
    """ 浏览者的id(用于区别已阅) """
    yymmdd = db.Column(db.Integer)
    """ 提交日期(用于做唯一约束) """

    created_at = db.Column(db.DateTime, nullable=False)
    modified_at = db.Column(db.DateTime)

    __table_args__ = (
        UniqueConstraint('id', 'staff_id', 'customer_id', 'yymmdd', name='_wr_id_s_id_cs_id_ymd'),
    )

    @staticmethod
    def get_message_count(staff_id, viewer_id, yymmdd):
        messages: List[WorkReport] = WorkReport.query.filter(
            WorkReport.staff_id == staff_id,
            WorkReport.yymmdd == yymmdd,
        ).order_by(desc(WorkReport.submitted_at)).all()

        unread = 0
        total = len(messages)
        if not messages:
            latest_time = datetime.now()
        else:
            latest_time = messages[0].submitted_at
            for message in messages:
                if not message.viewers:
                    unread += 1
                elif viewer_id not in message.viewers:
                    unread += 1

        return {
            "unread": unread,
            "total": total,
            "latest_time": latest_time,
        }

    @staticmethod
    def get_viewer(staff_id, customer_id, yymmdd):
        work_report: WorkReport = WorkReport.query.filter(
            WorkReport.staff_id == staff_id,
            WorkReport.customer_id == customer_id,
            WorkReport.yymmdd == yymmdd
        ).first()
        if not work_report:
            return []
        if not work_report.viewers:
            return []

        return work_report.viewers


class Department(db.Model, Hashable):
    hash_ids = Hashids(salt=cfg['hashids_salt'] + '-department')
    id = db.Column(db.Integer, primary_key=True)
    biz_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String)
    """ 部门名称 """
    parent_id = db.Column(db.Integer, default=0)
    """ 父部门id(0表示没有父部门) """
    leader_sid = db.Column(db.Integer, index=True)
    """ 主管的biz_staff_id """
    members = db.Column(db.ARRAY(db.Integer))
    """ 组员 """
    is_root = db.Column(db.Boolean, default=False)
    """ 是否是根部门(该部门下成员可拥有几乎等同于管理员的权限) """
    created_at = db.Column(db.DateTime)
    modified_at = db.Column(db.DateTime)

    def get_children(self):
        # 获取所有子部门
        children: List[Department] = Department.query.filter(
            Department.parent_id == self.id
        ).order_by(desc(Department.created_at)).all()
        return children

    def get_children_ids(self) -> list:
        children = self.get_children()
        children_ids = [c.id for c in children]
        return children_ids

    @property
    def parent(self):
        parent: Department = Department.query.filter(
            Department.id == self.parent_id
        ).first()
        return parent or []

    @property
    def staff_ids(self):
        member = self.members
        staff_ids = [self.leader_sid]
        for m in member:
            staff_ids.append(m)
        return staff_ids

    @staticmethod
    def get_root_id(biz_id):
        root: Department = Department.get_root(biz_id)
        if not root:
            return 0
        return root.id

    @staticmethod
    def get_root(biz_id):
        root: Department = Department.query.filter(
            Department.biz_id == biz_id,
            Department.is_root == true()
        ).first()
        return root
