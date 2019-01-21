from .mns.topic import TopicMessage
from .mns.account import Account
from store.config import cfg
import json

mns_account = Account(
    cfg['aliyun_mns']['endpoint'],
    cfg['aliyun_mns']['AccessKeyId'],
    cfg['aliyun_mns']['AccessKeySecret'], '')

topic = mns_account.get_topic('customer-arrived')


def push_registration_message(brief: dict, biz_hid):
    # # 对命名空间为'namespace'中的事件'arrived'推送内容为'brief'的消息
    # # 根据biz_hid来区分namespace
    # namespace = '/'+biz_hid
    brief.update({
        'is_push': True  # 用于前端样式判断
    })
    # socketio.emit('arrived', brief, namespace=namespace)
    msg_body = json.dumps({
        'brief': brief,
        'biz_hid': biz_hid
    })
    msg = TopicMessage(msg_body)
    topic.publish_message(msg)
