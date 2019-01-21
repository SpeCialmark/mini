from collections import namedtuple

RoleTuple = namedtuple('Role', ['biz_id', 'role'])


UNDEFINED_BIZ_ID = 0


class BaseRole(object):
    role = None
    id_key_str = None

    def __init__(self, biz_id=None):
        self._biz_id = biz_id

    @property
    def biz_id(self):
        return self._biz_id

    @biz_id.setter
    def biz_id(self, value):
        self._biz_id = value

    @property
    def is_undefined(self) -> bool:
        return bool(self._biz_id == UNDEFINED_BIZ_ID)

    def to_tuple(self) -> namedtuple:
        if self._biz_id is None:
            raise KeyError('biz_id not set!')
        return RoleTuple(biz_id=self._biz_id, role=self.role)

    def to_set(self) -> set:
        return set([self.to_tuple()])

    def to_list(self) -> list:
        return list([self.to_tuple()])

    def is_same_kind(self, other) -> bool:
        return bool(self.role == other.role)

    def in_g_role(self, g_role: dict) -> bool:
        biz = g_role.get(str(self.biz_id))
        if biz:
            if biz.get(self.id_key_str):
                return True
        return False

    def get_id(self, g_role: dict):
        biz = g_role.get(str(self.biz_id))
        if not biz:
            return None
        return biz.get(self.id_key_str)

    # def get_role_from_g(self, g_role: dict):


class AdminRole(BaseRole):
    """ 子类没有新增属性和方法, 只是设置了新的初始参数 """
    role = 'admin'
    id_key_str = 'admin_id'


class CustomerRole(BaseRole):
    role = 'customer'
    id_key_str = 'customer_id'


class CoachRole(BaseRole):
    role = 'coach'
    id_key_str = 'coach_id'


class BizUserRole(BaseRole):
    role = 'biz_user'
    id_key_str = 'biz_user_id'


class ManagerRole(BaseRole):
    role = 'manager'
    id_key_str = 'manager_id'


class StaffRole(BaseRole):
    role = "staff"
    id_key_str = "staff_id"

