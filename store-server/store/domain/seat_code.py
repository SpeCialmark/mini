from datetime import timedelta, datetime

import random

from store.domain.cache import SeatCodeCache, SeatCheckCache
from store.domain.models import Customer, Seat
from store.utils import time_processing as tp


def generate_code():
    while True:
        code = ''
        while len(code) < 6:
            code += str(random.randint(0, 9))
        code_cache = SeatCodeCache(code)
        seat_id = code_cache.get('seat_id')
        # get不到seat_id的情况下说明code可以使用
        if not seat_id:
            return code


def generate_seat_code(seat: Seat):
    seat_cache = SeatCheckCache(seat.id)
    code = seat_cache.get('code')
    if code:
        return code
    code = generate_code()
    code_cache = SeatCodeCache(code)
    try:
        code_cache.set({
            'seat_id': seat.id,
        })
        seat_cache.set({
            "code": code
        })
    except Exception as e:
        raise e
    return code
