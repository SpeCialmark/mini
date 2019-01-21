from collections import namedtuple

WxMsgTemplate = namedtuple('WxMsgTemplate', ['title', 'short_id', 'keyword_id_list'])

binding_template = WxMsgTemplate(
    title='绑定成功通知',
    short_id='AT0045',
    keyword_id_list=[2, 3, 6]
)

confirm_template = WxMsgTemplate(
    title='预约处理提醒',
    short_id='AT0218',
    keyword_id_list=[13, 7, 21]
)

reservation_template = WxMsgTemplate(
    title='预约成功通知',
    short_id='AT0104',
    keyword_id_list=[92, 51, 54]
)

cancel_template = WxMsgTemplate(
    title='预约取消通知',
    short_id='AT0117',
    keyword_id_list=[57, 53, 61]
)

group_success_template = WxMsgTemplate(
    title='拼团成功通知',
    short_id='AT0051',
    keyword_id_list=[1, 3, 26, 22, 43]

)

group_fail_template = WxMsgTemplate(
    title='拼团失败通知',
    short_id='AT0310',
    keyword_id_list=[1, 3, 12, 5, 17],
)

customer_seat_check_template = WxMsgTemplate(
    title='消耗课时通知',
    short_id='AT1791',
    keyword_id_list=[4, 12, 5, 7, 9]
)

coach_seat_check_template = WxMsgTemplate(
    title='消耗课时通知',
    short_id='AT1791',
    keyword_id_list=[4, 12, 5, 7, 1]
)

all_template = [binding_template, confirm_template, reservation_template, cancel_template,
                group_success_template, group_fail_template, customer_seat_check_template,
                coach_seat_check_template]
