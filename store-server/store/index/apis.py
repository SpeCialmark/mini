from http import HTTPStatus

from flask import Blueprint
from flask import jsonify, request

from store.config import get_res

blueprint = Blueprint('_index', __name__)


@blueprint.route('', methods=['GET'])
def get_index():
    access_type = request.args.get('access_type', default='phone', type=str)
    index_data = get_res(directory='index', file_name='index.yml')
    if access_type == 'phone':
        banner = index_data['phone_banner']
    elif access_type == 'pc':
        banner = index_data['pc_banner']
    else:
        return jsonify(msg='类别错误'), HTTPStatus.BAD_REQUEST

    index = index_data['index']
    return jsonify({
        'index': index,
        'banner': banner
    })
