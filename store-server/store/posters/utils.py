from datetime import datetime, timedelta

import io
import sys

import requests
from PIL import Image, ImageDraw, ImageFont
from concurrent import futures

from store.check_in.apis import RecordUtil
from store.domain.models import Qrcode, CheckIn
from store.utils.picture_processing import round_rectangle, circle
from store.utils import time_processing as tp

base_path = sys.path[0] + '/res/'


def get_avatar(avatar_url):
    avatar = Image.open(requests.get(avatar_url, stream=True).raw).convert('RGBA')
    avatar = avatar.resize((160, 160), Image.ANTIALIAS)
    avatar = circle(avatar, 80)
    return avatar


def get_goods_image(goods_image):
    goods = Image.open(requests.get(goods_image, stream=True).raw).convert('RGBA')
    return goods


def generate_group_report_poster(qrcode: Qrcode, activity_title, goods_image_url, avatar_url):
    fingerprint = Image.open(base_path + 'fingerprint.png').convert('RGBA')  # 指纹
    qr_code = Image.open(io.BytesIO(qrcode.content)).convert('RGBA')
    if len(activity_title) > 19:
        activity_title = activity_title[:19] + "\n" + activity_title[19:]
    avatar, goods_image = None, None
    with futures.ThreadPoolExecutor(max_workers=2) as executor:
        avatar_f = executor.submit(get_avatar, avatar_url)
        goods_f = executor.submit(get_goods_image, goods_image_url)
        fs = {avatar_f: 'avatar', goods_f: 'goods'}

        for f in futures.as_completed(fs):
            if fs[f] == 'avatar':
                avatar = f.result()
            elif fs[f] == 'goods':
                goods_image = f.result()
    if 9/4 > goods_image.size[0]/goods_image.size[1] >= 4/3:
        white_back_ground = round_rectangle((670, 1110), 10, '#ffffff')  # 卡片背景
        goods_image = goods_image.resize((610, 456), Image.ANTIALIAS)
    else:
        white_back_ground = round_rectangle((670, 926), 10, '#ffffff')  # 卡片背景
        goods_image = goods_image.resize((610, 272), Image.ANTIALIAS)

    qr_code = qr_code.resize((160, 160), Image.ANTIALIAS)
    fingerprint = fingerprint.resize((140, 140), Image.ANTIALIAS)
    back_ground = Image.new("RGBA", (750, 1334), '#ffbb3a')
    white_avatar = Image.new("RGBA", (avatar.size[0] + 10, avatar.size[1] + 10), '#ffffff')  # 头像白边
    white_avatar = circle(white_avatar, 85)

    a_a = avatar.split()[3]
    wa_a = white_avatar.split()[3]
    g_a = goods_image.split()[3]
    q_a = qr_code.split()[3]
    f_a = fingerprint.split()[3]
    w_a = white_back_ground.split()[3]

    qr_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=28)  # 长按识别小程序码大小28px
    invite_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=32)  # invite_str
    title_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=32)  # title大小32px 101010

    qr_str1 = '长按识别小程序码'  # 101010
    qr_str2 = '查看活动详情'
    invite_str1 = '我正在参加这个超值的拼团活动'  # fd242c
    invite_str2 = '你也一起来拿优惠吧!'

    back_ground.paste(white_back_ground, (40, 150), mask=w_a)
    back_ground.paste(white_avatar, (int(back_ground.size[0]/2 - white_avatar.size[0]/2), 66), mask=wa_a)
    back_ground.paste(avatar, (int(back_ground.size[0]/2 - avatar.size[0]/2), 70), mask=a_a)
    back_ground.paste(goods_image, (70, 418), mask=g_a)
    back_ground.paste(fingerprint, (70, int(150+white_back_ground.size[1] * 8/10)), mask=f_a)
    back_ground.paste(qr_code, (520, int(150+white_back_ground.size[1] * 8/10)), mask=q_a)

    word_draw = ImageDraw.Draw(back_ground)
    word_draw.text((int(back_ground.size[0]/2-int(len(invite_str1)/2*invite_font.size)), 260), invite_str1, font=invite_font, fill='#fd242c')
    word_draw.text((int(back_ground.size[0]/2-int(len(invite_str2)/2*invite_font.size)), 300), invite_str2, font=invite_font, fill='#fd242c')
    word_draw.text((70, int(100+white_back_ground.size[1] * 7/10)), activity_title, font=title_font, fill='#101010')
    word_draw.text((int(back_ground.size[0]/2-int(len(qr_str1)/2*qr_font.size)), int(200+white_back_ground.size[1] * 8/10)), qr_str1, font=qr_font, fill='#101010')
    word_draw.text((int(back_ground.size[0]/2-int(len(qr_str2)/2*qr_font.size)), int(240+white_back_ground.size[1] * 8/10)), qr_str2, font=qr_font, fill='#101010')

    poster = back_ground.convert(mode='RGBA')

    return poster


def generate_check_in_poster(qrcode, customer, image_url, step_count, record_data, check_in: CheckIn, store_name):
    if not record_data:
        record_data = {}
    # 选择在分享中添加健康数据记录的
    record_util = RecordUtil(check_in.biz_id, check_in.customer_id)
    qr_code = Image.open(requests.get(qrcode.get_brief()['url'], stream=True).raw).convert('RGBA')
    fingerprint = Image.open(base_path + 'fingerprint.png').convert('RGBA')  # 指纹

    avatar, image = None, None
    with futures.ThreadPoolExecutor(max_workers=2) as executor:
        avatar_f = executor.submit(get_c_avatar, customer.avatar)
        image_f = executor.submit(get_c_image, image_url)
        fs = {avatar_f: 'avatar', image_f: 'image'}

        for f in futures.as_completed(fs):
            if fs[f] == 'avatar':
                avatar = f.result()
            elif fs[f] == 'image':
                image = f.result()

    fingerprint = fingerprint.resize((100, 100), Image.ANTIALIAS)
    qr_code = qr_code.resize((120, 120), Image.ANTIALIAS)
    a_a = avatar.split()[3]
    q_a = qr_code.split()[3]
    f_a = fingerprint.split()[3]

    keep_str = '坚持健身'
    day_sum = record_util.get_sum_record()  # 累计健身天数
    month_sum = record_util.get_month_sum(datetime.today())  # 本月累计健身天数
    step_str = '今日走路%s步' % step_count
    month_str = '本月健身%s天' % month_sum
    date_str = check_in.check_in_date.strftime("%Y/%m/%d")
    bottom_str1 = '我在{store_name}健身'.format(store_name=store_name)
    bottom_str2 = '扫码跟我一起练!'

    day_font = ImageFont.truetype(base_path + 'font/arialbd.ttf', size=100)  # 大数字的大小100px
    date_font = ImageFont.truetype(base_path + 'font/arial.ttf', size=28)  # 小数字的大小28px
    keep_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=28)  # 坚持健身大小28px
    bottom_font = ImageFont.truetype(base_path + 'font/msyhbd.ttf', size=28)
    end_date = tp.get_day_max(datetime.today())
    start_date = tp.get_day_min(end_date - timedelta(days=15))
    if round(image.size[1]/image.size[0], 1) == 1.2:
        image = image.resize((750, 900), Image.ANTIALIAS)
        i_a = image.split()[3]
        # 长图
        mack = Image.open(base_path + 'material/mask_high.png').convert('RGBA')  # 蒙版
        mack = mack.resize((750, image.size[1]), Image.ANTIALIAS)
        m_a = mack.split()[3]
        back_ground = Image.new("RGBA", (750, image.size[1]+200), '#ffffff')
        back_ground.paste(image, (0, 0), mask=i_a)
        back_ground.paste(mack, (0, 0), mask=m_a)
        back_ground.paste(avatar, (40, int(image.size[1] * 2 / 10)), mask=a_a)
        back_ground.paste(fingerprint, (40, int((back_ground.size[1] - image.size[1])/2 + image.size[1] - fingerprint.size[1]/2)), mask=f_a)
        back_ground.paste(qr_code,
                          (int(back_ground.size[0] - qr_code.size[0] - 20),
                           int((back_ground.size[1] - image.size[1])/2 + image.size[1] - qr_code.size[1]/2)),
                          mask=q_a)

        word_draw = ImageDraw.Draw(back_ground)

        word_draw.text((40, int(image.size[1] * 2 / 10) + avatar.size[1] + keep_font.size), keep_str, font=keep_font, fill='#ffffff')
        word_draw.line(
            (40,
             int(image.size[1] * 2 / 10) + avatar.size[1] + 2 * keep_font.size + 20,
             40 + len(str(day_sum)) * (day_font.size / 2) + 2 * keep_font.size,
             int(image.size[1] * 2 / 10) + avatar.size[1] + 2 * keep_font.size + 20), width=2
        )  # 第1根线

        word_draw.text((40, int(image.size[1] * 2 / 10) + avatar.size[1] + 2 * keep_font.size + 20), str(day_sum), font=day_font, fill='#ffffff')
        word_draw.text(
            (40 + len(str(day_sum)) * (day_font.size / 2) + keep_font.size,
             int(image.size[1] * 2 / 10) + avatar.size[1] + 2 * keep_font.size + day_font.size - 20), '天', font=keep_font, fill='#ffffff'
        )

        line2_size = (40, int(image.size[1] * 2 / 10) + 2 * keep_font.size + day_font.size + day_font.size + 10)
        word_draw.line(
            (40,
             int(image.size[1] * 2 / 10) + 2 * keep_font.size + day_font.size + day_font.size + 10,
             40 + len(str(day_sum)) * (day_font.size / 2) + 2 * keep_font.size,
             int(image.size[1] * 2 / 10) + 2 * keep_font.size + day_font.size + day_font.size + 10), width=2
        )  # 第2根线

        word_draw.text((40, line2_size[1] + keep_font.size), date_str, font=date_font, fill='#ffffff')
        word_draw.text((40, line2_size[1] + 3*keep_font.size + 15), month_str, font=keep_font, fill='#ffffff')
        word_draw.text((40, line2_size[1] + 5*keep_font.size + 15), step_str, font=keep_font,
                       fill='#ffffff')

        # if record_data:
        #     weight_str = '近半月体重变化%.1f公斤' % BodyData.get_record_change(customer.id, start_date, end_date, Weight.name)
        #     word_draw.text((40, line2_size[1] + 7*keep_font.size + 15), weight_str, font=keep_font,
        #                    fill='#ffffff')
        #     bfp_str = '体脂率 %s' % record_data.get('bfp')
        #     word_draw.text((40, line2_size[1] + 9*keep_font.size + 15), bfp_str, font=keep_font,
        #                    fill='#ffffff')

        word_draw.text(
            (back_ground.size[0] / 2 - (len(bottom_str1) * bottom_font.size) / 2, image.size[1] + bottom_font.size + 20),
            bottom_str1,
            font=bottom_font, fill='#666666'
        )
        word_draw.text(
            (back_ground.size[0] / 2 - (len(bottom_str2) * bottom_font.size) / 2,
             image.size[1] + bottom_font.size + 60),
            bottom_str2,
            font=bottom_font, fill='#666666'
        )
    else:
        image.resize((750, 560), Image.ANTIALIAS)
        i_a = image.split()[3]
        # 宽图
        mack = Image.open(base_path + 'material/mask_width.png').convert('RGBA')  # 蒙版
        mack = mack.resize((750, image.size[1]), Image.ANTIALIAS)
        m_a = mack.split()[3]
        back_ground = Image.new('RGBA', (750, image.size[1]+200), '#ffffff')
        back_ground.paste(image, (0, 0), mask=i_a)
        back_ground.paste(mack, (0, 0), mask=m_a)
        back_ground.paste(fingerprint, (40, int(back_ground.size[1] * 9 / 11)), mask=f_a)
        back_ground.paste(
            qr_code, (int(back_ground.size[0] - qr_code.size[0] - 40), int(back_ground.size[1] * 9 / 11) - 20), mask=q_a
        )
        word_draw = ImageDraw.Draw(back_ground)
        word_draw.text((40, 20), keep_str, font=keep_font, fill='#ffffff')
        word_draw.line(
            (40, 64,
             40 + len(str(day_sum)) * (day_font.size / 2) + 2 * keep_font.size, 64), width=2)  # 第1根线

        word_draw.line(
            (40, 200,
             40 + len(str(day_sum)) * (day_font.size / 2) + 2 * keep_font.size, 200), width=2)  # 第2根线

        word_draw.text((40, int(image.size[1] * 1 / 11) + 30), str(day_sum), font=day_font, fill='#ffffff')
        word_draw.text(
            (40 + len(str(day_sum)) * (day_font.size / 2) + keep_font.size,
             int(image.size[1] * 1 / 11 + day_font.size)), '天', font=keep_font, fill='#ffffff'
        )
        word_draw.text((40, int(back_ground.size[1] * 3 / 10) - 20), date_str, font=date_font, fill='#ffffff')
        word_draw.text((40, int(image.size[1] * 7 / 10)), month_str, font=keep_font, fill='#ffffff')
        word_draw.text((40, int(image.size[1] * 7 / 10) + keep_font.size * 2), step_str, font=keep_font, fill='#ffffff')
        # if record_data:
        #     weight_str = '近半月体重变化%.1f公斤' % BodyData.get_record_change(customer.id, start_date, end_date, Weight.name)
        #     word_draw.text((40, int(image.size[1] * 7 / 10) + keep_font.size * 4), weight_str, font=keep_font,
        #                    fill='#ffffff')

        word_draw.text(
            (back_ground.size[0] / 2 - (len(bottom_str1) * keep_font.size) / 2, int(back_ground.size[1] * 8.3 / 10)),
            bottom_str1,
            font=bottom_font, fill='#666666'
        )
        word_draw.text(
            (back_ground.size[0] / 2 - (len(bottom_str2) * keep_font.size) / 2,
             int(back_ground.size[1] * 8.3 / 10) + keep_font.size + 20),
            bottom_str2,
            font=bottom_font, fill='#666666'
        )

    poster = back_ground.convert(mode='RGB')
    return poster


def get_c_avatar(avatar_url):
    # 将打开url类型的image改为此种方式,防止出现IOError cannot identify image file <_io.BytesIO object at 0x7f8dac6b0518>异常
    a_r = requests.get(avatar_url, stream=True)
    avatar = Image.open(io.BytesIO(a_r.content)).convert('RGBA')
    avatar = avatar.resize((80, 80), Image.ANTIALIAS)
    avatar = circle(avatar, 40)
    return avatar


def get_c_image(image_url):
    # 将打开url类型的image改为此种方式,防止出现IOError cannot identify image file <_io.BytesIO object at 0x7f8dac6b0518>异常
    image_r = requests.get(image_url, stream=True)
    image = Image.open(io.BytesIO(image_r.content)).convert('RGBA')
    return image
