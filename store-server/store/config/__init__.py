import os
import yaml
# from elasticapm.contrib.flask import ElasticAPM
# apm = ElasticAPM()

_env = os.environ.get('CFG_ENV')
_dir = os.path.abspath(os.path.dirname(__file__))
_config_path = os.path.abspath(os.path.join(_dir, os.pardir)) + '/config.yml'
_cfg_doc = yaml.load(open(_config_path))
_res_path_format = os.path.abspath(os.path.join(_dir, os.pardir)) + '/res/{directory}/{file_name}'


cfg = _cfg_doc[_env]


def get_res(directory, file_name):
    path = _res_path_format.format(directory=directory, file_name=file_name)
    doc = yaml.load(open(path))
    return doc
