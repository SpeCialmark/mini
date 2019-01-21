from flask import Blueprint
from flask import jsonify, request, g
from store.domain.middle import roles_required
from store.domain.permission import get_permissions_name

blueprint = Blueprint('_permissions', __name__)


@blueprint.route('', methods=['GET'])
@roles_required()
def get_permissions():
    w_id = g.get('w_id')
    biz_id = g.get('biz_id')
    permissions = g.get('permission')
    permission_list = get_permissions_name(permissions, biz_id)

    return jsonify({
        'permission_list': permission_list
    })
