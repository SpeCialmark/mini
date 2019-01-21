from datetime import datetime
from store.database import db
from store.domain.models import WxAuthorizer


def update_authorizer(authorizer_appid, authorization_info, authorizer_info) -> WxAuthorizer:
    now = datetime.now()
    if authorization_info.get('authorizer_refresh_token'):
        refresh_token = authorization_info.get('authorizer_refresh_token')

    authorizer = WxAuthorizer.query.filter(WxAuthorizer.app_id == authorizer_appid).first()
    if not authorizer:
        authorizer = WxAuthorizer(
            app_id=authorizer_appid,
            created_at=now
        )
        db.session.add(authorizer)

    # 设置authorization_info
    authorizer.is_authorized = True
    authorizer.refresh_token = refresh_token
    authorizer.authorized_at = now  # 授权时间
    authorizer.func_info = authorization_info.get('func_info')

    # 设置authorizer_info
    authorizer.nick_name = authorizer_info.get('nick_name')
    authorizer.head_img = authorizer_info.get('head_img')
    authorizer.verify_type_info = authorizer_info.get('verify_type_info')
    authorizer.user_name = authorizer_info.get('user_name')
    authorizer.signature = authorizer_info.get('signature')
    authorizer.principal_name = authorizer_info.get('principal_name')
    authorizer.business_info = authorizer_info.get('business_info')
    authorizer.qrcode_url = authorizer_info.get('qrcode_url')
    authorizer.mini_program_info = authorizer_info.get('MiniProgramInfo')
    authorizer.authorizer_info = {'authorizer_info': authorizer_info}
    authorizer.modified_at = now
    db.session.commit()
    db.session.refresh(authorizer)
    return authorizer
