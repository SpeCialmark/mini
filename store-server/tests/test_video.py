import json
import time
import base64
import hmac
import pytest
from hashlib import sha1 as sha
import math
from random import randint
from QcloudApi.common import sign
import requests

from store.main_app import create_main_app
from store.videos.tasks import pull_event

secret_id = 'AKIDzOo5TC4bJrEUcap0TmureGhy40lQoDLO'
secret_key = '150CJFF6mHeEteaRSr7LQNDtPDxWuIhw'


@pytest.yield_fixture(scope="session")
def app_ctx():
    print('***create app***')
    app = create_main_app()
    ctx = app.app_context()
    ctx.push()
    # 设置好绝对路径,这样无论从哪里运行都ok
    yield app
    ctx.pop()
    print('***pop app***')


@pytest.mark.skip
def test_signature():
    current = int(time.time())
    expired = current + 120
    random = randint(1, pow(2, 32))

    original = 'secretId={}&currentTimeStamp={}&expireTime={}&random={}'.format(secret_id, current, expired, random)

    h = hmac.new(secret_key.encode('utf-8'), original.encode('utf-8'), sha)
    msg = base64.b64encode(h.digest() + bytes(original, 'utf-8')).decode('utf-8')
    print('')
    print(msg)


@pytest.mark.skip
def test_sign():
    s = sign.Sign('secretIdFoo', 'secretKeyBar')
    params = {
        'SecretId': 'secretIdFoo',
        'Region': 'ap-guangzhou',
        'SignatureMethod': 'HmacSHA1',
        'Nonce': '1290303896666895346',
        'Timestamp': '1512393162',
        'Action': 'DescribeInstances',
        'Version': '2017-03-12',
    }
    ss = s.make('cvm.api.qcloud.com', '/v2/index.php', params,
                method='POST')
    assert ss == 'p3n+pxBqF5JGZtDSxoVn5tGngf0='
    print('ok')


@pytest.mark.skip
def test_s():
    current = int(time.time())
    # expired = current + 60 * 10  # 十分钟有效期
    nonce = randint(1, pow(2, 32))
    file_id = 5285890781089628300
    s = sign.Sign(secret_id, secret_key)
    params = {
        'SecretId': secret_id,
        'Region': 'ap-guangzhou',
        'SignatureMethod': 'HmacSHA1',
        'Nonce': nonce,
        'Timestamp': current,
        'Action': 'GetVideoInfo',
        'fileId': file_id
    }
    ss = s.make('vod.api.qcloud.com', '/v2/index.php', params,
                method='GET')
    print('ss=')
    print(ss)

    url = 'https://vod.api.qcloud.com/v2/index.php?'
    params.update({'Signature': ss})
    r = requests.get(url, params)
    print(r.json())
    print(json.dumps(r.json()))


def test_confirm_event():
    pull_event()
    return
