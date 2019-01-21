import io
import sys
import requests
import tempfile
from PIL import Image, ImageDraw, ImageFont
from store.config import cfg, _env
from store.utils.oss import bucket


def generate_place_base(qrcode, place_name, place_hid, app_hid):
    qr_code = Image.open(requests.get(qrcode.get_brief()['url'], stream=True).raw).convert('RGBA')
    back_ground = Image.new(mode='RGBA', size=(1295, 1325), color='white')

    back_ground_size = back_ground.size
    qr_code_size = qr_code.size
    qr_code_x = int(round(back_ground_size[0] / 2 - qr_code_size[0] / 2))  # 居中
    qr_code_y = int(round(back_ground_size[1] / 9))

    qr_a = qr_code.split()[3]
    back_ground.paste(qr_code, (qr_code_x, qr_code_y), mask=qr_a)
    back_ground = back_ground.convert(mode='RGBA')

    word_draw = ImageDraw.Draw(back_ground)
    if len(place_name) > 10:
        font_size = 60
        str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
        str_x = back_ground.size[0] / 2 - (font_size * len(place_name) / 2)
        str_y = back_ground.size[1] * 0.8
    else:
        font_size = 100
        str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
        str_x = back_ground.size[0] / 2 - (font_size * len(place_name) / 2)
        str_y = back_ground.size[1] * 0.8
    word_draw.text((str_x, str_y), place_name, font=str_font, fill="#202123")

    tmp = save_png_temp_file(back_ground)

    file_name = 'place_{place_hid}'.format(place_hid=place_hid) + '.png'
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=app_hid, file_name=file_name)
    if _env == 'dev':
        key = 'dev/' + key
    bucket.put_object_from_file(key=key, filename=tmp.name, headers={'Content-Disposition': 'attachment'})
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    tmp.close()  # 删除临时文件
    return image_url


def save_png_temp_file(share_pic):
    # 文件保存
    share_pic_bytes = io.BytesIO()
    share_pic.save(share_pic_bytes, format='PNG')
    share_pic_bytes = share_pic_bytes.getvalue()
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(share_pic_bytes)
    tmp.seek(0)
    return tmp
