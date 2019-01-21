import random

from random import randint
# from flask import Blueprint, g, jsonify, request


def get_random_avatar():
    avatars = [
        'http://oss.11train.com/user/avatar/c_avatar1.png',
        'http://oss.11train.com/user/avatar/c_avatar2.png',
        'http://oss.11train.com/user/avatar/c_avatar3.png',
        'http://oss.11train.com/user/avatar/c_avatar4.png',
        'http://oss.11train.com/user/avatar/c_avatar5.png',
        'http://oss.11train.com/user/avatar/c_avatar6.png',
    ]
    max_index = len(avatars) - 1
    index = randint(0, max_index)
    return avatars[index]


def get_random_checkin_img():
    images_types = [{'type': '.jpg', 'sum': 57}, {'type': '.png', 'sum': 112}]
    images_base_url = 'http://oss.11train.com/p/checkin/'

    images_type = random.choice(images_types)  # {'type': '.jpg', 'sum': 57} or {'type': '.png', 'sum': 112}
    images = [images_base_url+str(i)+images_type.get('type') for i in range(1, images_type.get('sum')+1)]

    max_index = len(images) - 1
    index = randint(0, max_index)
    return images[index]


def get_random_high_img():
    images_base_url = 'http://oss.11train.com/p/checkin/high/{num}.jpg'
    num = randint(0, 112)
    return images_base_url.format(num=num)


def get_random_width_img():
    images_base_url = 'http://oss.11train.com/p/checkin/width/{num}.png'
    num = randint(0, 13)
    return images_base_url.format(num=num)


def get_random_excitation():
    excitations = [
        '放弃可以找到一万个理由，坚持只需一个信念！',
        '要么挥汗如雨，要么滚回家。',
        '想要放弃了的时候，想想当初为什么开始？',
        '我努力过了，不管成功与否我不后悔。',
        '只有汗水和鲜血浇铸出来的才是真汉子。',
        '如果你中途退出，那就不要再回来——致放弃的人',
        '你只有非常努力，才能看起来毫不费力。',
        '既然没有俊美的外表，那就努力去拥有野兽般的身体吧！',
        '撑过是天堂，放弃是地狱！'
    ]
    max_index = len(excitations) - 1
    index = randint(0, max_index)
    return excitations[index]
