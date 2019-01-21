from functools import wraps
from flask import g, jsonify, request
from http import HTTPStatus

from sqlalchemy import true

from store.domain.models import Coach, Trainee, StoreBiz, Department, \
    BizStaff
from store.domain.permission import Permission
from store.domain.role import BaseRole, CustomerRole, CoachRole, StaffRole, ManagerRole, BizUserRole
from store.domain.cache import TokenCache, WxOpenUserCache, BizUserCache, AppAuditCache


def load_token(**kwargs):
    token = request.headers.get('token')
    if not token:
        return dict(), HTTPStatus.UNAUTHORIZED
    token_cache = TokenCache(token=token)

    app_id, open_id, website, phone_number, admin_role = token_cache.get(
        'app_id', 'open_id', 'website', 'phone_number', 'admin_role')

    if app_id and open_id:
        # 小程序端
        g.app_id = app_id
        wx_open_user_cache = WxOpenUserCache(app_id=app_id, open_id=open_id)
        permission, g.biz_id, g.role, g.w_id = wx_open_user_cache.get('permission', 'biz_id', 'role', 'w_id')
        g.permission = set(tuple(p) for p in permission) if permission else set()
    elif website and phone_number:
        # website
        biz_user_cache = BizUserCache(website=website, phone_number=phone_number)
        permission, g.biz_user_id, g.role = biz_user_cache.get('permission', 'biz_user_id', 'role')
        g.permission = set(tuple(p) for p in permission) if permission else set()
    elif admin_role:
        # 开发人员登录
        g.role = admin_role
        return dict(), HTTPStatus.OK
    else:
        return dict(), HTTPStatus.UNAUTHORIZED

    # biz_id 是个特别的属性, 可以从redis中读取, 也有可以从request的参数中读取
    biz_hid = request.args.get('biz_id', default=None, type=str)
    if biz_hid is None:
        biz_hid = kwargs.get('biz_hid')
    if biz_hid is None:
        biz_hid = request.headers.get('biz_id')
    if biz_hid:
        store_biz: StoreBiz = StoreBiz.find(biz_hid)
        if not store_biz:
            return {'msg': '该门店不存在'}, HTTPStatus.NOT_FOUND
        else:
            g.biz_id = store_biz.id     # 当前想要操作的biz_id

    return dict(), HTTPStatus.OK


def roles_required(*roles):
    """ Decorator which specifies that a user must have all the specified roles. """
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            if not g.get('role'):
                msg_dict, http_status = load_token(**kwargs)
                if http_status != HTTPStatus.OK:
                    return jsonify(msg_dict), http_status
            for r in roles:  # type: BaseRole
                if not r.is_undefined:
                    r.biz_id = g.biz_id
                if not r.in_g_role(g.role):
                    return jsonify(msg='角色不对, 需要{}'.format(r.role)), HTTPStatus.FORBIDDEN
            return f(*args, **kwargs)
        return func
    return decorator


def roles_required_at_least(*roles):
    """ Decorator which specifies that a user must have at least one of the specified roles. """
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            if not g.get('role'):
                msg_dict, http_status = load_token(**kwargs)
                if http_status != HTTPStatus.OK:
                    return jsonify(msg_dict), http_status
            for role in roles:  # type: BaseRole
                if not role.is_undefined:
                    role.biz_id = g.biz_id
                if role.in_g_role(g.role):
                    return f(*args, **kwargs)
            else:
                return jsonify(msg='角色不对'), HTTPStatus.FORBIDDEN
        return func
    return decorator


def customer_id_require():
    """ 可以是customer，也可以是能操作customer角色的coach或boss """
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            if not g.get('role'):
                msg_dict, http_status = load_token(**kwargs)
                if http_status != HTTPStatus.OK:
                    return jsonify(msg_dict), http_status

            customer_id = CustomerRole(g.biz_id).get_id(g.role)
            if not customer_id:     # 如果不是customer， 可以是绑定学员的教练
                t_id = request.args.get('trainee_id', default=None)
                if not t_id:
                    return jsonify(msg='missing trainee_id'), HTTPStatus.FORBIDDEN
                trainee: Trainee = Trainee.find(t_id)
                if not trainee:
                    return jsonify(msg='学员ID不对'), HTTPStatus.FORBIDDEN
                coach_id = CoachRole(g.biz_id).get_id(g.role)
                if coach_id != trainee.coach_id:
                    return jsonify(msg='没有权限查看该学员'), HTTPStatus.FORBIDDEN
                customer_id = trainee.customer_id
                g.coach_id = coach_id
            g.customer_id = customer_id
            return f(*args, **kwargs)
        return func
    return decorator


def coach_id_require():
    """ 可以是coach，也可以是能操作coach角色的staff或boss """
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            if not g.get('role'):
                msg_dict, http_status = load_token(**kwargs)
                if http_status != HTTPStatus.OK:
                    return jsonify(msg_dict), http_status

            coach_id = CoachRole(g.biz_id).get_id(g.role)
            if not coach_id:  # 如果不是coach， 可以是staff或boss
                manager_id = ManagerRole(g.biz_id).get_id(g.role)
                staff_id = StaffRole(g.biz_id).get_id(g.role)
                if not manager_id and not staff_id:
                    # 既不是manager又不是staff
                    return jsonify(msg='暂无权限'), HTTPStatus.FORBIDDEN
                c_id = request.args.get('coach_id', default=None)
                if not c_id:
                    return jsonify(msg='missing coach_id'), HTTPStatus.FORBIDDEN
                coach: Coach = Coach.find(c_id)
                if not coach:
                    return jsonify(msg='教练ID不对'), HTTPStatus.FORBIDDEN
                coach_id = coach.id
            g.coach_id = coach_id
            return f(*args, **kwargs)
        return func
    return decorator


def leader_require():
    """ 部门管理员访问验证 """
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            if not g.get('role'):
                msg_dict, http_status = load_token(**kwargs)
                if http_status != HTTPStatus.OK:
                    return jsonify(msg_dict), http_status
            manager_id = ManagerRole(g.biz_id).get_id(g.role)
            if manager_id:
                g.manager_id = manager_id
                g.is_root = True
            else:
                staff_id = StaffRole(g.biz_id).get_id(g.role)
                if not staff_id:
                    # PC端操作
                    biz_user_id = BizUserRole(g.biz_id).get_id(g.role)
                    if not biz_user_id:
                        return jsonify(msg='暂无权限'), HTTPStatus.FORBIDDEN
                    staff: BizStaff = BizStaff.query.filter(
                        BizStaff.biz_id == g.biz_id,
                        BizStaff.biz_user_id == biz_user_id
                    ).first()
                    if not staff:
                        return jsonify(msg='暂无权限'), HTTPStatus.FORBIDDEN
                    staff_id = staff.id
                # 该成员是根部门的成员
                department: Department = Department.query.filter(
                    Department.biz_id == g.biz_id,
                    Department.is_root == true(),
                    Department.members.any(staff_id)
                ).first()
                g.is_root = True
                if not department:
                    # 该成员是组长
                    department: Department = Department.query.filter(
                        Department.biz_id == g.biz_id,
                        Department.leader_sid == staff_id
                    ).first()
                    g.is_root = False
                if not department:
                    return jsonify(msg='暂无权限'), HTTPStatus.FORBIDDEN
                g.staff_id = staff_id
            return f(*args, **kwargs)
        return func
    return decorator


def root_department_require():
    """ 根部门成员访问验证 """
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            if not g.get('role'):
                msg_dict, http_status = load_token(**kwargs)
                if http_status != HTTPStatus.OK:
                    return jsonify(msg_dict), http_status
                manager_id = ManagerRole(g.biz_id).get_id(g.role)
                if not manager_id:
                    staff_id = StaffRole(g.biz_id).get_id(g.role)
                    if not staff_id:
                        # PC端操作
                        biz_user_id = BizUserRole(g.biz_id).get_id(g.role)
                        if not biz_user_id:
                            return jsonify(msg='暂无权限'), HTTPStatus.FORBIDDEN
                        staff: BizStaff = BizStaff.query.filter(
                            BizStaff.biz_id == g.biz_id,
                            BizStaff.biz_user_id == biz_user_id
                        ).first()
                        if not staff:
                            return jsonify(msg='暂无权限'), HTTPStatus.FORBIDDEN
                        staff_id = staff.id
                    # 是根部门的成员
                    department: Department = Department.query.filter(
                        Department.biz_id == g.biz_id,
                        Department.is_root == true(),
                        Department.members.any(staff_id),
                    ).first()
                    if not department:
                        return jsonify(msg='暂无权限'), HTTPStatus.FORBIDDEN
                    g.staff_id = staff_id
                g.manager_id = manager_id
            return f(*args, **kwargs)
        return func
    return decorator


def permission_required(*permissions):
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            if not g.get('permission'):
                msg_dict, http_status = load_token(**kwargs)
                if http_status != HTTPStatus.OK:
                    return jsonify(msg_dict), http_status
            for p in permissions:   # type: Permission
                p.biz_id = g.biz_id
                if not p.to_set() <= g.permission:
                    return jsonify(msg='暂无{}'.format(p.title)), HTTPStatus.FORBIDDEN
            return f(*args, **kwargs)
        return func
    return decorator


def permission_required_at_least(*permissions):
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            if not g.get('permission'):
                msg_dict, http_status = load_token(**kwargs)
                if http_status != HTTPStatus.OK:
                    return jsonify(msg_dict), http_status
            for p in permissions:   # type: Permission
                p.biz_id = g.biz_id
                if p.to_set() <= g.permission:
                    return f(*args, **kwargs)
            else:
                return jsonify(msg='暂无权限'), HTTPStatus.FORBIDDEN
        return func
    return decorator


def hide_feed_videos(func):
    def wrapper(**kwargs):
        msg_dict, http_status = load_token(**kwargs)
        if http_status != HTTPStatus.OK:
            return jsonify(msg_dict), http_status
        biz_id = g.get('biz_id')
        # 将version从header中获取
        is_auditing = AppAuditCache(biz_id=biz_id).is_auditing(request.headers)
        # 获取当前提交的小程序的模板
        if not is_auditing:
            return func()

        response = func()  # [{'id': xx, ..., 'video':{xxx}}]
        if not response:
            # 若接口无返回结果
            return jsonify({'feed_list': []})
        if type(response) is tuple:
            # 返回数据不是正常数据时会带上HTTPStatus因此是元组
            status_code = response[1]
            if status_code != HTTPStatus.OK:
                # 遍历页面时有可能对应的id为undefined
                # 若请求接口返回的结果不是200,则直接返回原本的数据
                return response

        res = response.get_json()
        feed_list = res.get('feed_list')
        new_res = []
        # 将返回数据中的video给隐藏
        for r in feed_list:
            r = {k: v for k, v in r.items() if k != 'video'}
            new_res.append(r)
        return jsonify({'feed_list': new_res})
    return wrapper


def hide_place_videos():
    # 防止以后修改字段因此每个视频接口独立一个隐藏器
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            msg_dict, http_status = load_token(**kwargs)
            if http_status != HTTPStatus.OK:
                return jsonify(msg_dict), http_status
            biz_id = g.get('biz_id')
            # 将version从header中获取
            is_auditing = AppAuditCache(biz_id=biz_id).is_auditing(request.headers)
            # 获取当前提交的小程序的模板
            if not is_auditing:
                return f(*args, **kwargs)

            response = f(*args, **kwargs)
            if not response:
                # 若接口无返回结果
                return jsonify()
            if type(response) is tuple:
                # 返回数据不是正常数据时会带上HTTPStatus因此是元组
                status_code = response[1]
                if status_code != HTTPStatus.OK:
                    # 遍历页面时有可能对应的id为undefined
                    # 若请求接口返回的结果不是200,则直接返回原本的数据
                    return response

            res = response.get_json()
            res.update({'videos': []})
            return jsonify(res)
        return func
    return decorator


def hide_coach_videos():
    # 防止以后修改字段因此每个视频接口独立一个隐藏器
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            msg_dict, http_status = load_token(**kwargs)
            if http_status != HTTPStatus.OK:
                return jsonify(msg_dict), http_status
            biz_id = g.get('biz_id')
            # 将version从header中获取
            is_auditing = AppAuditCache(biz_id=biz_id).is_auditing(request.headers)
            # 获取当前提交的小程序的模板
            if not is_auditing:
                return f(*args, **kwargs)

            response = f(*args, **kwargs)
            if not response:
                # 若接口无返回结果
                return jsonify()
            if type(response) is tuple:
                # 返回数据不是正常数据时会带上HTTPStatus因此是元组
                status_code = response[1]
                if status_code != HTTPStatus.OK:
                    # 遍历页面时有可能对应的id为undefined
                    # 若请求接口返回的结果不是200,则直接返回原本的数据
                    return response

            res = response.get_json()
            res.update({'videos': []})
            return jsonify(res)
        return func
    return decorator


def hide_course_videos():
    # 防止以后修改字段因此每个视频接口独立一个隐藏器
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            msg_dict, http_status = load_token(**kwargs)
            if http_status != HTTPStatus.OK:
                return jsonify(msg_dict), http_status
            biz_id = g.get('biz_id')
            # 将version从header中获取
            is_auditing = AppAuditCache(biz_id=biz_id).is_auditing(request.headers)
            # 获取当前提交的小程序的模板
            if not is_auditing:
                return f(*args, **kwargs)

            response = f(*args, **kwargs)
            if not response:
                # 若接口无返回结果
                return jsonify()
            if type(response) is tuple:
                # 返回数据不是正常数据时会带上HTTPStatus因此是元组
                status_code = response[1]
                if status_code != HTTPStatus.OK:
                    # 遍历页面时有可能对应的id为undefined
                    # 若请求接口返回的结果不是200,则直接返回原本的数据
                    return response

            res = response.get_json()
            res.update({'videos': []})
            return jsonify(res)
        return func
    return decorator


def hide_shake_videos():
    # 防止以后修改字段因此每个视频接口独立一个隐藏器
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            msg_dict, http_status = load_token(**kwargs)
            if http_status != HTTPStatus.OK:
                return jsonify(msg_dict), http_status
            biz_id = g.get('biz_id')
            # 将version从header中获取
            is_auditing = AppAuditCache(biz_id=biz_id).is_auditing(request.headers)
            # 获取当前提交的小程序的模板
            if not is_auditing:
                return f(*args, **kwargs)

            response = f(*args, **kwargs)
            if not response:
                # 若接口无返回结果
                return jsonify()
            if type(response) is tuple:
                # 返回数据不是正常数据时会带上HTTPStatus因此是元组
                status_code = response[1]
                if status_code != HTTPStatus.OK:
                    # 遍历页面时有可能对应的id为undefined
                    # 若请求接口返回的结果不是200,则直接返回原本的数据
                    return response
            res = response.get_json()
            res.update({'videos': []})
            return jsonify(res)
        return func
    return decorator


def hide_index_video():
    # 防止以后修改字段因此每个视频接口独立一个隐藏器
    def decorator(f):
        @wraps(f)
        def func(*args, **kwargs):
            msg_dict, http_status = load_token(**kwargs)
            if http_status != HTTPStatus.OK:
                return jsonify(msg_dict), http_status
            biz_id = g.get('biz_id')
            # 将version从header中获取
            is_auditing = AppAuditCache(biz_id=biz_id).is_auditing(request.headers)
            # 获取当前提交的小程序的模板
            if not is_auditing:
                return f(*args, **kwargs)

            response = f(*args, **kwargs)
            if not response:
                # 若接口无返回结果
                return jsonify()
            if type(response) is tuple:
                # 返回数据不是正常数据时会带上HTTPStatus因此是元组
                status_code = response[1]
                if status_code != HTTPStatus.OK:
                    # 遍历页面时有可能对应的id为undefined
                    # 若请求接口返回的结果不是200,则直接返回原本的数据
                    return response
            res = response.get_json()
            res.update({'video': {}})
            return jsonify(res)
        return func
    return decorator
