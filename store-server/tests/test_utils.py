import pytest
import os
from http import HTTPStatus
import ruamel.yaml
import requests
import json
import pprint
from datetime import datetime
from datetime import timedelta
from random import randint
from store.main_app import create_main_app
from store.utils.oss import encode_app_id, decode_app_id
from store.utils import time_processing as tp
import re


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


# @pytest.mark.skip
def test_time():
    now = datetime.now()
    days = []
    # days.append('今天' + now.strftime('%-m月%-d日'))
    # days.append('明天' + now.strftime('%-m月%-d日'))

    for ch, i in zip(['今天', '明天', '后天'], [0, 1, 2]):
        days.append(ch + (now + timedelta(days=i)).strftime('%-m月%-d日'))
    for i in range(3, 15):
        days.append((now + timedelta(days=i)).strftime('%-m月%-d日'))

    hhmm = []
    for i in range(6, 24):
        hhmm.append(str(i) + ':00')
        hhmm.append(str(i) + ':30')
    pprint.pprint(days)
    pprint.pprint(hhmm)


def test_encode():
    app_id = 'wx345sdgfasgdsdg'
    encode = encode_app_id(app_id)
    decode = decode_app_id(encode)
    print('encode', encode)
    print('decode', decode)
    assert decode == app_id


@pytest.mark.skip
def test_pop():
    for i in range(0, 100):
       get_random_avatar()


def get_random_avatar():
    avatars = [
        'http://oss.11train.com/user/avatar/c_avatar1.png',
        'http://oss.11train.com/user/avatar/c_avatar2.png',
        'http://oss.11train.com/user/avatar/c_avatar3.png',
        'http://oss.11train.com/user/avatar/c_avatar4.png',
        'http://oss.11train.com/user/avatar/c_avatar5.png',
        'http://oss.11train.com/user/avatar/c_avatar6.png',
    ]
    max_index = len(avatars) - 1
    index = randint(0, max_index)
    print(avatars[index])


def test_get_time():
    now = datetime.now()
    num = 6
    first_month = tp.get_last_n_early_month(now, num)
    pprint.pprint(first_month)
    max_week = 2
    first_sunday = tp.get_last_n_sunday(now, max_week)
    pprint.pprint(first_sunday)


def test_sort():
    a = 'send binding message to coach 1'
    b = re.search('to.*', a)
    pprint.pprint(b)
