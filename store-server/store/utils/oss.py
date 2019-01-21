import oss2
from store.config import cfg

_in_tab = '0123456789abcdefghijklmnopqrstuvwxyz'
_out_tab = 'ubkr8w9vmae1czh75fsdgiyjq03olnt642xp'
_tran_tab = str.maketrans(_in_tab, _out_tab)
_rev_tab = str.maketrans(_out_tab, _in_tab)

_aliyun_oss = cfg['aliyun_oss']
_auth = oss2.Auth(_aliyun_oss['access_key'], _aliyun_oss['secret'])
bucket = oss2.Bucket(_auth, _aliyun_oss['endpoint_vpc'], _aliyun_oss['bucket'])

qrcode_path = _aliyun_oss['qrcode_path']


def encode_app_id(app_id: str):
    msg = app_id
    if app_id.startswith('wx'):
        msg = app_id[2:]
    encoded_msg = msg.translate(_tran_tab)
    return encoded_msg


def decode_app_id(encoded_msg: str):
    decoded = encoded_msg.translate(_rev_tab)
    if not decoded.startswith('wx'):
        return 'wx' + decoded
    else:
        return decoded
