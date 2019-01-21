from collections import namedtuple
from typing import List

"""
商家人员角色
    查看网页端权限 (角色必备)
    管理门店资料权限
    管理私教人员权限 (包含编辑私教人员资料权限) 
    编辑私教人员资料权限

    管理团课教练人员权限
    管理课表权限

    管理动态权限
    管理上线发布权限    

私教角色
    预约, 会员资料(角色必备)
    编辑个人资料权限 (角色必备)
"""


class Scope:
    BIZ = 'biz'
    STORE = 'store'

    COACH = 'coach'
    PRIVATE_COACH = 'private_coach'
    PUBLIC_COACH = 'public_coach'

    GROUP_COURSE = 'group_course'
    DEPLOY = 'deploy'
    FEED = 'feed'
    WEB = 'web'
    RESERVATION = 'reservation'

    VIDEO = 'video'
    PLACE = 'place'
    SALESMAN = 'salesmen'
    REGISTRATION = 'registration'


class Method:
    ALL = 'all'
    GET = 'get'
    PUT = 'put'
    DELETE = 'delete'


PermissionTuple = namedtuple('Permission', ['biz_id', 'scope', 'method', 'object_id'])


class Permission(object):
    title = None
    name = None
    scope = None
    method = None

    def __init__(self, biz_id=None, object_id=None):
        self._biz_id = biz_id
        self._object_id = object_id

    @property
    def biz_id(self):
        return self._biz_id

    @biz_id.setter
    def biz_id(self, value):
        self._biz_id = value

    @property
    def object_id(self):
        return self._object_id

    @object_id.setter
    def object_id(self, value):
        self._object_id = value

    def to_tuple(self):
        if not self._biz_id:
            raise KeyError('biz_id not set!')
        return self._biz_id, self.scope, self.method, self._object_id

    def to_set(self) -> set:
        return set([self.to_tuple()])

    def to_list(self) -> list:
        return list([self.to_tuple()])

    def is_same_kind(self, other) -> bool:
        return bool(self.scope == other.scope and self.method == other.method and self._object_id == other.object_id)


class ViewBizPermission(Permission):
    """ 查看门店公开信息的权限, 包括打卡排名. 一般用户都具备."""
    title = '查看门店权限'
    name = 'view_biz'
    scope = Scope.BIZ
    method = Method.GET


class ViewBizWebPermission(Permission):
    """ 查看网页端权限 (商家人员角色必备) """
    title = '查看网页端权限'
    name = 'view_biz_web'
    scope = Scope.WEB
    method = Method.GET


class EditStorePermission(Permission):
    """ 管理门店资料权限 """
    title = '管理门店资料权限'
    name = 'edit_store'
    scope = Scope.STORE
    method = Method.PUT


class ManagePrivateCoachPermission(Permission):
    """ 管理私教人员权限 """
    title = '管理私教人员权限'
    name = 'manage_private_coach'
    scope = Scope.PRIVATE_COACH
    method = Method.ALL


class EditPrivateCoachPermission(Permission):
    """ 编辑私教人员资料权限 """
    title = '编辑私教人员资料权限'
    name = 'edit_private_coach'
    scope = Scope.PRIVATE_COACH
    method = Method.PUT


class ManagePublicCoachPermission(Permission):
    """ 管理团课教练人员权限 """
    title = '管理团课教练人员权限'
    name = 'manage_public_coach'
    scope = Scope.PUBLIC_COACH
    method = Method.ALL


class ManageGroupCoursePermission(Permission):
    """ 管理课表权限 """
    title = '管理课表权限'
    name = 'manage_group_course'
    scope = Scope.GROUP_COURSE
    method = Method.ALL


class ManageFeedPermission(Permission):
    """ 管理动态权限 """
    title = '管理动态权限'
    name = 'manage_feed'
    scope = Scope.FEED
    method = Method.ALL


class DeployPermission(Permission):
    """ 管理上线发布权限 """
    title = '管理上线发布权限'
    name = 'deploy'
    scope = Scope.DEPLOY
    method = Method.ALL


class ReservationPermission(Permission):
    """ 用户预约权限, 遇到黑名单的用户, 应该去掉该权限 """
    title = '预约权限'
    name = 'reservation'
    scope = Scope.RESERVATION
    method = Method.ALL


class EditCoachItemPermission(Permission):
    """ 编辑个人资料权限 (教练角色必备) """
    title = '编辑个人资料权限'
    name = 'edit_coach_item'
    scope = Scope.COACH
    method = Method.PUT


class ManagePlacePermission(Permission):
    """ 管理场地权限 """
    title = '管理场地权限'
    name = 'manage_place'
    scope = Scope.PLACE
    method = Method.ALL


class UploadVideoPermission(Permission):
    """ 上传视频权限 """
    title = '上传视频权限'
    name = 'upload_video'
    scope = Scope.VIDEO
    method = Method.PUT


class ManageVideoPermission(Permission):
    """ 管理视频权限 """
    title = "管理视频权限"
    name = "manage_video"
    scope = Scope.VIDEO
    method = Method.ALL


class ManageSalesmanPermission(Permission):
    """ 管理会籍权限 """
    title = '管理会籍权限'
    name = 'manage_salesman'
    scope = Scope.SALESMAN
    method = Method.ALL


class ManageRegistrationPermission(Permission):
    """ 管理到店登记权限 """
    title = '管理到店登记权限'
    name = 'manage_registration'
    scope = Scope.REGISTRATION
    method = Method.ALL


def get_permission(name, biz_id=None, object_id=None):
    all_permissions: List[Permission] = [
        ViewBizPermission(), ViewBizWebPermission(), EditStorePermission(), ManagePrivateCoachPermission(),
        EditPrivateCoachPermission(), ManagePublicCoachPermission(), ManageGroupCoursePermission(),
        ManageFeedPermission(), DeployPermission(), ReservationPermission(),
        EditCoachItemPermission(), ManagePlacePermission(), ManageSalesmanPermission(), UploadVideoPermission(),
        ManageVideoPermission(), ManageRegistrationPermission()
    ]
    for p in all_permissions:
        if name == p.name:
            p.biz_id = biz_id
            p.object_id = object_id
            return p
    return None


def get_permissions_name(permissions: set, biz_id=None, object_id=None) -> list:
    all_permissions: List[Permission] = [
        ViewBizPermission(), ViewBizWebPermission(), EditStorePermission(), ManagePrivateCoachPermission(),
        EditPrivateCoachPermission(), ManagePublicCoachPermission(), ManageGroupCoursePermission(),
        ManageFeedPermission(), DeployPermission(), ReservationPermission(),
        EditCoachItemPermission(), ManagePlacePermission(), ManageSalesmanPermission(), UploadVideoPermission(),
        ManageVideoPermission(), ManageRegistrationPermission()
    ]

    permissions = [p for p in permissions if p[0] == biz_id]  # p -> (14, "private_coach", "put", null)
    permission_list = []

    for permission_tuple in permissions:
        scope = permission_tuple[1]
        methods = permission_tuple[2]
        permission = Permission()
        permission.scope = scope
        permission.method = methods
        for p in all_permissions:
            if p.is_same_kind(permission):
                p.biz_id = biz_id
                p.object_id = object_id
                permission_list.append(p.name)
    return permission_list


def get_all_permission():
    all_permissions: List[Permission] = [
        ViewBizPermission.name, ViewBizWebPermission.name, EditStorePermission.name, ManagePrivateCoachPermission.name,
        EditPrivateCoachPermission.name, ManagePublicCoachPermission.name, ManageGroupCoursePermission.name,
        ManageFeedPermission.name, DeployPermission.name, ReservationPermission.name,
        EditCoachItemPermission.name, ManagePlacePermission.name, ManageSalesmanPermission.name,
        UploadVideoPermission.name, ManageVideoPermission.name, ManageRegistrationPermission.name
    ]
    return all_permissions


staff_selectable_permissions = [
    ViewBizWebPermission.name, ViewBizPermission.name,
    DeployPermission.name, EditStorePermission.name, ManagePrivateCoachPermission.name,
    ManagePublicCoachPermission.name, ManageFeedPermission.name, EditPrivateCoachPermission.name,
    ManageGroupCoursePermission.name, ManagePlacePermission.name, ManageSalesmanPermission.name,
    UploadVideoPermission.name, ManageVideoPermission.name, ManageRegistrationPermission.name
]
