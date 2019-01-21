import redis
from store.config import cfg
from wechatpy.enterprise import WeChatClient
from wechatpy import WeChatComponent
from wechatpy.session.redisstorage import RedisStorage

_redis_store = redis.from_url(cfg['wechatpy_redis_url'])
_session_interface = RedisStorage(_redis_store)

component = WeChatComponent(
    cfg['wxopen']['COMPONENT_APP_ID'],
    cfg['wxopen']['COMPONENT_APP_SECRET'],
    cfg['wxopen']['COMPONENT_APP_TOKEN'],
    cfg['wxopen']['COMPONENT_ENCODINGAESKEY'],
    session=_session_interface
)

release_client = WeChatClient(cfg['corp_id'], cfg['wxapp_release_agent']['secret'])
release_agent_id = cfg['wxapp_release_agent']['agent_id']

auth_client = WeChatClient(cfg['corp_id'], cfg['wxapp_auth_agent']['secret'])
auth_agent_id = cfg['wxapp_auth_agent']['agent_id']

agent_client = WeChatClient(cfg['corp_id'], cfg['wxapp_agent_agent']['secret'])
agent_agent_id = cfg['wxapp_agent_agent']['agent_id']

backend_client = WeChatClient(cfg['corp_id'], cfg['backend_agent']['secret'])
backend_agent_id = cfg['backend_agent']['agent_id']
