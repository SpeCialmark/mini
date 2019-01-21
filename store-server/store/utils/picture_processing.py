import io
import tempfile

from PIL import Image, ImageDraw


def round_corner(radius, fill):
    """Draw a round corner"""
    corner = Image.new('RGBA', (radius, radius), "#ffffff")
    draw = ImageDraw.Draw(corner)
    draw.pieslice((0, 0, radius * 2, radius * 2), 180, 270, fill=fill)
    return corner


def round_rectangle(size, radius, fill):
    """Draw a rounded rectangle"""
    width, height = size
    rectangle = Image.new('RGBA', size, fill)
    corner = round_corner(radius, fill)
    rectangle.paste(corner, (0, 0))
    rectangle.paste(corner.rotate(90), (0, height - radius))  # Rotate the corner and paste it
    rectangle.paste(corner.rotate(180), (width - radius, height - radius))
    rectangle.paste(corner.rotate(270), (width - radius, 0))
    return rectangle


def circle(ima, r3):
    # 生成圆形
    size = ima.size
    # 因为是要圆形，所以需要正方形的图片
    r2 = min(size[0], size[1])
    if size[0] != size[1]:
        ima = ima.resize((r2, r2), Image.ANTIALIAS)
    # 最后生成圆的半径
    # r3 = 80
    imb = Image.new('RGBA', (r3 * 2, r3 * 2), (255, 255, 255, 0))
    pima = ima.load()  # 像素的访问对象
    pimb = imb.load()
    r = float(r2 / 2)  # 圆心横坐标
    for i in range(r2):
        for j in range(r2):
            lx = abs(i - r)  # 到圆心距离的横坐标
            ly = abs(j - r)  # 到圆心距离的纵坐标
            l = (pow(lx, 2) + pow(ly, 2)) ** 0.5  # 三角函数 半径
            if l < r3:
                pimb[i - (r - r3), j - (r - r3)] = pima[i, j]
    return imb


def save_jpg_temp_file(share_pic):
    # 文件保存
    share_pic_bytes = io.BytesIO()
    share_pic.save(share_pic_bytes, format='JPEG')
    share_pic_bytes = share_pic_bytes.getvalue()
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(share_pic_bytes)
    tmp.seek(0)
    return tmp


def save_png_temp_file(share_pic):
    # 文件保存
    share_pic_bytes = io.BytesIO()
    share_pic.save(share_pic_bytes, format='PNG')
    share_pic_bytes = share_pic_bytes.getvalue()
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(share_pic_bytes)
    tmp.seek(0)
    return tmp
