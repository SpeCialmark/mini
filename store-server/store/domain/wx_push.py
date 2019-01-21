from datetime import datetime
from typing import List

import requests
from sqlalchemy import and_
from store.database import db
from store.domain.models import WxMessage, WxOpenUser, Coach, Trainee, GroupReport, GroupMember, Store, StoreBiz, \
    Customer, ContractContent
from store.domain.cache import AppCache, CourseCache
from store.utils import time_processing as tp
from store.utils.sms import send_reservation_sms, send_group_fail_sms
from store.wxopen import component


def send_phone_message(wx_message):
    message_data = wx_message.data
    data = message_data.get('data')
    touser = message_data.get('touser')  # wx_open_id
    wx_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.wx_open_id == touser
    ).first()
    coach_id = wx_user.coach_id
    coach: Coach = Coach.query.filter(
        Coach.id == coach_id
    ).first()
    if coach:
        name = data.get('keyword1')['value']
        time = data.get('keyword2')['value']  # 2018年9月1日14:00-15:00
        phone_number = coach.phone_number
        result = send_reservation_sms(phone_number=phone_number, time=time[5:], name=name)
        executed_at = datetime.now()
        wx_message.executed_at = executed_at
        wx_message.result = result.decode('utf-8')
        wx_message.is_completed = True
        db.session.commit()
        return

    # 如果不是教练则说明发送的是拼团的模板消息
    customer: Customer = Customer.query.filter(
        Customer.id == wx_user.customer_id
    ).first()
    phone_number = customer.phone_number
    activity_name = data.get('keyword1')['value']
    app_name = AppCache(wx_user.app_id).get('nick_name') + '小程序'
    result = send_group_fail_sms(phone_number, activity_name, app_name)

    executed_at = datetime.now()
    wx_message.executed_at = executed_at
    wx_message.result = result.decode('utf-8')
    wx_message.is_completed = True
    db.session.commit()
    return


def push_message(wx_message, data, f):
    form_id = f.form_id
    app_id = f.app_id
    result = send_template_message(data, form_id, app_id)

    executed_at = datetime.now()
    wx_message.executed_at = executed_at
    wx_message.result = result
    wx_message.is_completed = True  # 发送完成后状态变更为True

    db.session.delete(f)
    db.session.commit()
    db.session.refresh(wx_message)
    return wx_message.result


def send_template_message(data, form_id, app_id):
    client = component.get_client_by_appid(app_id)
    data.update({'form_id': form_id})
    r = requests.post('https://api.weixin.qq.com/cgi-bin/message/wxopen/template/send?access_token=' + client.access_token,
                      json=data)
    result = r.json()
    return result


def queue_coach_binding_message(data):
    coach_open = data.get('coach_open')
    trainee = data.get('trainee')
    customer = data.get('customer')
    # 由于课时设置在BOSS端完成,因此绑定的模板消息跳转到学员列表页
    page = 'pages/member/index'  # 学员列表页
    # 提交绑定信息进入队列
    message_data = {
        'touser': coach_open.wx_open_id,
        'template_id': AppCache(coach_open.app_id).get('binding_tmp_id'),
        'page': page,
        'form_id': '{form_id}',
        'data': {
            'keyword1': {
                'value': trainee.name
            },
            'keyword2': {
                'value': datetime.now().strftime("%Y年%m月%d日 %H:%M")
            },
            'keyword3': {
                'value': customer.nick_name
            }
        },
        "emphasis_keyword": "keyword1.DATA"
    }
    wx_message = WxMessage(
        app_id=coach_open.app_id,
        open_id=coach_open.wx_open_id,
        task="send binding message to coach %d" % coach_open.coach_id,
        publish_at=datetime.now(),
        data=message_data,
        created_at=datetime.now(),
        is_completed=False
    )
    db.session.add(wx_message)
    db.session.commit()


def queue_customer_reservation_message(data):
    seat = data.get('seat')
    # 提交预约成功信息进入队列
    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.customer_id == seat.customer_id
    ).first()
    coach: Coach = Coach.query.filter(
        Coach.id == seat.coach_id
    ).first()
    day = datetime.strptime(str(seat.yymmdd), "%Y%m%d")
    date = day.strftime("%Y年%m月%d日")
    start_time = tp.formatting_time(seat.start)  # '10:00'
    end_time = tp.formatting_time(seat.end)  # '11:00'
    message_data = {
        'touser': wx_open_user.wx_open_id,
        'template_id': AppCache(wx_open_user.app_id).get('reservation_tmp_id'),
        'page': 'pages/user/index',  # 客户端 我
        'form_id': '{form_id}',
        'data': {
            'keyword1': {
                'value': "预约成功"
            },
            'keyword2': {
                'value': date + ' ' + start_time + '-' + end_time
            },
            'keyword3': {
                'value': coach.name
            },
        },
        "emphasis_keyword": "keyword1.DATA"
    }
    wx_message = WxMessage(
        app_id=wx_open_user.app_id,
        open_id=wx_open_user.wx_open_id,
        task="send reservation message to customer %d" % seat.customer_id,
        publish_at=datetime.now(),
        data=message_data,
        created_at=datetime.now(),
        is_completed=False
    )
    db.session.add(wx_message)
    db.session.commit()


def queue_customer_cancel_message(data):
    seat = data.get('seat')
    # 提交预约取消信息进入队列
    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.customer_id == seat.customer_id
    ).first()

    coach: Coach = Coach.query.filter(
        Coach.id == seat.coach_id
    ).first()

    day = datetime.strptime(str(seat.yymmdd), "%Y%m%d")
    date = day.strftime("%Y年%m月%d日")
    start_time = tp.formatting_time(seat.start)  # '10:00'
    end_time = tp.formatting_time(seat.end)  # '11:00'
    message_data = {
                'touser': wx_open_user.wx_open_id,
                'template_id': AppCache(wx_open_user.app_id).get('cancel_tmp_id'),
                'page': 'pages/user/index',  # 客户端 我
                'form_id': '{form_id}',
                'data': {
                    'keyword1': {
                        'value': "预约取消"
                    },
                    'keyword2': {
                        'value': date + " " + start_time + "-" + end_time
                    },
                    'keyword3': {
                        'value': coach.name
                    },
                },
                "emphasis_keyword": "keyword1.DATA"
            }
    wx_message = WxMessage(
        app_id=wx_open_user.app_id,
        open_id=wx_open_user.wx_open_id,
        task="send cancel message to customer %d" % seat.customer_id,
        publish_at=datetime.now(),
        data=message_data,
        created_at=datetime.now(),
        is_completed=False
    )
    db.session.add(wx_message)
    db.session.commit()


def queue_coach_confirmed_message(data):
    seat = data.get('seat')
    # 提交预约待确认信息进入队列
    wx_open_user: WxOpenUser = WxOpenUser.query.filter(
        WxOpenUser.coach_id == seat.coach_id,
        WxOpenUser.role == 'coach',
    ).first()

    trainee: Trainee = Trainee.query.filter(and_(
        Trainee.coach_id == seat.coach_id,
        Trainee.customer_id == seat.customer_id,
    )).first()

    day = datetime.strptime(str(seat.yymmdd), "%Y%m%d")
    date = day.strftime("%Y年%m月%d日")
    start_time = tp.formatting_time(seat.start)  # '10:00'
    end_time = tp.formatting_time(seat.end)  # '11:00'
    message_data = {
                'touser': wx_open_user.wx_open_id,
                'template_id': AppCache(wx_open_user.app_id).get('confirm_tmp_id'),
                'page': 'pages/reservation/index?page=1',  # 小助手预约页面(第一页)
                'form_id': '{form_id}',
                'data': {
                    'keyword1': {
                        'value': trainee.name
                    },
                    'keyword2': {
                        'value': date + ' ' + start_time + '-' + end_time
                    },
                    'keyword3': {
                        'value': '您有新的会员预约待确认,快去处理吧！'
                    }
                },
                "emphasis_keyword": "keyword1.DATA"
            }
    wx_message = WxMessage(
        app_id=wx_open_user.app_id,
        open_id=wx_open_user.wx_open_id,
        task="send confirmed message to coach %d" % seat.coach_id,
        publish_at=datetime.now(),
        data=message_data,
        created_at=datetime.now(),
        is_completed=False
    )
    db.session.add(wx_message)
    db.session.commit()


def queue_and_send_group_success_message(group_report: GroupReport):
    from store.user.apis import send_messages
    # 提交拼团成功消息进入队列
    group_members: List[GroupMember] = GroupMember.query.filter(
        GroupMember.group_report_id == group_report.id
    ).all()

    customer_ids = [member.customer_id for member in group_members]

    wx_open_users: List[WxOpenUser] = WxOpenUser.query.filter(
        WxOpenUser.customer_id.in_(customer_ids),
    ).all()
    store: Store = Store.query.filter(
        Store.biz_id == group_report.biz_id
    ).first()
    store_biz: StoreBiz = StoreBiz.query.filter(
        StoreBiz.id == group_report.biz_id
    ).first()
    for wx_open_user in wx_open_users:
        message_data = {
            'touser': wx_open_user.wx_open_id,
            'template_id': AppCache(wx_open_user.app_id).get('group_success_tmp_id'),
            'page': 'pages/user/group/groupDetail?id={g_hid}'.format(g_hid=group_report.get_hash_id()),  # 拼团详情页
            'form_id': '{form_id}',
            'data': {
                'keyword1': {
                    'value': group_report.activity.name
                },
                'keyword2': {
                    'value': group_report.activity.get_size().get('min_size')
                },
                'keyword3': {
                    'value': group_report.closed_at.strftime('%Y-%m-%d %H:%M:%S')
                },
                'keyword4': {
                    'value': store_biz.name
                },
                'keyword5': {
                    'value': store.get_address()
                }
            },
        }
        wx_message = WxMessage(
            app_id=wx_open_user.app_id,
            open_id=wx_open_user.wx_open_id,
            task="send group success message to customer %d" % wx_open_user.customer_id,
            publish_at=datetime.now(),
            data=message_data,
            created_at=datetime.now(),
            is_completed=False
        )
        db.session.add(wx_message)
        db.session.commit()
        db.session.refresh(wx_message)
        # 直接发送消息
        send_messages(wx_open_user)


def queue_and_send_group_fail_message(group_report: GroupReport):
    from store.user.apis import send_messages
    # 提交拼团失败消息进入队列
    group_members: List[GroupMember] = GroupMember.query.filter(
        GroupMember.group_report_id == group_report.id
    ).all()

    customer_ids = [member.customer_id for member in group_members]

    wx_open_users: List[WxOpenUser] = WxOpenUser.query.filter(
        WxOpenUser.customer_id.in_(customer_ids),
    ).all()
    store_biz: StoreBiz = StoreBiz.query.filter(
        StoreBiz.id == group_report.biz_id
    ).first()
    for wx_open_user in wx_open_users:
        message_data = {
            'touser': wx_open_user.wx_open_id,
            'template_id': AppCache(wx_open_user.app_id).get('group_fail_tmp_id'),
            'page': 'pages/user/group/groupDetail?id={g_hid}'.format(g_hid=group_report.get_hash_id()),  # 拼团详情页
            'form_id': '{form_id}',
            'data': {
                'keyword1': {
                    'value': group_report.activity.name
                },
                'keyword2': {
                    'value': group_report.created_at.strftime('%Y-%m-%d %H:%M:%S')
                },
                'keyword3': {
                    'value': group_report.members_count
                },
                'keyword4': {
                    'value': '参团人数未满%d人' % group_report.activity.get_size().get('min_size')
                },
                'keyword5': {
                    'value': store_biz.name
                }
            },
        }
        wx_message = WxMessage(
            app_id=wx_open_user.app_id,
            open_id=wx_open_user.wx_open_id,
            task="send group fail message to customer %d" % wx_open_user.customer_id,
            publish_at=datetime.now(),
            data=message_data,
            created_at=datetime.now(),
            is_completed=False
        )
        db.session.add(wx_message)
        db.session.commit()
        db.session.refresh(wx_message)
        # 直接发送消息
        send_messages(wx_open_user)


def queue_and_send_seat_check_message(data, type='customer'):
    from store.user.apis import send_messages
    seat = data.get('seat')
    day = datetime.strptime(str(seat.yymmdd), "%Y%m%d")
    date = day.strftime("%Y年%m月%d日")
    start_time = tp.formatting_time(seat.start)  # '10:00'
    end_time = tp.formatting_time(seat.end)  # '11:00'
    remainder = ContractContent.get_remainder_lesson(
        customer_id=seat.customer_id, course_id=seat.course_id,
        is_group=seat.is_group
    )
    course_name = ''
    if seat.course_id:
        course_cache = CourseCache(seat.course_id)
        course_brief = course_cache.get('brief')
        course_name = course_brief.get('title')
        if seat.is_group:
            course_name += "(多人)"
    if type == 'customer':
        coach: Coach = Coach.query.filter(
            Coach.id == seat.coach_id
        ).first()
        wx_open_user: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.customer_id == seat.customer_id
        ).first()
        message_data = {
            'touser': wx_open_user.wx_open_id,
            'template_id': AppCache(wx_open_user.app_id).get('customer_seat_check_tmp_id'),
            'page': 'pages/user/index',  # 客户端 我
            'form_id': '{form_id}',
            'data': {
                'keyword1': {
                    'value': date + ' ' + start_time + '-' + end_time
                },
                'keyword2': {
                    'value': course_name
                },
                'keyword3': {
                    'value': "1课时"
                },
                'keyword4': {
                    'value': remainder
                },
                'keyword5': {
                    'value': coach.name
                }
            }
        }
        wx_message = WxMessage(
            app_id=wx_open_user.app_id,
            open_id=wx_open_user.wx_open_id,
            task="send seat check success message to customer %d" % seat.customer_id,
            publish_at=datetime.now(),
            data=message_data,
            created_at=datetime.now(),
            is_completed=False
        )
        db.session.add(wx_message)
        db.session.commit()
        db.session.refresh(wx_message)
        send_messages(wx_open_user)
    else:
        wx_open_user: WxOpenUser = WxOpenUser.query.filter(
            WxOpenUser.coach_id == seat.coach_id,
            WxOpenUser.role == 'coach',
        ).first()
        trainee: Trainee = Trainee.query.filter(
            Trainee.customer_id == seat.customer_id,
            Trainee.coach_id == seat.coach_id
        ).first()
        message_data = {
            'touser': wx_open_user.wx_open_id,
            'template_id': AppCache(wx_open_user.app_id).get('coach_seat_check_tmp_id'),
            'page': 'pages/member/index?t_id=' + trainee.get_hash_id(),  # 学员列表页
            'form_id': '{form_id}',
            'data': {
                'keyword1': {
                    'value': date + ' ' + start_time + '-' + end_time
                },
                'keyword2': {
                    'value': course_name
                },
                'keyword3': {
                    'value': "1课时"
                },
                'keyword4': {
                    'value': remainder
                },
                'keyword5': {
                    'value': trainee.name
                }
            }
        }
        wx_message = WxMessage(
            app_id=wx_open_user.app_id,
            open_id=wx_open_user.wx_open_id,
            task="send seat check success message to coach %d" % seat.coach_id,
            publish_at=datetime.now(),
            data=message_data,
            created_at=datetime.now(),
            is_completed=False
        )
        db.session.add(wx_message)
        db.session.commit()
        db.session.refresh(wx_message)
        send_messages(wx_open_user)
    return
