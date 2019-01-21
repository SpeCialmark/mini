import time

import requests
from QcloudApi.common import sign
from random import randint

from store.config import cfg
from store.videos.utils import confirm_event


def pull_event():
    # 拉取消息队列
    secret_id = cfg['tencent_video']['secret_id']
    secret_key = cfg['tencent_video']['secret_key']
    current = int(time.time())
    nonce = randint(1, pow(2, 32))
    s = sign.Sign(secret_id, secret_key)
    params = {
        'SecretId': secret_id,
        'SignatureMethod': 'HmacSHA1',
        'Nonce': nonce,
        'Timestamp': current,
        'Action': 'PullEvent',
    }
    ss = s.make('vod.api.qcloud.com', '/v2/index.php', params,
                method='GET')

    url = 'https://vod.api.qcloud.com/v2/index.php'
    params.update({'Signature': ss})
    r = requests.get(url, params)
    event_info = r.json()
    confirm_event(event_info)
    return event_info
