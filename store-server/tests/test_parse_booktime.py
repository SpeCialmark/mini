from datetime import datetime
from datetime import timedelta
import re
from dateutil import parser


def test_book_time():
    texts = ['4月27日4:00', '9月7日14:00', '1月1日14:00', '明天4月27日11:00', '明天4月27日11:30']
    for text in texts:
        get_datetime(text)
    # print('time=', time)
    pass


def test_same_date():
    now = datetime.now()
    book_day = get_datetime('5月24日9:00')
    delta: timedelta = book_day.date() - now.date()
    print('days', delta.days)
    assert delta.days == 0


bt = re.compile('(今天|明天|后天)*(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})')


def get_datetime(text):
    m = bt.match(text)
    month = int(m.group(2))
    day = int(m.group(3))
    hh = int(m.group(4))
    mm = int(m.group(5))
    print('********')
    # print(m.group(2))
    # print(m.group(3))
    print('********')

    now = datetime.now()
    this_year = now.year
    time = datetime(year=this_year, month=month, day=day, hour=hh, minute=mm)
    if month == 1:
        if time < now:
            time = datetime(year=this_year + 1, month=month, day=day, hour=hh, minute=mm)
    print('month', month, 'day', day, 'time', time)
    return time

