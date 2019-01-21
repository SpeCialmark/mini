import pytest
from store.main_app import create_main_app
# from store.reservation.apis import generate_seats
import requests
from pprint import pprint
from .test_queue import q

# @pytest.yield_fixture(scope="session")
# def app_ctx():
#     print('***create app***')
#     app = create_main_app()
#     ctx = app.app_context()
#     ctx.push()
#     # 设置好绝对路径,这样无论从哪里运行都ok
#     yield app
#     ctx.pop()
#     print('***pop app***')


base_url = 'http://sz.11train.com:80/api/v1'

token_format = '{phone_number}:{sms_code}'
phone_number = '18589059214'
sms_code = '755758'     # 查看手机


user_headers = {
    'token': token_format.format(phone_number=phone_number, sms_code=sms_code)
}


@pytest.mark.skip
def test_set_admin_customer_token():
    data = {
        'role': 'customer',
        'customer_id': 2,
        'w_id': 2,
        'biz_id': 6,
    }
    r = requests.post(
        base_url + '/user/dev_login/' + phone_number, json=data)
    pprint(r.json())
    assert r.status_code == 200


# @pytest.mark.skip
# def test_seat_helper():
    # seats = generate_seats()
    # for s in seats:
    #     print(s)


@pytest.mark.skip
def test_get_coaches():
    r = requests.get(
        base_url + '/reservations/coaches', headers=user_headers)
    pprint(r.json())
    assert r.status_code == 200


@pytest.mark.skip
def test_get_coaches_day():
    r = requests.get(
        base_url + '/reservations/coaches/{c_id}/days/{d_id}'.format(c_id='Rn', d_id='20180701'),
        headers=user_headers
    )
    pprint(r.json())
    assert r.status_code == 200


# @pytest.mark.skip
def test_post_reserved():
    data = {
        'duration': 30
    }
    r = requests.post(
        base_url + '/reservations/coaches/{c_id}/seats/{s_id}/reserve'.format(c_id='Rn', s_id='201808012030'),
        json=data, headers=user_headers
    )
    pprint(r.json())
    assert r.status_code == 200


@pytest.mark.skip
def test_get_trainees():
    r = requests.get(
        base_url + "/trainees/", headers=user_headers
    )
    pprint(r.json())
    assert r.status_code == 200


# def test_put_queue():
#     q.put(1)
#     q.put(2)
#     q.put(2)
#     size = q.qsize()
#     pprint(size)
