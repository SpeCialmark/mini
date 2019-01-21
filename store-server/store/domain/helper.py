from typing import List
from store.domain.models import Store
import copy
from store.domain.cache import StoreBizCache
from sqlalchemy import and_
from store.database import db
from datetime import datetime


def move(a, i, j):
    if i == j:
        return a
    b = []
    for index, x in enumerate(a):
        if len(b) == j:
            b.append(a[i])

        if index != i:
            b.append(x)

        if len(b) == j:
            b.append(a[i])
    return b


class CourseIndex:
    def __init__(self, biz_id):
        self.biz_id = biz_id

    def add(self, course_id):
        now = datetime.now()
        store: Store = Store.query.filter(and_(
            Store.biz_id == self.biz_id
        )).first()
        course_indexes: list = copy.deepcopy(store.course_indexes) if store.course_indexes else list()
        course_indexes.append(course_id)
        store.course_indexes = course_indexes
        store.modified_at = now
        db.session.commit()

        biz_cache = StoreBizCache(self.biz_id)
        biz_cache.reload()

        return course_indexes.index(course_id)

    def find(self, course_id):
        biz_cache = StoreBizCache(self.biz_id)
        course_indexes = biz_cache.get('course_indexes')
        return course_indexes.index(course_id)

    def update(self, course_id, n_index):
        store: Store = Store.query.filter(and_(
            Store.biz_id == self.biz_id
        )).first()
        course_indexes: list = copy.deepcopy(store.course_indexes) if store.course_indexes else list()
        if n_index < 0 or n_index >= len(course_indexes):
            raise IndexError

        now = datetime.now()

        c_index = course_indexes.index(course_id)
        new_indexes = move(course_indexes, c_index, n_index)
        store.course_indexes = new_indexes
        store.modified_at = now
        db.session.commit()

        biz_cache = StoreBizCache(store.biz_id)
        biz_cache.reload()

        return n_index

    def delete(self, course_id):
        now = datetime.now()
        store: Store = Store.query.filter(and_(
            Store.biz_id == self.biz_id
        )).first()
        course_indexes: list = copy.deepcopy(store.course_indexes) if store.course_indexes else list()
        course_indexes.remove(course_id)

        store.course_indexes = course_indexes
        store.modified_at = now
        db.session.commit()

        biz_cache = StoreBizCache(self.biz_id)
        biz_cache.reload()


class CoachIndex:
    def __init__(self, biz_id):
        self.biz_id = biz_id

    def add(self, coach_id):
        now = datetime.now()
        store: Store = Store.query.filter(and_(
            Store.biz_id == self.biz_id
        )).first()
        coach_indexes: list = copy.deepcopy(store.coach_indexes) if store.coach_indexes else list()
        coach_indexes.append(coach_id)
        store.coach_indexes = coach_indexes
        store.modified_at = now
        db.session.commit()

        biz_cache = StoreBizCache(self.biz_id)
        biz_cache.reload()

        return coach_indexes.index(coach_id)

    def find(self, coach_id):
        biz_cache = StoreBizCache(self.biz_id)
        coach_indexes = biz_cache.get('coach_indexes')
        return coach_indexes.index(coach_id)

    def get_first(self):
        biz_cache = StoreBizCache(self.biz_id)
        coach_indexes = biz_cache.get('coach_indexes')
        return coach_indexes[0] if coach_indexes else None

    def update(self, coach_id, n_index):
        store: Store = Store.query.filter(and_(
            Store.biz_id == self.biz_id
        )).first()
        coach_indexes: list = copy.deepcopy(store.coach_indexes)
        if n_index < 0 or n_index >= len(coach_indexes):
            raise IndexError

        now = datetime.now()

        c_index = coach_indexes.index(coach_id)
        new_indexes = move(coach_indexes, c_index, n_index)
        store.coach_indexes = new_indexes
        store.modified_at = now
        db.session.commit()

        biz_cache = StoreBizCache(store.biz_id)
        biz_cache.reload()

        return n_index

    def delete(self, coach_id):
        now = datetime.now()
        store: Store = Store.query.filter(and_(
            Store.biz_id == self.biz_id
        )).first()
        coach_indexes: List = copy.deepcopy(store.coach_indexes)
        coach_indexes.remove(coach_id)

        store.coach_indexes = coach_indexes
        store.modified_at = now
        db.session.commit()

        biz_cache = StoreBizCache(self.biz_id)
        biz_cache.reload()
