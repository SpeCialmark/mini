from store.cache import (BaseCache, token_redis_store, store_biz_redis_store, coach_redis_store,
                         wx_open_user_redis_store, app_redis_store, course_redis_store, trainee_redis_store,
                         customer_redis_store, biz_user_redis_store, auth_link_redis_store, group_courses_redis_store,
                         place_redis_store, audit_redis_store, video_limit_store, video_history_store, salesman_store,
                         check_in_redis_store, coupon_customer_redis_store, customer_unread_redis_store,
                         group_reports_redis_store, user_group_reports_redis_store, diary_unread_redis_store,
                         ex_redis_store, department_redis_store, staff_redis_store, seat_check_redis_store,
                         seat_code_redis_store)
from sqlalchemy import and_, desc, asc, true, or_
import json
from datetime import datetime
from store.utils.token import generate_token
from .models import Store, Course, Coach, Trainee, Customer, WxAuthorizer, BizUser, WxMsgTemplate, AppMark, \
    WxOpenUser, BizStaff, StoreBiz, GroupTime, GroupCourse, Place, Salesman, CheckIn, Coupon, Goods, Activity, \
    GroupReport, GroupMember, Diary, Ex, Department
from typing import List
from store.config import cfg
from store.domain.role import CustomerRole, CoachRole, ManagerRole, BizUserRole, StaffRole
from store.database import db
from store.domain.msg_template import binding_template, reservation_template, cancel_template, confirm_template, \
    group_success_template, group_fail_template, customer_seat_check_template, coach_seat_check_template
from store.domain.permission import get_permission, ViewBizPermission, ViewBizWebPermission, EditStorePermission, \
    ManagePrivateCoachPermission, EditPrivateCoachPermission, ManagePublicCoachPermission, \
    ManageGroupCoursePermission, ManageFeedPermission, DeployPermission, EditCoachItemPermission, ReservationPermission, \
    get_permissions_name, ManagePlacePermission, ManageSalesmanPermission, UploadVideoPermission, \
    ManageRegistrationPermission

from store.utils import time_processing as tp


class WxOpenUserNotFoundException(Exception):
    pass


class BizUserNotFoundException(Exception):
    pass


def get_default_customer_permission(biz_id) -> set:
    res = set()
    res.add(ViewBizPermission(biz_id=biz_id).to_tuple())
    res.add(ReservationPermission(biz_id=biz_id).to_tuple())
    return res


def get_default_coach_permission(biz_id, coach_id) -> set:
    """ 默认权限 """
    # 教练的默认权限
    res = set()
    res.add(ViewBizPermission(biz_id=biz_id).to_tuple())  # 查看门店权限
    res.add(ViewBizWebPermission(biz_id=biz_id).to_tuple())  # 查看网页端权限
    res.add(EditCoachItemPermission(biz_id=biz_id, object_id=coach_id).to_tuple())  # 编辑个人资料权限
    res.add(ManageFeedPermission(biz_id=biz_id).to_tuple())  # 管理动态权限(视频功能上线后动态管理成为教练的基本权限)
    res.add(UploadVideoPermission(biz_id=biz_id).to_tuple())  # 上传视频权限

    return res


def get_default_staff_permission(biz_id) -> set:
    # staff默认拥有浏览权限
    res = set()
    res.add(ViewBizPermission(biz_id=biz_id).to_tuple())
    res.add(ViewBizWebPermission(biz_id=biz_id).to_tuple())
    return res


def get_coach_permission(biz_id, coach_id) -> set:
    res = set()
    coach: Coach = Coach.query.filter(
        Coach.id == coach_id
    ).first()
    if not coach.permission_list:
        permission_set = get_default_coach_permission(biz_id, coach_id)
        coach.permission_list = get_permissions_name(permission_set)
        db.session.commit()
        db.session.refresh(coach)
        return permission_set

    for p in coach.permission_list:
        permission = get_permission(p, biz_id)
        if permission:
            if permission.name == EditCoachItemPermission.name:
                # 教练编辑自己的资料需要coach_id
                permission.object_id = coach_id
            res.add(permission.to_tuple())

    return res


def get_manager_permission(biz_id) -> set:
    """ 管理员拥有对该biz所有的权限 """
    res = set()
    res.add(ViewBizPermission(biz_id=biz_id).to_tuple())
    res.add(ViewBizWebPermission(biz_id=biz_id).to_tuple())
    res.add(EditStorePermission(biz_id=biz_id).to_tuple())
    res.add(ManagePrivateCoachPermission(biz_id=biz_id).to_tuple())
    res.add(EditPrivateCoachPermission(biz_id=biz_id).to_tuple())
    res.add(ManagePublicCoachPermission(biz_id=biz_id).to_tuple())
    res.add(ManageGroupCoursePermission(biz_id=biz_id).to_tuple())
    res.add(ManageFeedPermission(biz_id=biz_id).to_tuple())
    res.add(DeployPermission(biz_id=biz_id).to_tuple())
    res.add(ReservationPermission(biz_id=biz_id).to_tuple())
    res.add(ManagePlacePermission(biz_id=biz_id).to_tuple())
    res.add(ManageSalesmanPermission(biz_id=biz_id).to_tuple())
    res.add(UploadVideoPermission(biz_id=biz_id).to_tuple())
    res.add(ManageRegistrationPermission(biz_id=biz_id).to_tuple())
    return res


def get_staff_permission(staff: BizStaff) -> set:
    res = set()
    # for r in staff.roles:
    #     if r == CoachRole.role:
    #         res.update()
    # TODO

    for p in staff.permission_list:
        permission = get_permission(p, biz_id=staff.biz_id)
        # TODO 处理item类型
        if permission:
            res.add(permission.to_tuple())
    return res


def get_staff_permission_from_id(staff_id) -> set:
    res = set()
    staff: BizStaff = BizStaff.query.filter(
        BizStaff.id == staff_id
    ).first()
    if not staff:
        return res
    return get_staff_permission(staff)


class TokenCache(BaseCache):
    redis_store = token_redis_store
    expire_seconds = cfg['redis_expire']['token']
    type_dict = {
        'app_id': 'str',
        'open_id': 'str',
        'website': 'str',
        'phone_number': 'str',
        'admin_role': 'json'
    }

    def __init__(self, token: str):
        self.id = token

    def reload(self):
        pass


class WxOpenUserCache(BaseCache):
    redis_store = wx_open_user_redis_store
    expire_seconds = cfg['redis_expire']['token'] * 2
    type_dict = {
        'biz_id': 'int',
        'w_id': 'int',
        'token': 'str',
        'role': 'json',
        'client_role': 'str',
        'permission': 'json',
    }

    def __init__(self, app_id: str, open_id: str):
        self.app_id = app_id
        self.open_id = open_id
        self.id = str(app_id) + '-' + str(open_id)

        app_cache = AppCache(app_id=self.app_id)
        biz_id = app_cache.get('biz_id')
        self.biz_id = biz_id

    def reload(self):
        w_user: WxOpenUser = WxOpenUser.query.filter(and_(
            WxOpenUser.wx_open_id == self.open_id,
            WxOpenUser.app_id == self.app_id
        )).first()
        if not w_user:
            raise WxOpenUserNotFoundException()

        if w_user.login_biz_id:
            self.biz_id = w_user.login_biz_id
        if not self.biz_id:
            raise KeyError('biz_id not set')

        g_role, permission = self.get_role_and_permission(w_user)
        k_v = {
            'biz_id': self.biz_id,
            'w_id': w_user.id,
            'token': w_user.token,
            'role': json.dumps(g_role),
            'client_role': w_user.role,
            'permission': json.dumps(list(permission)),

        }
        self.set(k_v)

    def get_role_and_permission(self, w_user: WxOpenUser):
        biz_id = self.biz_id
        g_role = dict()
        if w_user.role == CustomerRole.role:
            permission = get_default_customer_permission(biz_id)
            g_role.update({
                str(biz_id): {
                    CustomerRole.id_key_str: w_user.customer_id
                }
            })
        elif w_user.role == CoachRole.role:
            permission = get_coach_permission(biz_id, w_user.coach_id)
            g_role.update({
                str(biz_id): {
                    CoachRole.id_key_str: w_user.coach_id
                }
            })

        elif w_user.role == ManagerRole.role:
            permission = get_manager_permission(self.biz_id)
            g_role.update({
                str(self.biz_id): {
                    # w_user.manager_id 是biz_user_id
                    ManagerRole.id_key_str: w_user.manager_id
                }
            })

        elif w_user.role == StaffRole.role:
            # 如果角色是STAFF, manager_id是staff_id
            permission = get_staff_permission_from_id(w_user.manager_id)
            g_role.update({
                str(self.biz_id): {
                    # w_user.manager_id 是staff_id
                    StaffRole.id_key_str: w_user.manager_id
                }
            })

        return g_role, permission

    def login(self, session_key=None):
        try:
            old_token = self.get('token')
            new_token = None
            if old_token:
                token_cache = TokenCache(old_token)
                elapse = token_cache.expire_seconds - token_cache.redis_store.ttl(old_token)
                if elapse <= 40:    # 如果在不久前生成， 那么还是用以前的
                    new_token = old_token
                else:   # 否则清掉旧token
                    token_redis_store.delete(old_token)

            if not new_token:   # 前面没拿到token
                new_token = generate_token()
                token_cache = TokenCache(token=new_token)
                token_cache.set({
                    'open_id': self.open_id,
                    'app_id': self.app_id
                })

            w_user: WxOpenUser = WxOpenUser.query.filter(and_(
                WxOpenUser.wx_open_id == self.open_id,
                WxOpenUser.app_id == self.app_id
            )).first()
            now = datetime.now()
            w_user.token = new_token
            w_user.login_at = now
            if session_key:     # 这个每次登录都要更新，后面解密需要用到
                w_user.session_key = session_key

            db.session.commit()

            g_role, permission = self.get_role_and_permission(w_user)
            k_v = {
                'biz_id': self.biz_id,
                'w_id': w_user.id,
                'token': new_token,
                'role': json.dumps(g_role),
                'client_role': w_user.role,
                'permission': json.dumps(list(permission)),
            }
            self.set(k_v)
            return new_token, w_user.role
        except WxOpenUserNotFoundException as e:
            raise e

    def login_as_customer(self, customer: Customer):
        new_token = generate_token()
        token_cache = TokenCache(token=new_token)
        token_cache.set({
            'open_id': self.open_id,
            'app_id': self.app_id
        })

        w_user: WxOpenUser = WxOpenUser.query.filter(and_(
            WxOpenUser.wx_open_id == self.open_id,
            WxOpenUser.app_id == self.app_id
        )).first()
        now = datetime.now()
        w_user.token = new_token
        w_user.role = CustomerRole.role
        w_user.customer_id = customer.id
        w_user.login_at = now

        db.session.commit()
        db.session.refresh(w_user)

        g_role, permission = self.get_role_and_permission(w_user)
        k_v = {
            'biz_id': self.biz_id,
            'w_id': w_user.id,
            'token': w_user.token,
            'client_role': w_user.role,
            'role': json.dumps(g_role),
            'permission': json.dumps(list(permission))
        }
        self.set(k_v)
        return w_user.token, w_user.role

    def logout(self):
        old_token = self.get('token')
        if old_token:
            token_redis_store.delete(old_token)
        w_user: WxOpenUser = WxOpenUser.query.filter(and_(
            WxOpenUser.wx_open_id == self.open_id,
            WxOpenUser.app_id == self.app_id
        )).first()
        w_user.role = CustomerRole.role
        w_user.coach_id = 0
        w_user.login_biz_id = None
        w_user.token = None
        db.session.commit()
        self.delete()

    def upgrade_to_coach(self, coach: Coach):
        w_user: WxOpenUser = WxOpenUser.query.filter(and_(
            WxOpenUser.wx_open_id == self.open_id,
            WxOpenUser.app_id == self.app_id
        )).first()

        other: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.coach_id == coach.id,
            WxOpenUser.id != w_user.id,
            WxOpenUser.app_id == self.app_id
        ).first()
        if other:
            other_cache = WxOpenUserCache(app_id=other.app_id, open_id=other.wx_open_id)
            other_cache.logout()

        w_user.role = CoachRole.role
        w_user.coach_id = coach.id
        # 教练在登陆教练端时将staff_id保存到wx_user中,以便boss端的逻辑处理
        biz_user: BizUser = BizUser.query.filter(
            BizUser.phone_number == coach.phone_number
        ).first()
        if biz_user:
            staff: BizStaff = BizStaff.query.filter(
                BizStaff.biz_id == coach.biz_id,
                BizStaff.biz_user_id == biz_user.id
            ).first()
            if staff:
                w_user.manager_id = staff.id
        db.session.commit()

        db.session.refresh(w_user)
        g_role, permission = self.get_role_and_permission(w_user)
        k_v = {
            'client_role': w_user.role,
            'role': json.dumps(g_role),
            'permission': json.dumps(list(permission))
        }
        self.set(k_v)

    def upgrade_to_manager(self, staff: BizStaff):
        w_user: WxOpenUser = WxOpenUser.query.filter(and_(
            WxOpenUser.wx_open_id == self.open_id,
            WxOpenUser.app_id == self.app_id
        )).first()

        other: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.manager_id == staff.id,
            WxOpenUser.id != w_user.id,
            WxOpenUser.app_id == self.app_id
        ).first()
        if other:
            other_cache = WxOpenUserCache(app_id=other.app_id, open_id=other.wx_open_id)
            other_cache.logout()

        w_user.role = ManagerRole.role
        w_user.manager_id = staff.id
        db.session.commit()

        db.session.refresh(w_user)
        g_role, permission = self.get_role_and_permission(w_user)
        k_v = {
            'client_role': w_user.role,
            'role': json.dumps(g_role),
            'permission': json.dumps(list(permission))
        }
        self.set(k_v)

    def upgrade_to_staff(self, staff: BizStaff):
        w_user: WxOpenUser = WxOpenUser.query.filter(and_(
            WxOpenUser.wx_open_id == self.open_id,
            WxOpenUser.app_id == self.app_id
        )).first()

        other: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.manager_id == staff.id,
            WxOpenUser.id != w_user.id,
            WxOpenUser.app_id == self.app_id
        ).first()
        if other:
            other_cache = WxOpenUserCache(app_id=other.app_id, open_id=other.wx_open_id)
            other_cache.logout()

        w_user.role = StaffRole.role
        w_user.manager_id = staff.id
        db.session.commit()

        db.session.refresh(w_user)
        g_role, permission = self.get_role_and_permission(w_user)
        k_v = {
            'client_role': w_user.role,
            'role': json.dumps(g_role),
            'permission': json.dumps(list(permission))
        }
        self.set(k_v)


class StoreBizCache(BaseCache):
    redis_store = store_biz_redis_store
    expire_seconds = cfg['redis_expire']['store']
    type_dict = {
        'store': 'json',
        'course_indexes': 'json',
        'coach_indexes': 'json',
        'contact': 'json',
        'business_hours_begin': 'int',
        'business_hours_end': 'int',
        'customer_app_id': 'str',
        'coupons_brief': 'json',
        'goods_briefs': 'json'
    }

    def __init__(self, biz_id: int):
        self.id = biz_id

    def reload(self):
        # store
        store: Store = Store.query.filter(and_(
            Store.biz_id == self.id
        )).first()

        if not store:
            raise KeyError('store biz_id=' + str(self.id) + ' not found')

        wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(and_(
            WxAuthorizer.biz_id == self.id,
            WxAuthorizer.mark == AppMark.CUSTOMER.value,
        )).first()  # 获取客户端的头像和名称
        customer_app_id = wx_authorizer.app_id if wx_authorizer else None
        store_dict = {
            'cards': store.cards
        }
        business_hours_begin, business_hours_end = store.get_business_hours()

        coupons: List[Coupon] = Coupon.query.filter(
            Coupon.biz_id == store.biz_id
        ).order_by(desc(Coupon.created_at)).all()
        coupons_brief = [c.get_brief() for c in coupons]

        goods: List[Goods] = Goods.query.filter(
            Goods.biz_id == self.id,
            Goods.is_shelf == true()
        ).order_by(desc(Goods.created_at)).all()
        goods_brief = [gs.get_brief() for gs in goods]

        # contact
        contact = None
        for c in store.cards:
            if c.get('type') == 'contact':
                contact = c.get('contact')
        k_v = {
            'customer_app_id': customer_app_id,
            'store': json.dumps(store_dict),
            'business_hours_begin': business_hours_begin,
            'business_hours_end': business_hours_end,
            'course_indexes': json.dumps(store.course_indexes),
            'coach_indexes': json.dumps(store.coach_indexes),
            'contact': json.dumps(contact),
            'coupons_brief': json.dumps(coupons_brief),
            'goods_briefs': json.dumps(goods_brief)
        }
        self.set(k_v)

    @property
    def courses(self):
        course_indexes = self.get('course_indexes')
        return [CourseCache(course_id=c).get('brief') for c in course_indexes] if course_indexes else list()

    @property
    def coaches(self):
        coach_indexes = self.get('coach_indexes')
        return [CoachCache(coach_id=c).get('brief') for c in coach_indexes] if coach_indexes else list()


class CourseCache(BaseCache):
    redis_store = course_redis_store
    expire_seconds = cfg['redis_expire']['store']
    type_dict = {
        'brief': 'json'
    }

    def __init__(self, course_id: int):
        self.id = course_id

    def reload(self):
        course: Course = Course.query.filter(Course.id == self.id).first()
        if not course:
            raise KeyError('course id=' + str(self.id) + '] not found')
        k_v = {
            'brief': json.dumps(course.get_brief())
        }
        self.set(k_v)


class CoachCache(BaseCache):
    redis_store = coach_redis_store
    expire_seconds = cfg['redis_expire']['store']
    type_dict = {
        'brief': 'json',
        'diaries_unread': 'json',
        'exps': 'int',  # 体验会员人数
        'privates': 'int',  # 私教会员人数
        'measurements': 'int'  # 体测会员人数
    }

    def __init__(self, coach_id: int):
        self.id = coach_id

    def reload(self):
        coach: Coach = Coach.query.filter(Coach.id == self.id).first()
        if not coach:
            raise KeyError('coach id=' + str(self.id) + '] not found')
        today_min = tp.get_day_min(datetime.today())
        trainee: List[Trainee] = Trainee.query.filter(
            Trainee.coach_id == self.id,
            or_(
                Trainee.is_bind == true(),
                Trainee.is_measurements == true()
            )
        ).all()
        trainee_cids = [t.customer_id for t in trainee]
        # 查询今日创建了日记的学员
        diaries: List[Diary] = Diary.query.filter(
            Diary.customer_id.in_(trainee_cids),
            Diary.recorded_at == today_min
        ).all()

        trainees: List[Trainee] = Trainee.query.filter(
            Trainee.coach_id == self.id,
            or_(
                Trainee.is_exp == true(),
                Trainee.is_measurements == true(),
                Trainee.is_bind == true()
            )
        ).all()
        privates = 0
        exps = 0
        measurements = 0
        for t in trainees:
            if t.is_bind:
                privates += 1
            if t.is_measurements:
                measurements += 1
            if t.is_exp:
                exps += 1

        k_v = {
            "brief": json.dumps(coach.get_brief()),
            "diaries_unread": json.dumps({
                "date": today_min.strftime("%Y-%m-%d"),
                "trainee": [d.customer_id for d in diaries]
            }),
            "exps": exps,
            "privates": privates,
            "measurements": measurements,
        }
        self.set(k_v)

    def is_read(self, customer_id):
        diaries_unread = self.get('diaries_unread')
        if not diaries_unread:
            return
        unread_trainee = self.get_unread()
        if customer_id not in unread_trainee:
            return
        unread_trainee.remove(customer_id)
        self.set({
            'diaries_unread': json.dumps({
                "date": diaries_unread.get('date'),
                "trainee": unread_trainee
            })
        })

    def get_unread(self):
        diaries_unread = self.get('diaries_unread')
        if not diaries_unread:
            return []
        today_min = tp.get_day_min(datetime.today())
        date = datetime.strptime(diaries_unread.get('date'), "%Y-%m-%d")
        if date != today_min:
            self.reload()
        return diaries_unread.get('trainee')

    def set_unread(self, customer_id):
        diaries_unread = self.get('diaries_unread')
        if not diaries_unread:
            return
        unread_trainee = self.get_unread()
        if customer_id in unread_trainee:
            return
        unread_trainee.append(customer_id)
        self.set({
            'diaries_unread': json.dumps({
                "date": diaries_unread.get('date'),
                "trainee": unread_trainee
            })
        })
        return


class TraineeCache(BaseCache):
    redis_store = trainee_redis_store
    expire_seconds = cfg['redis_expire']['store']
    type_dict = {
        'brief': 'json',
        'name': 'str',
        'trainee_id': 'int'
    }

    def __init__(self, coach_id: int, customer_id: int):
        self.coach_id = coach_id
        self.customer_id = customer_id
        self.id = str(coach_id) + '-' + str(customer_id)

    def reload(self):
        t: Trainee = Trainee.query.filter(and_(
            Trainee.coach_id == self.coach_id,
            Trainee.customer_id == self.customer_id
        )).first()
        k_v = {
            'brief': json.dumps(t.get_brief()),
            'name': t.name,
            'trainee_id': t.id
        }
        self.set(k_v)


class CustomerCache(BaseCache):
    redis_store = customer_redis_store
    expire_seconds = cfg['redis_expire']['store']
    type_dict = {
        'avatar': 'str',
        'nick_name': 'str',
        'phone_number': 'str',
        'base_info': 'json',
        'gender': 'int'
    }

    def __init__(self, customer_id):
        self.id = customer_id

    def reload(self):
        c: Customer = Customer.query.filter(
            Customer.id == self.id
        ).first()
        avatar = c.avatar
        nick_name = c.nick_name
        if not avatar:
            avatar = "https://oss.11train.com/user/avatar/defulate_avatar.png"
        if not nick_name:
            nick_name = "游客"
        k_v = {
            'avatar': avatar,
            'nick_name': nick_name,
            'phone_number': c.phone_number or '无',
            'base_info': json.dumps(c.get_base_info()),
            'gender': c.gender
        }
        self.set(k_v)


class AppCache(BaseCache):
    redis_store = app_redis_store
    expire_seconds = cfg['redis_expire']['store']
    type_dict = {
        'biz_id': 'int',
        'customer_app_id': 'str',
        'coach_app_id': 'str',
        'binding_tmp_id': 'str',
        'confirm_tmp_id': 'str',
        'reservation_tmp_id': 'str',
        'cancel_tmp_id': 'str',
        'group_success_tmp_id': 'str',
        'group_fail_tmp_id': 'str',
        'customer_seat_check_tmp_id': 'str',
        'coach_seat_check_tmp_id': 'str',
        'mark': 'int',
        'head_img': 'str',
        'nick_name': 'str'
    }

    def __init__(self, app_id: str):
        self.id = app_id

    def reload(self):
        wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(
            WxAuthorizer.app_id == self.id
        ).first()

        if not wx_authorizer:
            raise KeyError('wx_authorizer app_id=' + str(self.id) + ' not found')

        k_v = {
            'biz_id': wx_authorizer.biz_id,
            'mark': wx_authorizer.mark,
            'head_img': wx_authorizer.head_img,
            'nick_name': wx_authorizer.nick_name
        }

        apps: List[WxAuthorizer] = WxAuthorizer.query.filter(
            WxAuthorizer.biz_id == wx_authorizer.biz_id
        ).all()

        for app in apps:
            if app.mark == AppMark.CUSTOMER:
                k_v.update({'customer_app_id': app.app_id})
            elif app.mark == AppMark.COACH:
                k_v.update({'coach_app_id': app.app_id})

        wx_templates: List[WxMsgTemplate] = WxMsgTemplate.query.filter(and_(
            WxMsgTemplate.app_id == self.id)).all()
        for wx_tmp in wx_templates:
            if wx_authorizer.mark == AppMark.CUSTOMER.value:
                # 预约成功通知
                if wx_tmp.short_id == reservation_template.short_id:
                    k_v.update({'reservation_tmp_id': wx_tmp.template_id})
                # 拼团成功通知
                elif wx_tmp.short_id == group_success_template.short_id:
                    k_v.update({'group_success_tmp_id': wx_tmp.template_id})
                # 拼团失败通知
                elif wx_tmp.short_id == group_fail_template.short_id:
                    k_v.update({'group_fail_tmp_id': wx_tmp.template_id})
                # 预约取消通知
                elif wx_tmp.short_id == cancel_template.short_id:
                    k_v.update({'cancel_tmp_id': wx_tmp.template_id})
                # 消耗课时通知
                elif wx_tmp.short_id == customer_seat_check_template.short_id:
                    k_v.update({'customer_seat_check_tmp_id': wx_tmp.template_id})

            elif wx_authorizer.mark == AppMark.COACH.value:
                # 绑定成功通知
                if wx_tmp.short_id == binding_template.short_id:
                    k_v.update({'binding_tmp_id': wx_tmp.template_id})
                # 预约处理提醒
                elif wx_tmp.short_id == confirm_template.short_id:
                    k_v.update({'confirm_tmp_id': wx_tmp.template_id})
                # 消耗课时通知
                elif wx_tmp.short_id == coach_seat_check_template.short_id:
                    k_v.update({'coach_seat_check_tmp_id': wx_tmp.template_id})
        self.set(k_v)


class BizUserCache(BaseCache):
    redis_store = biz_user_redis_store
    expire_seconds = cfg['redis_expire']['biz_user_token'] * 2
    type_dict = {
        'biz_user_id': 'int',
        'token': 'str',
        'role': 'json',
        'permission': 'json'
    }

    def __init__(self, website: str, phone_number: str):
        self.website = website
        self.phone_number = phone_number
        self.id = str(website) + '-' + str(phone_number)

    def reload(self):
        b_user: BizUser = BizUser.query.filter(and_(
            BizUser.phone_number == self.phone_number
        )).first()
        if not b_user:
            raise BizUserNotFoundException()

        g_role, permission = self.get_role_and_permission(b_user.id)
        k_v = {
            'biz_user_id': b_user.id,
            'token': b_user.token,
            'role': json.dumps(g_role),
            'permission': json.dumps(list(permission))
        }
        self.set(k_v)

    @staticmethod
    def get_role_and_permission(biz_user_id):
        g_role = dict()
        permission = set()
        # 如果同一个手机号既是manager又是staff时,要将staff的角色覆盖掉

        staffs: List[BizStaff] = BizStaff.query.filter(and_(
            BizStaff.biz_user_id == biz_user_id
        )).all()
        for staff in staffs:
            g_role.update({
                str(staff.biz_id): {
                    BizUserRole.id_key_str: staff.id  # 这里设置了staff的id
                }
            })
            permission.update(get_staff_permission(staff))

        manager_store_biz: List[StoreBiz] = StoreBiz.query.filter(
            StoreBiz.biz_user_id == biz_user_id
        ).all()
        for m_s in manager_store_biz:
            g_role.update({
                str(m_s.id): {
                    ManagerRole.id_key_str: biz_user_id
                }
            })
            permission.update(get_manager_permission(m_s.id))

        return g_role, permission

    def login(self):
        # 先把旧token清理
        old_token = self.get('token')
        if old_token:
            token_redis_store.delete(old_token)

        new_token = generate_token()
        token_cache = TokenCache(token=new_token)
        token_cache.set({
            'website': self.website,
            'phone_number': self.phone_number
        }, cfg['redis_expire']['biz_user_token'])

        b_user: BizUser = BizUser.query.filter(and_(
            BizUser.phone_number == self.phone_number
        )).first()
        now = datetime.now()
        b_user.token = new_token
        b_user.login_at = now

        db.session.commit()
        db.session.refresh(b_user)

        g_role, permission = self.get_role_and_permission(b_user.id)
        k_v = {
            'biz_user_id': b_user.id,
            'token': b_user.token,
            'role': json.dumps(g_role),
            'permission': json.dumps(list(permission))
        }
        self.set(k_v)
        return new_token

    def logout(self):
        old_token = self.get('token')
        if old_token:
            token_redis_store.delete(old_token)

        b_user: BizUser = BizUser.query.filter(and_(
            BizUser.phone_number == self.phone_number
        )).first()
        b_user.token = None
        db.session.commit()
        self.delete()


class AuthLinkCache(BaseCache):
    redis_store = auth_link_redis_store
    expire_seconds = cfg['redis_expire']['auth_link']
    type_dict = {
        'biz_user_id': 'int',
        'biz_id': 'int',
        'mark': 'int'
    }

    def __init__(self, token):
        self.id = token

    def reload(self):
        pass


class GroupCoursesCache(BaseCache):
    redis_store = group_courses_redis_store
    expire_seconds = cfg['redis_expire']['store']
    type_dict = {
        "group_courses": "json"
    }

    def __init__(self, biz_id: int, group_time_id: int):
        self.biz_id = biz_id
        self.group_time_id = group_time_id
        self.id = str(biz_id) + '-' + str(group_time_id)

    def reload(self):
        group_time: GroupTime = GroupTime.query.filter(
            GroupTime.id == self.group_time_id
        ).first()
        if not group_time:
            raise KeyError('group_time id=' + str(self.group_time_id) + ' not found')
        group_courses: List[GroupCourse] = GroupCourse.query.filter(
            GroupCourse.group_time_id == self.group_time_id
        ).order_by(asc(GroupCourse.week), desc(GroupCourse.place), asc(GroupCourse.start_time)).all()

        k_v = {
            "group_courses": json.dumps([g_c.get_brief() for g_c in group_courses])
        }
        self.set(k_v)


class PlaceCache(BaseCache):
    redis_store = place_redis_store
    expire_seconds = cfg['redis_expire']['store']
    type_dict = {
        'name': 'str',
        'id': 'str'
    }

    def __init__(self, place_id: int):
        self.id = place_id

    def reload(self):
        place: Place = Place.query.filter(Place.id == self.id).first()
        if not place:
            raise KeyError('place_id=' + str(self.id) + 'not found')

        k_v = {
            'name': place.name,
            'id': place.get_hash_id()
        }
        self.set(k_v)


class AppAuditCache(BaseCache):
    """ 小程序审核相关的, 目前只涉及用户端的 """
    redis_store = audit_redis_store
    expire_seconds = cfg['redis_expire']['app_audit']
    type_dict = {
        'version': 'str'
    }

    def __init__(self, biz_id: int, app_mark=AppMark.CUSTOMER):
        if type(app_mark) is int:
            self.id = str(biz_id) + '-' + str(app_mark)
        elif isinstance(app_mark, AppMark):
            self.id = str(biz_id) + '-' + str(app_mark.value)
        else:
            raise TypeError('unknown app_mark')

    def reload(self):
        pass

    def is_auditing(self, args) -> bool:
        version = args.get('version')
        if not version:
            return False
        audit_version = self.get('version')
        if not audit_version:
            return False
        if audit_version == version:
            return True
        return False

    def set_version(self, version):
        self.set({'version': version})


class VideoLimitCache(BaseCache):
    """ 视频播放流量限制 """
    redis_store = video_limit_store
    expire_seconds = cfg['redis_expire']['video_limit']
    type_dict = {
        'amount': 'int',  # 每日限额(s)  一般用户初始每日30分钟(1800s)
        'used': 'int'  # 已用时长(s)
    }

    def __init__(self, customer_id: int):
        self.id = customer_id

    def reload(self):
        pass

    def is_over(self) -> bool:
        amount = self.get('amount') or 60
        used = self.get('used') or 0
        if used >= amount:
            # 超出限额
            return True

        return False


class VideoHistory(BaseCache):
    """ 视频观看历史(有效期限暂定为7天) """
    redis_store = video_history_store
    expire_seconds = cfg['redis_expire']['video_history']
    type_dict = {
        'file_ids': 'json'
    }

    def __init__(self, customer_id: int):
        self.id = customer_id

    def reload(self):
        pass


class SalesmanCache(BaseCache):
    redis_store = salesman_store
    expire_seconds = cfg['redis_expire']['store']
    type_dict = {
        'name': 'str',
        'avatar': 'str',
        'email': 'str'
    }

    def __init__(self, salesman_id: int):
        self.id = salesman_id

    def reload(self):
        salesman: Salesman = Salesman.query.filter(Salesman.id == self.id).first()
        if not salesman:
            raise KeyError('salesman id=' + str(self.id) + '] not found')
        k_v = {
            'name': salesman.name,
            'avatar': salesman.avatar,
            'email': salesman.email
        }
        self.set(k_v)


class CheckInCache(BaseCache):
    redis_store = check_in_redis_store
    expire_seconds = cfg['redis_expire']['check_in']
    type_dict = {
        "briefs": 'json',
        "date": 'str'
    }

    def __init__(self, biz_id: int):
        self.id = biz_id

    def reload(self):
        now = datetime.now()
        today_min = tp.get_day_min(now)
        today_max = tp.get_day_max(now)
        check_ins: List[CheckIn] = CheckIn.query.filter(
            CheckIn.biz_id == self.id,
            CheckIn.check_in_date >= today_min,
            CheckIn.check_in_date <= today_max
        ).order_by(asc(CheckIn.check_in_date)).all()

        briefs = list()
        for c in check_ins:
            check_in_time = c.check_in_date
            check_in_data = {
                "customer_id": c.customer_id,
                "check_in_time": check_in_time.strftime('%Y.%m.%d %H:%M:%S')
            }
            if check_in_data not in briefs:
                briefs.append(check_in_data)

        k_v = {
            "briefs": json.dumps(briefs),
            "date": today_min.strftime('%Y.%m.%d %H:%M:%S')
        }
        self.set(k_v)

    def get_avatars(self, customer_id):
        today_min = tp.get_day_min(datetime.today())
        date = datetime.strptime(self.get('date'), "%Y.%m.%d %H:%M:%S")
        if date != today_min:
            self.reload()
        briefs = self.get('briefs')
        avatars = [CustomerCache(b.get('customer_id')).get('avatar') for b in briefs]
        customer_avatar = CustomerCache(customer_id).get('avatar')
        # 将自己的头像剔除
        if customer_avatar in avatars:
            avatars.remove(customer_avatar)
        return avatars

    def get_customer_briefs(self, customer_id):
        today_min = tp.get_day_min(datetime.today())
        date = datetime.strptime(self.get('date'), "%Y.%m.%d %H:%M:%S")
        if date != today_min:
            self.reload()
        briefs = self.get('briefs')
        c_briefs = [{
            'avatar': CustomerCache(b.get('customer_id')).get('avatar'),
            'nick_name': CustomerCache(b.get('customer_id')).get('nick_name')
        } for b in briefs]
        customer_brief = {
            'avatar': CustomerCache(customer_id).get('avatar'),
            'nick_name': CustomerCache(customer_id).get('nick_name')
        }
        # 将自己剔除
        if customer_brief in c_briefs:
            c_briefs.remove(customer_brief)
        return c_briefs


class CouponCustomerCache(BaseCache):
    redis_store = coupon_customer_redis_store
    expire_seconds = cfg['redis_expire']['unread_customer']
    type_dict = {
        'time': 'str',
    }

    def __init__(self, salesman_id: int):
        self.id = salesman_id

    def reload(self):
        now = datetime.now()
        now_str = now.strftime('%Y.%m.%d %H:%M:%S')
        k_v = {
            'time': now_str
        }
        self.set(k_v)


class CustomerUnreadCache(BaseCache):
    redis_store = customer_unread_redis_store
    expire_seconds = cfg['redis_expire']['unread_customer']
    type_dict = {
        'coupon_time': 'str',
        'registration_time': 'str',
        'group_time': 'str',
    }

    def __init__(self, salesman_id: int):
        self.id = salesman_id

    def reload(self, type=None):

        now = datetime.now()
        now_str = now.strftime('%Y.%m.%d %H:%M:%S')
        if type == 'coupon':
            k_v = {
                'coupon_time': now_str
            }
        elif type == 'registration':
            k_v = {
                'registration_time': now_str,
            }
        elif type == 'group':
            k_v = {
                'group_time': now_str,
            }
        else:
            k_v = {
                'coupon_time': now_str,
                'registration_time': now_str,
                'group_time': now_str,
            }
        self.set(k_v)


class GroupReportsCache(BaseCache):
    redis_store = group_reports_redis_store
    expire_seconds = cfg['redis_expire']['group_reports']
    type_dict = {
        'group_reports': 'json',
    }

    def __init__(self, biz_id: int, activity_id: int):
        self.biz_id = biz_id
        self.a_id = activity_id
        self.id = str(biz_id) + '-' + str(activity_id)

    def reload(self):
        group_reports: List[GroupReport] = GroupReport.query.filter(
            GroupReport.biz_id == self.biz_id,
            GroupReport.activity_id == self.a_id,
        ).all()

        group_reports_brief = [group_report.get_brief() for group_report in group_reports]

        k_v = {
            'group_reports': json.dumps(group_reports_brief),
        }
        self.set(k_v)


class UserGroupReportsCache(BaseCache):
    redis_store = user_group_reports_redis_store
    expire_seconds = cfg['redis_expire']['group_reports']
    type_dict = {
        'group_reports': 'json',
    }

    def __init__(self, customer_id: int):
        self.id = customer_id

    def reload(self):
        group_members: List[GroupMember] = GroupMember.query.filter(
            GroupMember.customer_id == self.id,
        ).order_by(desc(GroupMember.created_at)).all()

        group_reports_brief = [group_member.group_report.get_brief() for group_member in group_members]

        k_v = {
            'group_reports': json.dumps(group_reports_brief),
        }
        self.set(k_v)


class DiaryUnreadCache(BaseCache):
    redis_store = diary_unread_redis_store
    expire_seconds = cfg['redis_expire']['unread_customer']
    type_dict = {
        "images_tip": 'str',
        "note_tip": 'str',
        "training_tip": 'str',
        "plan_tip": "str",
        "mg_tip": "str",
        "record_tip": "str"
    }

    def __init__(self, customer_id):
        self.id = customer_id

    def reload(self):
        k_v = {
            "images_tip": "",
            "note_tip": "",
            "training_tip": "",
            "plan_tip": "",
            "mg_tip": "",
            "record_tip": ""
        }
        self.set(k_v)

    def get_unread(self, type=None):
        if not type:
            return
        elif type == 'images':
            images_tip = self.get('images_tip')
            return {
                "unread": bool(images_tip),
                "tip": images_tip
            }
        elif type == 'note':
            note_tip = self.get('note_tip')
            return {
                "unread": bool(note_tip),
                "tip": note_tip
            }
        elif type == 'training':
            training_tip = self.get('training_tip')
            return {
                "unread": bool(training_tip),
                "tip": training_tip
            }
        elif type == 'plan':
            plan_tip = self.get('plan_tip')
            return {
                "unread": bool(plan_tip),
                "tip": plan_tip
            }
        elif type == 'mg':
            mg_tip = self.get('mg_tip')
            return {
                "unread": bool(mg_tip),
                "tip": mg_tip
            }
        elif type == 'record':
            record_tip = self.get('record_tip')
            return {
                "unread": bool(record_tip),
                "tip": record_tip
            }

    def is_read(self, r_type=None):
        if not r_type:
            # 没有type的时候默认全部已读,清除缓存中所有未读数据
            self.reload()
            return
        if r_type == 'images':
            if not self.get('images_tip'):
                return
            self.set({
                "images_tip": ""
            })
        elif r_type == 'note':
            if not self.get('note_tip'):
                return
            self.set({
                "note_tip": ""
            })
        elif r_type == 'training':
            if not self.get('training_tip'):
                return
            self.set({
                "training_tip": ""
            })
        elif r_type == 'plan':
            if not self.get('plan_tip'):
                return
            self.set({
                "plan_tip": ""
            })
        elif r_type == 'mg':
            if not self.get('mg_tip'):
                return
            self.set({
                "mg_tip": ""
            })
        elif r_type == 'record':
            if not self.get('record_tip'):
                return
            self.set({
                "record_tip": ""
            })

    def modified(self, m_type, note_msg=None):
        if m_type == 'images':
            self.set({
                "images_tip": "🌄 教练编辑了你的健身相册"
            })
        elif m_type == 'note':
            self.set({
                'note_tip': note_msg
            })
        elif m_type == 'training':
            self.set({
                "training_tip": "📝 教练编辑了你的训练类型"
            })
        elif m_type == 'plan':
            self.set({
                "plan_tip": "📋 教练编辑了你的健身计划"
            })
        elif m_type == 'mg':
            self.set({
                "mg_tip": "📝 教练编辑了你的训练部位"
            })
        elif m_type == 'record':
            self.set({
                "mg_tip": "📝 教练编辑了你的训练部位"
            })
        elif m_type == 'mg':
            self.set({
                "record_tip": "📝 教练修改了你的体测数据"
            })


class ExCache(BaseCache):
    redis_store = ex_redis_store
    expire_seconds = cfg['redis_expire']['ex']

    type_dict = {
        'title': 'str',
        'full_name': 'str',
        'record_method': 'str',
        'pictures': 'json',
        'primary_mg': 'json',
        'secondary_mg': 'json',
        'describe': 'json',
        'related_exs': 'json'
    }

    def __init__(self, ex_id: int):
        self.id = ex_id

    def reload(self):
        ex: Ex = Ex.query.filter(Ex.id == self.id).first()
        if not ex:
            raise KeyError('ex id=' + self.id + ' not found')

        k_v = {
            'title': ex.title,
            'full_name': ex.full_name,
            'record_method': ex.record_method,
            'pictures': json.dumps(ex.pictures),
            'primary_mg': json.dumps(ex.primary_mg),
            'secondary_mg': json.dumps(ex.secondary_mg),
            'describe': ex.describe,
            'related_exs': ex.related_exs
        }
        self.set(k_v)


class BizStaffCache(BaseCache):
    redis_store = staff_redis_store
    expire_seconds = cfg['redis_expire']['staff']
    type_dict = {
        "id": "str",
        "coach_id": "str",
        "name": "str",
        "roles": "json",
        "avatar": "str",
        "phone_number": "str"
    }

    def __init__(self, biz_staff_id):
        self.id = biz_staff_id

    def reload(self):
        staff: BizStaff = BizStaff.query.filter(
            BizStaff.id == self.id
        ).first()
        if not staff:
            raise KeyError("staff id=" + str(self.id) + " not found")

        name = staff.name
        coach_id = None
        avatar = "https://oss.11train.com/user/avatar/defulate_avatar.png"

        k_v = {
            "id": staff.get_hash_id(),
            "coach_id": coach_id,
            "name": name,
            "avatar": avatar,
            "roles": json.dumps(staff.roles),
            "phone_number": staff.biz_user.phone_number
        }

        coach: Coach = Coach.query.filter(
            Coach.biz_id == staff.biz_id,
            Coach.phone_number == staff.biz_user.phone_number,
            Coach.in_service == true()
        ).first()

        wx_open_user: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.manager_id == staff.id,
            WxOpenUser.login_biz_id == staff.biz_id
        ).first()
        if wx_open_user:
            k_v.update({
                "avatar": wx_open_user.wx_info.get('avatarUrl')
            })

        if coach:
            coach_id = coach.get_hash_id()
            k_v.update({
                "name": coach.name,
                "avatar": coach.avatar,
                "coach_id": coach_id
            })
        self.set(k_v)


class DepartmentCache(BaseCache):
    redis_store = department_redis_store
    expire_seconds = cfg['redis_expire']['department']
    type_dict = {
        "name": "str",
        "members": "json",
        "leader": "json"
    }

    def __init__(self, department_id):
        self.id = department_id

    def reload(self):
        department: Department = Department.query.filter(
            Department.id == self.id
        ).first()
        if not department:
            raise KeyError("department id=" + str(self.id) + " not found")
        members = []
        s_cache = BizStaffCache(department.leader_sid)
        leader = {
            "id": s_cache.get('id'),
            "coach_id": s_cache.get('coach_id'),
            "name": s_cache.get('name'),
            "avatar": s_cache.get('avatar'),
            "is_leader": True
        }
        d_members = department.members or []
        for m in d_members:
            s_cache = BizStaffCache(m)
            member = {
                "id": s_cache.get('id'),
                "coach_id": s_cache.get('coach_id'),
                "name": s_cache.get('name'),
                "avatar": s_cache.get('avatar'),
                "is_leader": bool(m == department.leader_sid)
            }
            members.append(member)

        k_v = {
            "name": department.name,
            "members": json.dumps(members),
            "leader": json.dumps(leader)
        }
        self.set(k_v)


class SeatCheckCache(BaseCache):
    redis_store = seat_check_redis_store
    expire_seconds = cfg['redis_expire']['seat_check']
    type_dict = {
        "code": "str",
    }

    def __init__(self, seat_id: int):
        # 用户只需要输入seat_id就可以获取对应的code
        self.id = seat_id

    def reload(self):
        pass


class SeatCodeCache(BaseCache):
    redis_store = seat_code_redis_store
    expire_seconds = cfg['redis_expire']['seat_check']
    type_dict = {
        "seat_id": "str"
    }

    def __init__(self, code: str):
        # 前台只需要输入code就可以查询对应的seat_id
        self.id = code

    def reload(self):
        pass
