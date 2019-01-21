import requests
from http import HTTPStatus
import ruamel.yaml
import pytest
from hashids import Hashids
from pprint import pprint

base_url = 'https://store.11train.com/api/v1'

token_format = '{phone_number}:{sms_code}'
phone_number = '18688967466'
sms_code = '178067'     # 查看手机

headers = {
    'token': token_format.format(phone_number=phone_number, sms_code=sms_code)
}


folder = '/home/alice/11train/store-server/store/res/templates/'


# @pytest.mark.skip
def test_set_admin_token():
    data = {
        'role': 'admin',
        'admin_id': 1
    }
    r = requests.post(base_url + '/user/dev_login/' + phone_number, json=data)
    pprint(r.json())
    assert r.status_code == 200


def test_post_template():
    file = 'templates.yml'
    tree = ruamel.yaml.round_trip_load(open(folder + file), preserve_quotes=True)
    admin_post(tree, 'templates', base_url + '/codebase/templates')


def test_get_templates():
    r = requests.get(base_url + '/codebase/templates', headers=headers)
    assert HTTPStatus.OK == r.status_code
    pprint(r.json())


def test_update_template():
    json_data = {
        'title': '基础版'
    }
    r = requests.put(base_url + '/codebase/templates/1', json=json_data, headers=headers)
    assert HTTPStatus.OK == r.status_code
    pprint(r.json())


def admin_post(tree, nodes, url):
    for n in tree[nodes]:
        action = Action(n, url)
        r_insert = action.insert()
        assert HTTPStatus.OK == r_insert.status_code
        pprint(r_insert.json())


class Action:
    """
        trainers:
        - anchor: &superman
            id: ~   # 必须的
          data: &data
            nickname: 'superman'
          find:   # 非必须, 默认取data里的第一个键值对
            <<: *data
          insert:  # 非必须, 默认取data
            <<: *data
          update:  # 非必须, 默认取data
            <<: *data

    """
    def __init__(self, node, url):
        self.node = node
        self.url = url

    def get_data(self):
        return self.node['data']

    def insert(self) -> requests.Response:
        data = self.get_data()
        print('==insert==')
        pprint(data)
        print('==insert==')
        print('==headers===')
        pprint(headers)
        print('==headers===')
        return requests.post(self.url, json=data, headers=headers)

    def update(self) -> requests.Response:
        data = self.get_data()
        return requests.put(self.url + '/' + str(data['id']), json=data, headers=self.get_headers())

