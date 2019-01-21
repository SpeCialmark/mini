import pytest
import os
from http import HTTPStatus
import ruamel.yaml
import requests
import json
from pprint import pprint

ENV = 'dev'   # dev or prod

base_url = 'https://api.11train.com/api/v1' if ENV == 'prod' else 'http://sz.11train.com:81/api/v1'

_dir = os.path.abspath(os.path.dirname(__file__))
folder = _dir + '/exs/'


# @pytest.mark.skip
def test_exercisers():
    # for letter in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n',
    #                'o', 'p', 'r', 's', 't', 'u', 'v', 'w']:
    letter_list = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n',
                   'o', 'p', 'r', 's', 't', 'u', 'v', 'w']

    # letter_list = ['v']
    for letter in letter_list:
        file = f'ex_{letter}.yml'
        tree = ruamel.yaml.round_trip_load(open(folder + file), preserve_quotes=True)
        base_id = (ord(letter) - ord('a') + 1) * 10000
        admin_post(tree, 'exercises', base_id)
        ruamel.yaml.round_trip_dump(tree, open(folder + file, 'w'))


# @pytest.mark.skip
# def test_yoga():
#     file = f'yoga.yml'
#     tree = ruamel.yaml.round_trip_load(open(folder + file), preserve_quotes=True)
#     admin_post(tree, 'exercises')
#     ruamel.yaml.round_trip_dump(tree, open(folder + file, 'w'))


def upsert(tree, nodes, base_id):
    for n in tree[nodes]:
        action = Action(n, base_url + '/' + nodes, base_id)

        r_update = action.update()
        if r_update.status_code == HTTPStatus.OK:
            pass
        elif r_update.status_code == HTTPStatus.NOT_FOUND:
            r_insert = action.insert()
            print(r_insert.json())
            assert r_insert.status_code == HTTPStatus.OK
        else:
            print(r_update)
            raise ConnectionError()


def admin_post(tree, nodes, base_id):
    for n in tree[nodes]:
        action = Action(n, base_url + '/' + nodes + '/admin', base_id)

        r_insert = action.insert()
        print(r_insert.json())
        n['data']['related_exs'] = r_insert.json()


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
    def __init__(self, node, url, base_id):
        self.node = node
        self.url = url

    def get_headers(self):
        return {
            'token': '18688967466:032619'
        }

    def get_data(self):
        return self.node['data']

    def insert(self) -> requests.Response:
        data = self.get_data()
        print('==insert==')
        pprint(data)
        print('==insert==')
        headers = self.get_headers()
        print('==headers===')
        pprint(headers)
        print('==headers===')
        return requests.post(self.url, json=data, headers=headers)

    def update(self) -> requests.Response:
        data = self.get_data()
        return requests.put(self.url + '/' + str(data['id']), json=data, headers=self.get_headers())
