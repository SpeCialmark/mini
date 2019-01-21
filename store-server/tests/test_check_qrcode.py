import requests
from PIL import Image, ImageDraw, ImageFont

from store.domain.models import Qrcode, StoreBiz
from store.domain.wxapp import CheckInQrcode


def test_get_check_qrcode():
    biz_id = 6
    store_biz: StoreBiz = StoreBiz.query.filter(StoreBiz.id == biz_id).first()
    qrcode: Qrcode = CheckInQrcode(app_id=store_biz.wx_authorizer.app_id).get()
    qr_code_url = qrcode.get_brief()['url']
    qr_code = Image.open(requests.get(qr_code_url, stream=True).raw).convert('RGBA')
    qr_code.show()


test_get_check_qrcode()
