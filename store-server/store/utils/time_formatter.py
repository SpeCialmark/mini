from datetime import datetime, timedelta, time


def get_date_hhmm(yymmdd: int, start: int, end: int):
    """
    day=20180701, start=1230, end=1260
    """
    now = datetime.now()
    year = int(yymmdd/10000)
    month = int((yymmdd - year*10000)/100)
    day = yymmdd - year*10000 - month*100
    then = datetime(year=year, month=month, day=day)
    delta = then.date() - now.date()
    if delta.days == 0:
        time_str = '今天'
    elif delta.days == 1:
        time_str = '明天'
    elif delta.days == 2:
        time_str = '后天'
    else:
        time_str = ''
    time_str = time_str + then.strftime('%-m月%-d日')

    start_hh = int(start/60)
    start_mm = start - start_hh*60
    end_hh = int(end/60)
    end_mm = end - end_hh*60
    hhmm = '{}:{:02d}-{}:{:02d}'.format(start_hh, start_mm, end_hh, end_mm)
    return time_str, hhmm


def get_yymmdd(date: datetime):
    return date.year * 10000 + date.month * 100 + date.day


def get_yymmddhhmm(yymmdd: int, start: int):
    hours = int(start / 60)
    minutes = start - hours * 60
    return yymmdd * 10000 + hours * 100 + minutes


def get_hhmm(start, end):
    start_hh = int(start/60)
    start_mm = start - start_hh*60
    end_hh = int(end/60)
    end_mm = end - end_hh*60
    start_str = '{:02d}:{:02d}'.format(start_hh, start_mm)
    end_str = '{:02d}:{:02d}'.format(end_hh, end_mm)
    return start_str, end_str


def get_yymm(yymmdd: int):
    yymmdd_str = str(yymmdd)[:-2]
    yymm = int(yymmdd_str)
    return yymm


def get_year(yymmdd: int):
    year_str = str(yymmdd)[:4]
    return int(year_str)


def get_month(yymmdd: int):
    month_str = str(yymmdd)[4:6]
    return int(month_str)


def yymm_to_datetime(yymm: int):
    s_yymm = str(yymm)
    year = int(s_yymm[:4])
    month = int(s_yymm[4:])
    days = datetime(year, month, 1)
    return days


def yymmdd_to_datetime(yymmdd: int):
    s_yymm = str(yymmdd)
    year = int(s_yymm[:4])
    month = int(s_yymm[4:6])
    day = int(s_yymm[6:])
    date = datetime(year, month, day)
    return date
