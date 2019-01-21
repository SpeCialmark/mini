import io
import sys
import requests
from PIL import Image, ImageDraw, ImageFont

from store.utils.picture_processing import circle

base_path = sys.path[0] + '/res/'


def generate_salesman_poster(salesman, store, store_name, qrcode):
    address = store.get_address()
    image_url = store.cards[0].get('images')[0]
    if not image_url:
        image_url = store.cards[1].get('images')[0]

    image = Image.open(requests.get(image_url, stream=True).raw).convert('RGBA')
    avatar = Image.open(requests.get(salesman.avatar, stream=True).raw).convert('RGBA')
    # qr_code = Image.open(io.BytesIO(qrcode.content)).convert('RGBA')
    qr_code = Image.open(requests.get(qrcode.get_brief()['url'], stream=True).raw).convert('RGBA')
    phone_icon = Image.open(base_path + 'phone.png').convert('RGBA')
    wechat_icon = Image.open(base_path + 'wechat.png').convert('RGBA')
    address_icon = Image.open(base_path + 'address.png').convert('RGBA')

    image = image.resize((750, int(750 * 4/9)), Image.ANTIALIAS)  # 将海报的图片缩放到750px
    back_ground = Image.new(mode='RGBA', size=(image.size[0], 932), color='white')

    avatar = avatar.resize((100, 100), Image.ANTIALIAS)
    qr_code = qr_code.resize((int(qr_code.size[0] * 0.4), int(qr_code.size[1] * 0.4)), Image.ANTIALIAS)

    i_a = image.split()[3]
    a_a = avatar.split()[3]
    q_a = qr_code.split()[3]
    p_a = phone_icon.split()[3]
    w_a = wechat_icon.split()[3]
    ad_a = address_icon.split()[3]

    back_ground.paste(image, (0, 0), mask=i_a)
    back_ground.paste(avatar, (int(back_ground.size[0]*8/10), image.size[1]+100), mask=a_a)
    back_ground.paste(qr_code, (int(back_ground.size[0]*7/10), image.size[1]+310), mask=q_a)
    back_ground.paste(phone_icon, (60, image.size[1] + 310), mask=p_a)
    back_ground.paste(wechat_icon, (60, image.size[1] + 370), mask=w_a)
    back_ground.paste(address_icon, (60, image.size[1] + 430), mask=ad_a)

    store_name_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=28)
    name_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=36)
    title_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=28)
    phone_number_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=28)
    wechat_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=28)
    address_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=24)

    word_draw = ImageDraw.Draw(back_ground)
    # store_name = '修改视频文件的描述信息，包括分类、名称、描述等。'  # for test
    word_draw.text((int(back_ground.size[0]/2-(len(store_name)*28)/2), image.size[1]+10), store_name, font=store_name_font, fill='#666666')
    word_draw.text((60, image.size[1]+100), salesman.name, font=name_font, fill='#101010')
    word_draw.text((60, image.size[1]+156), salesman.title, font=title_font, fill='#666666')

    line_size = (30, image.size[1] + 232, back_ground.size[0] - 30, image.size[1] + 232)
    word_draw.line(line_size, fill='#f8f8f8', width=2)  # 分割线

    word_draw.text((120, image.size[1] + 310), salesman.phone_number, font=phone_number_font, fill='#101010')
    word_draw.text((120, image.size[1] + 370), salesman.wechat, font=wechat_font, fill='#101010')
    # address = '修改视频文件的描述信息，包括分类、名称、描述等。'  # for test
    if len(address) > 12:
        address = address[:12] + '\n' + address[12:]
    elif len(address) > 24:
        address = address[:12] + '\n' + address[12:24] + '\n' + address[24:]
    word_draw.text((120, image.size[1] + 430), address, font=address_font, fill='#666666')

    share_pic = back_ground.convert(mode='RGB')
    return share_pic


def generate_salesman_share_cover(salesman, store, store_name, head_img_url):
    # 转发时的图片(替代微信转发自动截图)

    back_ground = Image.open(base_path + 'share_back_ground.png').convert('RGBA')
    head_img = Image.open(requests.get(head_img_url, stream=True).raw).convert('RGBA')
    avatar = Image.open(requests.get(salesman.avatar, stream=True).raw).convert('RGBA')

    head_img = head_img.resize((130, 130), Image.ANTIALIAS)
    avatar = avatar.resize((100, 100), Image.ANTIALIAS)
    avatar_border = Image.new("RGBA", (avatar.size[0] + 2, avatar.size[1] + 2), '#ffffff')  # 头像白边
    head_img = circle(head_img, 60)
    h_a = head_img.split()[3]
    a_a = avatar.split()[3]

    back_ground.paste(head_img, (93, 192), mask=h_a)
    back_ground.paste(avatar_border, (596, 323))
    back_ground.paste(avatar, (597, 324), mask=a_a)

    store_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=36)  # 37444a
    phone_number_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=24)  # ecf0f0
    wechat_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=24)  # ecf0f0
    address_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=20)  # ecf0f0
    name_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=52)  # f78314
    title_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=28)  # ecf0f0

    word_draw = ImageDraw.Draw(back_ground)
    name_box = (int(back_ground.size[0]*0.71 - len(salesman.name)*52/2), 90)
    title_box = (int(back_ground.size[0]*0.71 - len(salesman.title)*28/2), 165)
    word_draw.text(name_box, salesman.name, font=name_font, fill='#f78314')
    word_draw.text(title_box, salesman.title, font=title_font, fill='#ecf0f0')
    word_draw.text((347, 324), salesman.phone_number, font=phone_number_font, fill='#ecf0f0')
    word_draw.text((347, 374), salesman.wechat, font=wechat_font, fill='#ecf0f0')

    address = store.get_address()
    if len(address) > 11:
        address = address[:11] + '\n' + address[11:]
    elif len(address) > 22:
        address = address[:11] + '\n' + address[11:22] + '\n' + address[22:]
    word_draw.text((347, 421), address, font=address_font, fill='#ecf0f0')

    if 9 > len(store_name) > 6:
        store_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=32)  # 37444a
    elif len(store_name) >= 9:
        store_font = ImageFont.truetype(base_path + 'font/msyh.ttf', size=28)  # 37444a
    store_name_box = (int(back_ground.size[0] * 0.2 - len(store_name) * store_font.size / 2), 337)
    word_draw.text(store_name_box, store_name, font=store_font, fill='#37444a')

    share_cover = back_ground.convert(mode='RGB')
    return share_cover


class AccessType:
    Qrcode = 'qrcode'  # 通过二维码访问
    Share = 'share'  # 通过分享页面访问
    Home = 'home'  # 通过主页访问
