import json
import time
from datetime import datetime
from urllib.parse import urlencode, quote

from hashids import Hashids
from pprint import pprint
import base64
import hmac
import time

import requests
from random import randint
from hashlib import sha1 as sha, sha256

from store.cache import form_redis_store
from store.config import cfg
from store.wxopen import component

base_url = 'https://sz.11train.com/api/v1'

token_format = '{phone_number}:{sms_code}'
phone_number = '18589059214'
sms_code = '625593'     # 查看手机

biz_user_phone = '15807610521'
token = '9fd8f71b04d3c8276dcd4601cb5da072'

# biz_user_phone = '18589059214'
# token = 'd832d6f1f1c079a8fdaf2cedeb4f2b90'

admin_headers = {
    'token': token_format.format(phone_number=phone_number, sms_code=sms_code)
}

user_headers = {
    'token': token
}


# @pytest.mark.skip
def test_set_admin_customer_token():
    # data = {
    #     'role': 'customer',
    #     'customer_id': 30,
    #     'w_id': 12,
    #     'biz_id': 6,
    # }
    data = {
        'role': ['coach'],
        'coach_id': 2,
    }
    phone_number = '18589059214'
    r = requests.post(
        base_url + '/user/dev_login/' + phone_number, json=data)
    pprint(r.json())
    assert r.status_code == 200
# test_set_admin_customer_token()


def test_set_admin_coach_token():
    data = {
        'role': 'coach',
        'coach_id': 2,
        'w_id': 2,
        'biz_id': 6,
    }
    r = requests.post(
        base_url + '/user/dev_login/' + '18589059214', json=data)
    pprint(r.json())
    assert r.status_code == 200
# test_set_admin_coach_token()


def test_biz_user_login():
    data = {
        'phone_number': biz_user_phone,
        'password': '12345678'
    }
    r = requests.post(
        base_url + '/biz_user/login', json=data)
    pprint(r.json())
    assert 200 == r.status_code


def test_generate_biz_user():
    data = {
        'phone_number': biz_user_phone,
        'password': 'yilijianshen'
    }
    r = requests.post(
        base_url + '/biz_user/admin', json=data, headers=admin_headers)
    pprint(r.json())
    assert r.status_code == 200


def test_hid():
    salt = 'Blue_Lotus_Store'
    hash_ids = Hashids(salt=salt + '-wx_authorizer')
    h_id = hash_ids.encode(3)
    print('h_id', h_id)


def test_get_apps():
    r = requests.get(
        base_url + '/biz_list', headers=user_headers)
    pprint(r.json())
    assert r.status_code == 200


def test_store_biz_hid():
    salt = 'Blue_Lotus_Store'
    hash_ids = Hashids(salt=salt + '-store_biz')
    h_id = hash_ids.encode(6)
    print('h_id', h_id)


biz_hid = 'ma'


def test_get_biz():
    r = requests.get(
        base_url + '/biz_list/{biz_hid}'.format(biz_hid=biz_hid), headers=user_headers)
    pprint(r.json())
    assert r.status_code == 200


def test_get_templates():
    """ 获取可选的模板 """
    r = requests.get(
        base_url + '/biz_list/{biz_hid}/templates'.format(biz_hid=biz_hid), headers=user_headers)
    pprint(r.json())
    assert r.status_code == 200


def test_get_actions():
    """ 获取上线流程 """
    r = requests.get(
        base_url + '/biz_list/{biz_hid}/actions'.format(biz_hid=biz_hid), headers=user_headers)
    pprint(r.json())
    assert r.status_code == 200


def test_set_template():
    """ 设置模板 """
    json_data = {
        'template_id': 1
    }
    r = requests.post(
        base_url + '/biz_list/{biz_hid}/actions/set_template'.format(biz_hid=biz_hid),
        json=json_data, headers=user_headers)
    pprint(r.json())
    assert r.status_code == 200


def test_submit_biz():
    """ 提交审核 """
    r = requests.post(
        base_url + '/biz_list/{biz_hid}/actions/submit'.format(biz_hid=biz_hid), headers=user_headers)
    pprint(r.json())
    assert r.status_code == 200


def test_get_wx_templates():
    app_id = 'wx862c80b960ce0195'
    client = component.get_client_by_appid(app_id)
    data = {
        'offset': 0,
        'count': 10,
    }
    r = requests.post('https://api.weixin.qq.com/cgi-bin/wxopen/template/list?access_token=' + client.access_token, json=data)
    pprint(r.json())
    assert r.status_code == 200
# test_get_wx_templates()


def test_delete_template():
    template_id = "tLAyJnIhXoc76gNHG_br-dX9UWcbpw1M_kd8_qM7h3o"
    app_id = 'wx862c80b960ce0195'
    client = component.get_client_by_appid(app_id)
    data = {
        'template_id': template_id
    }
    r = requests.post('https://api.weixin.qq.com/cgi-bin/wxopen/template/del?access_token=' + client.access_token,
                      json=data)
    pprint(r.json())
    assert r.status_code == 200
# test_delete_template()


def test_get_templates_keywords():
    app_id = 'wx862c80b960ce0195'
    client = component.get_client_by_appid(app_id)
    data = {
        'id': 'AT0218'
    }
    r = requests.post(
        'https://api.weixin.qq.com/cgi-bin/wxopen/template/library/get?access_token=' + client.access_token, json=data)
    pprint(r.json())
    assert r.status_code == 200
# test_get_templates_keywords()


def test_del_expired_form():
    open_id = 'otQM341gGajxhMmCdwySxiwcE6Hs'
    forms = form_redis_store.lrange(open_id, 0, -1)
    expired = []  # 已经过期的下标
    print('------expired---------')
    print(expired)

    for index, b_form_data in enumerate(forms):
        form_data = b_form_data.decode('utf-8').replace("'", '"')
        form_data = json.loads(form_data)
        expire = form_data.get('expire')
        # if int(time.time()) > expire:
        if 1530000001 < expire:
            # 过期
            # expired.append(index)
            form_redis_store.lset(open_id, index, 'del')
    # 删除
    form_redis_store.lrem(open_id, 0, 'del')
    print('----------------删除----------------')
# test_del_expired_form()


def test_send_template_message():
    open_id = 'oVzH64haUM0fSI2KhQ9RFEXWvUbE'
    app_id = 'wx862c80b960ce0195'
    # template_id = cfg['TEMPLATE_ID'][app_id]['CANCEL']
    client = component.get_client_by_appid(app_id)
    today = datetime.today()
    # data = {
    #     "touser": open_id,
    #     "template_id": template_id,
    #     "page": "pages/user/index",
    #     "form_id": "b061d87f8da7af2ad63c78718c2c2db8",
    #     "data": {
    #         "keyword1": {
    #             "value": "西乡"
    #         },
    #         "keyword2": {
    #             "value": today.strftime("%Y年%m月%d日")
    #         }
    #     },
    # }
    data = {
        'touser': open_id,
        'template_id': cfg['TEMPLATE_ID'][app_id]['CONFIRMED'],
        'page': 'pages/reservation/index',
        'form_id': 'fb0aeca9dda8920c3ea1b53f1b23f6eb',
        'data': {
            'keyword1': {
                'value': "李莉"
            },
            'keyword2': {
                'value': '7月3日 14:00-15:00'
            },
            'keyword3': {
                'value': '您有新的会员预约待确认,快去处理吧！'
            }
        },
        "emphasis_keyword": "keyword1.DATA"
    }

    r = requests.post(
        "https://api.weixin.qq.com/cgi-bin/message/wxopen/template/send?access_token=" + client.access_token,
        json=data)
    # form_pool.pop(index)
    pprint(r.json())
    assert r.status_code == 200
# test_send_template_message()


def test_add_template():
    app_id = 'wx862c80b960ce0195'
    client = component.get_client_by_appid(app_id)
    data = {
        "id": "AT0218",
        "keyword_id_list": [13, 7, 21]

    }
    r = requests.post(
        "https://api.weixin.qq.com/cgi-bin/wxopen/template/add?access_token=" + client.access_token,
        json=data)
    pprint(r.json())
    assert r.status_code == 200
# test_add_template()


def test_delete():
    a = {'id': 1, "name": 'test'}
    b = {'id': 1, "name": 'test'}
    c = [a, b]
    d = []
    for i in c:
        if i not in d:
            d.append(i)
    print(d)
    return d
# test_delete()


def test_get_common_params():
    secret_id = cfg['tencent_video']['secret_id']
    secret_key = cfg['tencent_video']['secret_key']

    current = int(time.time())
    expired = current + 60 * 10  # 十分钟有效期
    random = randint(1, pow(2, 32))

    SecretId = 'AKIDz8krbsJ5yKBZQpn74WFkmLPx3gnPhESA'
    SecretKey = 'Gu5t9xGARNpq86cd98joQYCN3Cozk1qA'

    # original = 'secretId={}&currentTimeStamp={}&expireTime={}&random={}'.format(secret_id, current, expired, random)
    #
    # h = hmac.new(secret_key.encode('utf-8'), original.encode('utf-8'), sha)
    # signature = base64.b64encode(h.digest() + bytes(original, 'utf-8')).decode('utf-8')

    s = "GETvod.api.qcloud.com/v2/index.php?" \
        "Action=GetVideoInfo" \
        "&file_id=5285890781089628300" \
        "&Nonce={Nonce}" \
        "&Region=gz" \
        "&SecretId={SecretId}" \
        "&SignatureMethod=HmacSHA256" \
        "&Timestamp={current}".format(
        current=current, Nonce=random, SecretId=secret_id
    )

    b = "Action=GetVideoInfo" \
    "&file_id=5285890781089628300" \
    "&Nonce={Nonce}" \
    "&Region=gz" \
    "&SecretId={SecretId}" \
    "&SignatureMethod=HmacSHA256" \
    "&Timestamp={current}".format(
        current=current, Nonce=random, SecretId=secret_id
    )

    t = """Action=DescribeInstances&InstanceIds.0=ins-09dx96dg&Nonce=11886&Region=ap-guangzhou&SecretId=AKIDz8krbsJ5yKBZQpn74WFkmLPx3gnPhESA&SignatureMethod=HmacSHA256&Timestamp=1465185768"""

    t_s = "GETcvm.api.qcloud.com/v2/index.php?" + t

    h = hmac.new(secret_key.encode('utf-8'), s.encode('utf-8'), sha256)
    # n_signature = base64.b64encode(h.digest() + bytes(s, 'utf-8')).decode('utf-8')
    n_signature = base64.b64encode(h.digest()).decode('utf-8')
    print(n_signature)
    n_s = quote(n_signature)
    f = quote("file_id=5285890781089628300")

    url = "https://vod.api.qcloud.com/v2/index.php?" \
          "Action=GetVideoInfo" \
          "&file_id=5285890781089628300" \
          "&Nonce={Nonce}" \
          "&Region=gz" \
          "&SecretId={SecretId}" \
          "&SignatureMethod=HmacSHA256" \
          "&Timestamp={current}" \
          "&Signature={Signature}" \
          .format(
        Nonce=random, SecretId=secret_id, current=current, Signature=n_s
    )

    # url = "https://vod.api.qcloud.com/v2/index.php?" \
    #       "Action=GetVideoInfo" + "&"\
    #       + f + '&' + s + "&Signature=" + n_s

    print(url)
    r = requests.get(url)
    res = r.json()
    print(res)

test_get_common_params()


def test_get_video_info():
    file_id = '5285890781083969711'
    # common_params = "&SecretId=AKIDzOo5TC4bJrEUcap0TmureGhy40lQoDLO&Region=gz&Timestamp=1534153596&Nonce=3749992598&Signature=0YsGEzgJKI01cCVrks9eAhNRM8pzZWNyZXRJZD1BS0lEek9vNVRDNGJKckVVY2FwMFRtdXJlR2h5NDBsUW9ETE8mY3VycmVudFRpbWVTdGFtcD0xNTM0MTUzNTk2JmV4cGlyZVRpbWU9MTUzNDE1NDE5NiZyYW5kb209Mzc0OTk5MjU5OA=="
    # base_url = 'https://vod.api.qcloud.com/v2/index.php?Action=GetVideoInfo'
    # url = base_url + "&fileId={file_id}&COMMON_PARAMS={common_params}".format(file_id=file_id,
    #                                                                           common_params=common_params)
    # r = requests.get(url)
    # res = r.json()
    # print(res)
    # return res
# test_get_video_info()