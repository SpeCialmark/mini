import sys

import requests
from PIL import Image, ImageDraw, ImageFont

from store.check_in.apis import save_png_temp_file
from store.config import cfg, _env
from store.utils.oss import encode_app_id, bucket


def generate_check_in_cover(qrcode, nick_name, customer_app_id):
    qr_code_url = qrcode.get_brief()['url']

    qr_code = Image.open(requests.get(qr_code_url, stream=True).raw).convert('RGBA')
    back_ground = Image.open(sys.path[0] + '/res/new_qrcode_back_ground.png').convert("RGBA")

    back_ground = back_ground.resize((back_ground.size[0] * 2, back_ground.size[1] * 2))
    back_ground_size = back_ground.size

    qr_code = qr_code.resize((qr_code.size[0] * 2, qr_code.size[1] * 2))
    qr_code_size = qr_code.size
    qr_code_x = int(round(back_ground_size[0] / 2 - qr_code_size[0] / 2))  # 居中
    qr_code_y = int(round(back_ground_size[1] / 7))

    qr_a = qr_code.split()[3]
    back_ground.paste(qr_code, (qr_code_x, qr_code_y), mask=qr_a)
    back_ground = back_ground.convert(mode='RGBA')

    word_draw = ImageDraw.Draw(back_ground)
    # store_name = '毅力私人健身房毅力私人健身房'  # for test
    if len(nick_name) > 10:
        font_size = 180
        str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
        str_x = back_ground.size[0] / 2 - (font_size * len(nick_name) / 2)
        str_y = back_ground.size[1] * 0.8
    else:
        font_size = 240
        str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
        str_x = back_ground.size[0] / 2 - (font_size * len(nick_name) / 2)
        str_y = back_ground.size[1] * 0.8
    word_draw.text((str_x, str_y), nick_name, font=str_font, fill="#202123")

    tmp = save_png_temp_file(back_ground)

    app_hid = encode_app_id(customer_app_id)
    file_name = 'check_cover' + '.png'
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=app_hid, file_name=file_name)
    bucket.put_object_from_file(key=key, filename=tmp.name, headers={'Content-Disposition': 'attachment'})
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    tmp.close()  # 删除临时文件

    return image_url


def generate_release_cover(qr_code, nick_name, customer_app_id):
    qr_code_url = qr_code.get_brief()['url']

    qr_code = Image.open(requests.get(qr_code_url, stream=True).raw).convert('RGBA')
    back_ground = Image.open(sys.path[0] + '/res/release_cover_back_ground.png').convert("RGBA")

    back_ground = back_ground.resize((back_ground.size[0] * 2, back_ground.size[1] * 2))
    back_ground_size = back_ground.size
    qr_code = qr_code.resize((int(qr_code.size[0] * 2.7), int(qr_code.size[1] * 2.7)))
    qr_code_size = qr_code.size
    qr_code_x = int(round(back_ground_size[0] / 2 - qr_code_size[0] / 2))  # 居中
    qr_code_y = int(round(back_ground_size[1] / 3))
    qr_a = qr_code.split()[3]
    back_ground.paste(qr_code, (qr_code_x, qr_code_y), mask=qr_a)
    back_ground = back_ground.convert(mode='RGBA')

    word_draw = ImageDraw.Draw(back_ground)
    if len(nick_name) > 10:
        font_size = 180
        str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
        str_x = back_ground.size[0] / 2 - (font_size * len(nick_name) / 2)
        str_y = back_ground.size[1] * 0.85
    else:
        font_size = 240
        str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
        str_x = back_ground.size[0] / 2 - (font_size * len(nick_name) / 2)
        str_y = back_ground.size[1] * 0.85
    word_draw.text((str_x, str_y), nick_name, font=str_font, fill="#202123")

    search_font = ImageFont.truetype(sys.path[0] + '/res/font/LTQHGBK.TTF', size=192)
    search_xy = (580, 692)
    word_draw.text(search_xy, nick_name, font=search_font, fill="#878686")

    tmp = save_png_temp_file(back_ground)
    file_name = 'release_cover' + '.png'
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=encode_app_id(customer_app_id), file_name=file_name)
    bucket.put_object_from_file(key=key, filename=tmp.name, headers={'Content-Disposition': 'attachment'})
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    tmp.close()  # 删除临时文件

    return image_url


def generate_shake_cover(qrcode, nick_name, customer_app_id):
    qr_code_url = qrcode.get_brief()['url']

    qr_code = Image.open(requests.get(qr_code_url, stream=True).raw).convert('RGBA')
    back_ground = Image.open(sys.path[0] + '/res/shake_background.png').convert("RGBA")

    back_ground_size = back_ground.size

    qr_code = qr_code.resize((int(qr_code.size[0] * 2.5), int(qr_code.size[1] * 2.5)))
    qr_code_size = qr_code.size
    qr_code_x = int(round(back_ground_size[0] / 2 - qr_code_size[0] / 2))  # 居中
    qr_code_y = int(round(back_ground_size[1] * 3.5 / 10))

    qr_a = qr_code.split()[3]
    back_ground.paste(qr_code, (qr_code_x, qr_code_y), mask=qr_a)
    back_ground = back_ground.convert(mode='RGBA')

    word_draw = ImageDraw.Draw(back_ground)
    if len(nick_name) > 10:
        font_size = 180
        str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
        str_x = back_ground.size[0] / 2 - (font_size * len(nick_name) / 2)
        str_y = qr_code_y + qr_code.size[1] + 400
    else:
        font_size = 240
        str_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=font_size)
        str_x = back_ground.size[0] / 2 - (font_size * len(nick_name) / 2)
        str_y = qr_code_y + qr_code.size[1] + 350
    word_draw.text((str_x, str_y), nick_name, font=str_font, fill="#202123")

    tmp = save_png_temp_file(back_ground)

    app_hid = encode_app_id(customer_app_id)
    file_name = 'shake_cover' + '.png'
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=app_hid, file_name=file_name)
    if _env == 'dev':
        key = 'dev/' + key
    bucket.put_object_from_file(key=key, filename=tmp.name, headers={'Content-Disposition': 'attachment'})
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    tmp.close()  # 删除临时文件

    return image_url


def generate_registration_cover(qrcode, customer_app_id):
    qr_code_url = qrcode.get_brief()['url']
    qr_code = Image.open(requests.get(qr_code_url, stream=True).raw).convert('RGBA')
    back_ground = Image.new('RGBA', (3496, 4960), '#ffffff').convert('RGBA')  # 白底
    top = Image.new('RGBA', (3496, 1400), '#e67931').convert('RGBA')  # 顶部

    qr_code = qr_code.resize((int(qr_code.size[0] * 2.2), int(qr_code.size[1] * 2.2)))
    top_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=400)
    button_font = ImageFont.truetype(sys.path[0] + '/res/font/fzhtjt.TTF', size=250)

    top_str = '到店登记'
    button_str = '扫码一键登记'

    back_ground.paste(top, (0, 0))
    back_ground.paste(qr_code, (int(back_ground.size[0] / 2 - qr_code.size[0] / 2), top.size[1] + 400))

    word_draw = ImageDraw.Draw(back_ground)
    word_draw.text((int(back_ground.size[0] - len(top_str) * top_font.size) / 2, int(top.size[1] / 2 - top_font.size / 2)),
                   top_str, font=top_font, fill="#ffffff")

    word_draw.text((int(back_ground.size[0] - len(button_str) * button_font.size) / 2, int(back_ground.size[1] * 8 / 10)),
                   button_str, font=button_font, fill="#101010")

    tmp = save_png_temp_file(back_ground)
    app_hid = encode_app_id(customer_app_id)
    file_name = 'registration_cover' + '.png'
    key = cfg['aliyun_oss']['qrcode_path'].format(app_hid=app_hid, file_name=file_name)
    if _env == 'dev':
        key = 'dev/' + key
    bucket.put_object_from_file(key=key, filename=tmp.name, headers={'Content-Disposition': 'attachment'})
    image_url = cfg['aliyun_oss']['host'] + '/' + key
    tmp.close()  # 删除临时文件

    return image_url
