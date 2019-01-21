import pytest
import os
from http import HTTPStatus
import ruamel.yaml
import requests
import json
from pprint import pprint


ENV = 'dev'   # dev or prod

# base_url = 'https://store.11train.com/api/v1' if ENV == 'prod' else 'http://119.23.15.139:5006/api/v1'
# base_url = 'http://localhost:5006/api/v1'
base_url = 'https://sz.11train.com/api/v1'

_dir = os.path.abspath(os.path.dirname(__file__))
folder = '/home/ae86/workoutprog/store/tests/'


def get_admin_token():
    return '786085'


def admin_post(tree, nodes):
    for n in tree[nodes]:
        action = Action(n, base_url + '/' + nodes + '/admin')
        r_insert = action.insert()
        assert HTTPStatus.OK == r_insert.status_code
        pprint(r_insert.json())


# @pytest.mark.skip
def test_store():
    file = 'store.yml'
    tree = ruamel.yaml.round_trip_load(open(folder + file), preserve_quotes=True)
    admin_post(tree, 'store')


def test_course():
    file = 'course.yml'
    tree = ruamel.yaml.round_trip_load(open(folder + file), preserve_quotes=True)
    admin_post(tree, 'courses')


def test_coach():
    file = 'coach.yml'
    tree = ruamel.yaml.round_trip_load(open(folder + file), preserve_quotes=True)
    admin_post(tree, 'coaches')


def test_manager():
    file = 'manager.yml'
    tree = ruamel.yaml.round_trip_load(open(folder + file), preserve_quotes=True)
    admin_post(tree, 'manager')


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

    def get_headers(self):
        return {
            'token': get_admin_token()
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
