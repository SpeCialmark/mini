from datetime import datetime, timedelta, time
import calendar


def get_day_min(day):
    """获取当日开始时间"""
    day_min = datetime(year=day.year, month=day.month, day=day.day, hour=0, minute=0, second=0)
    return day_min


def get_day_max(day):
    """获取当日结束时间"""
    day_max = datetime(year=day.year, month=day.month, day=day.day, hour=23, minute=59, second=59)
    return day_max


def get_next_day(day):
    """获取明天起始日期"""
    next_day = day + timedelta(days=1)
    return next_day


def get_last_n_day(day, num):
    """获取前n日"""
    today = get_day_min(day)
    for i in range(num):
        last_day = get_last_day(today)
        today = last_day
    return today


def get_next_n_day(day, num):
    """获取后n日"""
    today = get_day_min(day)
    for i in range(num):
        next_day = get_next_day(today)
        today = next_day
    return today


def get_last_day(day):
    """获取昨天起始日期"""
    last_day = day - timedelta(days=1)
    return last_day


def get_sunday(day):
    """获取当周周日"""
    # 6.13周三-->sunday = 6.10
    day = get_day_min(day)
    sunday = day - timedelta(day.weekday() - -1)
    return sunday


def get_next_sunday(day):
    """获取下周周日"""
    sunday = get_sunday(day)
    next_sunday = sunday + timedelta(days=7)
    return next_sunday


def get_last_sunday(day):
    """获取上周周日"""
    sunday = get_sunday(day)
    last_sunday = sunday - timedelta(days=7)
    return last_sunday


def get_saturday(day):
    """获取当周周六"""
    # 6.13周三-->saturday = 6.16
    day = get_day_min(day)
    sunday = day - timedelta(day.weekday() - -1)
    saturday = sunday + timedelta(days=6)
    return saturday


def get_next_saturday(day):
    """获取下周周六"""
    saturday = get_saturday(day)
    next_saturday = saturday + timedelta(days=7)
    return next_saturday


def get_last_saturday(day):
    """获取上周周六"""
    saturday = get_saturday(day)
    last_saturday = saturday - timedelta(days=7)
    return last_saturday


def get_last_n_sunday(day, num):
    """获取前n个周的周日"""
    sunday = get_sunday(day)
    for i in range(num):
        last_sunday = get_last_sunday(sunday)
        sunday = last_sunday
    return sunday


def get_early_month(day):
    """获取月初"""
    early_month = datetime(year=day.year, month=day.month, day=1)
    return early_month


def get_end_month(day):
    """获取月末"""
    day_of_month = calendar.monthrange(year=day.year, month=day.month)[1]
    end_month = datetime(year=day.year, month=day.month, day=day_of_month, hour=23, minute=59, second=59)
    return end_month


def get_day_of_month(day):
    """获取本月天数"""
    day_of_month = calendar.monthrange(year=day.year, month=day.month)[1]
    return day_of_month


def get_last_early_month(day):
    """获取上一个月月初"""
    early_month = get_early_month(day)
    last_day = early_month - timedelta(days=1)
    last_month = get_early_month(last_day)
    return last_month


def get_last_n_early_month(day, num):
    """获取前n个月的月初"""
    early_month = get_early_month(day)
    for i in range(num):
        last_early_month = get_last_early_month(early_month)
        early_month = last_early_month
    return early_month


def get_next_early_month(day):
    """获取下一个月月初"""
    end_month = get_end_month(day)
    next_day = end_month + timedelta(days=1)
    next_month = get_early_month(next_day)
    return next_month


def get_last_end_month(day):
    """获取上一个月月末"""
    last_early = get_last_early_month(day)
    last_end_month = get_end_month(last_early)
    return last_end_month


def get_next_end_month(day):
    """获取下一个月月末"""
    next_early = get_next_early_month(day)
    next_end_month = get_end_month(next_early)
    return next_end_month


def get_week(day):
    """ 获取周号 """
    week = calendar.weekday(day.year, day.month, day.day)
    # 周一是0, 周日是6
    # 转换为周日是0
    t_week = week + 1
    if t_week == 7:
        t_week = 0
    return t_week


def transform_weekstr(week_str):
    if week_str == 'Sun':
        week = 0
    elif week_str == 'Mon':
        week = 1
    elif week_str == 'Tue':
        week = 2
    elif week_str == 'Wed':
        week = 3
    elif week_str == 'Thu':
        week = 4
    elif week_str == 'Fri':
        week = 5
    elif week_str == 'Sat':
        week = 6
    else:
        # 格式错误
        week = -1
    return week


def formatting_time(t):
    """时间转换"""
    t_hour = t // 60
    if t_hour < 10:
        t_hour = "%02d" % t_hour
    t_min = t % 60
    if t_min < 10:
        t_min = "%02d" % t_min
    t = str(t_hour) + ":" + str(t_min)
    return t


def transform_timestr(t_str):
    """
    :param t_str: 10:00
    :return: 600
    """
    hour = int(t_str[:2])
    minute = int(t_str[3:])
    t = hour * 60 + minute
    return t


def transform_week_to_date(week: int):
    # 获取未来7天内对应week的日期(datetime)
    today = get_day_min(datetime.today())
    next_today = today + timedelta(days=7)
    while today < next_today:
        w = get_week(today)
        if w == week:
            return today
        today += timedelta(days=1)


def transform_week_chstr(week: int):
    if week == 0:
        week_chstr = '日'
    elif week == 1:
        week_chstr = '一'
    elif week == 2:
        week_chstr = '二'
    elif week == 3:
        week_chstr = '三'
    elif week == 4:
        week_chstr = '四'
    elif week == 5:
        week_chstr = '五'
    elif week == 6:
        week_chstr = '六'
    else:
        week_chstr = ''

    return week_chstr
