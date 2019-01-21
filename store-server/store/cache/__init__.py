import redis
from store.config import cfg
import json
from abc import ABCMeta, abstractmethod


lock_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=1))

# db = 3 , 用于 wechatpy.
# db = 4, 用于　celery_broker

biz_user_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=9))

wx_open_user_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=10))

token_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=11))

store_biz_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=12))

code_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=13))

app_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=14))

course_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=15))

coach_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=16))

invitation_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=17))

form_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=18))

trainee_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=19))

customer_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=20))

auth_link_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=21))

group_courses_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=22))

place_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=23))

audit_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=24))

video_limit_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=25))

video_history_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=26))

salesman_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=27))

check_in_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=28))

coupon_customer_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=29))

customer_unread_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=30))

group_reports_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=31))

user_group_reports_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=32))

diary_unread_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=33))

ex_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=34))

department_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=35))

staff_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=36))

seat_check_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=37))

seat_code_redis_store = redis.StrictRedis(
    connection_pool=redis.ConnectionPool.from_url(cfg['redis_url'], db=38))


class BaseCache(metaclass=ABCMeta):
    type_dict: dict = None
    redis_store: redis.StrictRedis = None
    expire_seconds: int = 3600

    @abstractmethod
    def reload(self):
        pass

    def delete(self):
        self.redis_store.delete(self.id)

    def exists(self):
        return self.redis_store.ttl(self.id) > 1

    def set(self, k_v: dict, expire_seconds=None):
        for k in k_v.keys():
            if k not in self.type_dict:
                raise KeyError('key={} not found'.format(k))
        self.redis_store.hmset(self.id, k_v)
        self.redis_store.expire(self.id, expire_seconds or self.expire_seconds)

    def get(self, *keys):
        values = self.redis_store.hmget(self.id, keys)
        if all(v is None for v in values):      # 都是None, 很可能是已过期
            if not self.redis_store.exists(self.id):
                self.reload()
                values = self.redis_store.hmget(self.id, keys)

        res = list()
        for key, value in zip(keys, values):
            v_type = self.type_dict.get(key)
            if not v_type:
                raise KeyError('key={} not found'.format(key))
            res.append(self.parse(v_type, value))
        return tuple(res) if len(res) > 1 else res[0]

    @staticmethod
    def parse(v_type, value):
        if value == b'None' or value is None:
            return None
        if v_type == 'str':
            return value.decode('utf-8')
        elif v_type == 'int':
            return int(value)
        elif v_type == 'json':
            if value == b'null':
                return None
            return json.loads(value.decode('utf-8'))
        elif v_type == 'bool':
            value = value.decode('utf-8')
            if value == b'null':
                return None
            return bool(value == 'True')
        else:
            raise KeyError('v_type={} not found'.format(v_type))
