from datetime import datetime
from typing import List

import base62
from sqlalchemy import func, true

from store.database import db
from store.domain.cache import CoachCache, PlaceCache, CourseCache
from store.domain.models import Share, ShareVisit, ShareVisitor, Customer, Place, Coach, Course, Video
from store.utils import time_processing as tp


class BaseRecord:
    codetable = {
        '0': '/pages/home/index',
        '1': '/pages/home/experience',
        '2': '/pages/course/index',
        '3': '/pages/coach/index',
        '4': '/pages/feed/index',
        '5': '/pages/user/index',
        '6': '/pages/course/detail',
        '7': '/pages/course/groupCourses',
        '8': '/pages/course/groupCourseDetail',
        '9': '/pages/coach/detail',
        'a': '/pages/coach/traineeCase',
        'b': '/pages/coach/coachShow',
        'c': '/pages/coach/coachSolo',
        'd': '/pages/user/check_in',
        'e': '/pages/user/freeReservation',
        'f': '/pages/user/mineReservation',
        'g': '/pages/member/invite',
        'h': '/pages/member/confirm',
        'i': '/pages/member/free',
        'j': '/pages/checkIn/checkIn',
        'k': '/pages/checkIn/record',
        'l': '/pages/checkIn/recordDetail',
        'm': '/pages/places/index',
        'n': '/pages/places/detail',
        'o': '/pages/places/allCourses',
        'p': '/pages/salesman/index',
        'q': '/pages/salesman/circle',
        'r': '/pages/salesman/qrcode',
        's': '/pages/video/detail'
    }

    # 当前可以分享的页面
    coach_pages = [codetable['9'], codetable['3']]
    place_pages = [codetable['m']]
    video_pages = [codetable['s']]
    salesman_pages = [codetable['p']]
    course_pages = [codetable['6']]
    user_pages = [codetable['0']]
    check_in_pages = [codetable['j']]
    group_course_pages = [codetable['7'], codetable['8']]

    coach_title = "{name}"
    course_title = "{name}"
    place_title = "{name}"
    video_title = "{name}视频"
    check_in_title = "打卡页"
    salesman_title = "名片页"
    user_title = "主页"
    group_course_index_title = "团课课表页"
    group_course_title = "{name}"

    def get_coach_title(self, params):
        # 解析path为教练页面的title
        params = self.get_params_dict(params)
        coach_hid = params.get('coach_id')
        if coach_hid:
            c_cache = CoachCache(Coach.decode_id(coach_hid))
            c_brief = c_cache.get('brief')
            return self.coach_title.format(name=c_brief.get('name'))
        else:
            return "教练列表"

    def get_place_title(self, params):
        # 解析path为场地页面的title
        params = self.get_params_dict(params)
        place_hid = params.get('place_id')
        if place_hid:
            p_cache = PlaceCache(Place.decode_id(place_hid))
            p_name = p_cache.get('name')
            return self.place_title.format(name=p_name)
        else:
            return ""

    def get_video_title(self, params):
        # 解析path为视频页面的title
        params = self.get_params_dict(params)
        file_id = params.get('file_id')
        video: Video = Video.find(file_id)
        if not video:
            return "未命名视频"
        return self.video_title.format(name=video.title) if video.title else "未命名视频"

    def get_salesman_title(self):
        # 解析path为会籍(名片)页面的title
        return self.salesman_title

    def get_course_title(self, params):
        # 解析path为课程页面的title
        params = self.get_params_dict(params)
        course_hid = params.get('course_id')
        if course_hid:
            c_cache = CourseCache(Course.decode_id(course_hid))
            c_brief = c_cache.get('brief')
            return self.course_title.format(name=c_brief.get('title'))
        else:
            return ""

    def get_user_title(self):
        # 解析path为主页页面的title
        return self.user_title

    def get_check_in_title(self):
        # 解析path为打卡页面的title
        return self.check_in_title

    def get_group_course_title(self, params):
        # 解析path为团课页面的title
        params = self.get_params_dict(params)
        if not params:
            return self.group_course_index_title

        course_hid = params.get('course_id')
        if course_hid:
            c_cache = CourseCache(Course.decode_id(course_hid))
            c_brief = c_cache.get('brief')
            return self.group_course_title.format(name=c_brief.get('title'))
        else:
            return ''

    def get_title(self, share):
        path = share.path
        params = share.params
        if path in self.coach_pages:
            title = self.get_coach_title(params)
        elif path in self.course_pages:
            title = self.get_course_title(params)
        elif path in self.place_pages:
            title = self.get_place_title(params)
        elif path in self.video_pages:
            title = self.get_video_title(params)
        elif path in self.salesman_pages:
            title = self.get_salesman_title()
        elif path in self.user_pages:
            title = self.get_user_title()
        elif path in self.check_in_pages:
            title = self.get_check_in_title()
        elif path in self.group_course_pages:
            title = self.get_group_course_title(params)
        else:
            title = ''

        return title

    @staticmethod
    def get_params_dict(params):
        if params and params != '':
            params = params.split('&')
            params_dict = {}
            for p in params:
                k, v = p.split('=')
                if v == 'undefined':
                    continue
                params_dict.update({k: v})
            return params_dict
        else:
            return {}

    @staticmethod
    def check_params(params):
        if params and params != '':
            all_params = params.split('&')
            for p in all_params:
                k, v = p.split('=')
                if v == 'undefined':
                    return False, ''
            return True, params
        else:
            return True, ''


class ShareRecord(BaseRecord):

    def __init__(self, biz_id, customer_id=None, coach_id=None, salesman_id=None):
        self.biz_id = biz_id
        self.customer_id = customer_id
        self.coach_id = coach_id
        self.salesman_id = salesman_id
        if self.customer_id:
            self.user_type = 'customer'
        elif self.coach_id:
            self.user_type = 'coach'
        elif self.salesman_id:
            self.user_type = 'salesman'
        elif self.customer_id and self.salesman_id:
            self.user_type = 'salesman'
        else:
            self.user_type = None

    def get_user_shares(self) -> list:
        if self.user_type == 'customer':
            s: List[Share] = Share.query.filter(
                Share.biz_id == self.biz_id,
                Share.shared_customer_id == self.customer_id
            ).all()
        elif self.user_type == 'coach':
            s: List[Share] = Share.query.filter(
                Share.biz_id == self.biz_id,
                Share.shared_coach_id == self.coach_id
            ).all()
        elif self.user_type == 'salesman':
            s: List[Share] = Share.query.filter(
                Share.biz_id == self.biz_id,
                Share.shared_salesman_id == self.salesman_id
            ).all()
        else:
            s = []
        return s

    def post_share(self, s_type, path, params):
        # 每当用户进行分享操作时调用,生成对应的share记录
        if self.user_type == 'customer':
            s: Share = Share.query.filter(
                Share.biz_id == self.biz_id,
                Share.path == path,
                Share.type == s_type,
                Share.params == params,
                Share.shared_customer_id == self.customer_id
            ).first()
            if not s:
                s = Share(
                    biz_id=self.biz_id,
                    path=path,
                    params=params,
                    type=s_type,
                    shared_customer_id=self.customer_id,
                    created_at=datetime.now()
                )
                db.session.add(s)
                db.session.commit()
            return {
                'share_type': s_type,
                's_id': base62.encode(s.id)
            }

        elif self.user_type == 'coach':
            s: Share = Share.query.filter(
                Share.biz_id == self.biz_id,
                Share.path == path,
                Share.type == s_type,
                Share.params == params,
                Share.shared_coach_id == self.coach_id
            ).first()
            if not s:
                s = Share(
                    biz_id=self.biz_id,
                    path=path,
                    type=s_type,
                    params=params,
                    shared_coach_id=self.coach_id,
                    created_at=datetime.now()
                )
                db.session.add(s)
                db.session.commit()
            return {
                'share_type': s_type,
                's_id': base62.encode(s.id)
            }

        elif self.user_type == 'salesman':
            s: Share = Share.query.filter(
                Share.biz_id == self.biz_id,
                Share.path == path,
                Share.type == s_type,
                Share.params == params,
                Share.shared_salesman_id == self.salesman_id
            ).first()
            if not s:
                s = Share(
                    biz_id=self.biz_id,
                    path=path,
                    type=s_type,
                    params=params,
                    shared_salesman_id=self.salesman_id,
                    created_at=datetime.now()
                )
                db.session.add(s)
                db.session.commit()
            return {
                'share_type': s_type,
                's_id': base62.encode(s.id)
            }

        else:
            # 非法的操作
            return -1

    @staticmethod
    def put_share_visit(visit_cid, s: Share):
        # 每当有用户点击或扫描别人分享的页面或二维码时调用此方法
        # 为分享出去的用户增加一条访客记录
        # visit_cid为访客的customer_id
        visit: Customer = Customer.query.filter(
            Customer.id == visit_cid
        ).first()
        if not visit:
            return

        if s.shared_salesman_id:
            # 如果该分享是会籍分享的则将用户与该会籍绑定
            visit.salesman_id = s.shared_salesman_id
            visit.from_share_id = s.id
        now = tp.get_day_min(datetime.now())
        is_new = bool(tp.get_day_min(visit.created_at) == now)

        today_min = tp.get_day_min(datetime.today())
        today_max = tp.get_day_max(datetime.today())
        try:
            # 查询该访客今日是否访问过此页面
            s_visit: ShareVisit = ShareVisit.query.filter(
                ShareVisit.share_id == s.id,
                ShareVisit.customer_id == visit_cid,
                ShareVisit.created_at >= today_min,
                ShareVisit.created_at <= today_max,
            ).first()

            s_visitor: ShareVisitor = ShareVisitor.query.filter(
                ShareVisitor.share_id == s.id,
                ShareVisitor.customer_id == visit_cid,
                ShareVisitor.created_at >= today_min,
                ShareVisitor.created_at <= today_max,
            ).first()
            if not s_visit:
                s_visit = ShareVisit(
                    share_id=s.id,
                    customer_id=visit_cid,
                    created_at=now
                )
                db.session.add(s_visit)
            if not s_visitor:
                s_visitor = ShareVisitor(
                    share_id=s.id,
                    customer_id=visit_cid,
                    is_new_comer=is_new,
                    created_at=now
                )
                db.session.add(s_visitor)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e

    def get_visit(self, shares, page_type=None):
        if page_type == PageType.Salesman:
            res = self.get_salesman_pages_visit(shares)
        elif page_type == PageType.Coach:
            res = self.get_coach_pages_visit(shares)
        elif page_type == PageType.Course:
            res = self.get_course_pages_visit(shares)
        elif page_type == PageType.Place:
            res = self.get_place_pages_visit(shares)
        elif page_type == PageType.Video:
            res = self.get_video_pages_visit(shares)
        elif page_type == PageType.User:
            res = self.get_user_pages_visit(shares)
        elif page_type == PageType.CheckIn:
            res = self.get_check_in_pages_visit(shares)
        elif page_type == PageType.GroupCourse:
            res = self.get_group_course_pages_visit(shares)
        else:
            res = self.get_all_pages_visit(shares)

        return res

    @staticmethod
    def get_all_pages_visit(s, start_date=None, end_date=None) -> dict:
        if not start_date:
            start_date = tp.get_day_min(datetime.today())
        if not end_date:
            end_date = tp.get_day_max(datetime.today())
        share_ids = [share.id for share in s]

        if start_date == tp.get_day_min(end_date):
            # 若查询的日期是单日,则返回从有数据开始至该日期的访客数
            access_count = db.session.query(func.count(ShareVisit.id)).filter(
                ShareVisit.share_id.in_(share_ids),
                ShareVisit.created_at <= end_date
            ).scalar()  # 访问此页面的总访问量
        else:
            # 若查询的时间是时间段,则返回该时段内的访客数
            access_count = db.session.query(func.count(ShareVisit.id)).filter(
                ShareVisit.share_id.in_(share_ids),
                ShareVisit.created_at >= start_date,
                ShareVisit.created_at <= end_date
            ).scalar()  # 访问此页面的总访问量

        # 根据customer_id进行分组,组的数量就是用户的数量
        total_visit_new = len(db.session.query(func.count(ShareVisitor.customer_id), ShareVisitor.customer_id).filter(
            ShareVisitor.share_id.in_(share_ids),
            ShareVisitor.is_new_comer == true()
        ).group_by(ShareVisitor.customer_id).all())  # 今日访问此页面的总用户量

        today_visit = db.session.query(func.count(ShareVisit.id)).filter(
            ShareVisit.share_id.in_(share_ids),
            ShareVisit.created_at >= start_date,
            ShareVisit.created_at <= end_date
        ).scalar()  # 访问此页面的总用户量

        # 因为同一个用户就算多次访问也只有在第一次访问的时候是新用户
        # 因此可以用这个字段来区分总共带来了多少个用户
        today_visit_new = db.session.query(func.count(ShareVisitor.id)).filter(
            ShareVisitor.share_id.in_(share_ids),
            ShareVisitor.is_new_comer == true(),
            ShareVisitor.created_at >= start_date,
            ShareVisitor.created_at <= end_date
        ).scalar()
        return {
            'access_count': access_count,  # 访问此页面的总访问量
            'total_visit_new': total_visit_new,  # 访问此页面的总用户量
            'today_visit': today_visit,  # 今日访问此页面的总用户量
            'today_visit_new': today_visit_new,  # 今日访问此页面的新用户量(今日创建的customer)
        }

    def get_visit_detail(self, shares):
        # 获取每个页面的访问数据
        res = []
        for p_type in PageType.ALL:
            res.extend(self.get_visit(shares=shares, page_type=p_type))
        res = self.compare_title(res)
        res.sort(key=lambda x: (-x['access_count']))  # 访问此页面的总访问量
        return res

    def get_coach_pages_visit(self, shares) -> list:
        # 获取所有教练页面的访客记录
        coach_s = [share for share in shares if share.path in self.coach_pages]
        res = self.get_page_visit(coach_s)
        return res

    def get_place_pages_visit(self, shares) -> list:
        # 获取所有场地页面的访客记录
        place_s = [share for share in shares if share.path in self.place_pages]
        res = self.get_page_visit(place_s)
        return res

    def get_video_pages_visit(self, shares) -> list:
        # 获取所有视频页面的访客记录
        video_s = [share for share in shares if share.path in self.video_pages]
        res = self.get_page_visit(video_s)
        return res

    def get_salesman_pages_visit(self, shares) -> list:
        # 获取所有名片页面的访客记录
        salesman_s = [share for share in shares if share.path in self.salesman_pages]
        res = self.get_page_visit(salesman_s)
        return res

    def get_course_pages_visit(self, shares) -> list:
        # 获取所有课程页面的访客记录
        course_s = [share for share in shares if share.path in self.course_pages]
        res = self.get_page_visit(course_s)
        return res

    def get_user_pages_visit(self, shares) -> list:
        # 获取所有主页页面的访客记录
        user_s = [share for share in shares if share.path in self.user_pages]
        res = self.get_page_visit(user_s)
        return res

    def get_check_in_pages_visit(self, shares) -> list:
        # 获取所有预约页面的访客记录
        check_in_s = [share for share in shares if share.path in self.check_in_pages]
        res = self.get_page_visit(check_in_s)
        return res

    def get_group_course_pages_visit(self, shares) -> list:
        # 获取所有团课页面的访客记录
        gc_s = [share for share in shares if share.path in self.group_course_pages]
        res = self.get_page_visit(gc_s)
        return res

    def get_page_visit(self, shares: list) -> list:
        res = []
        today_min = tp.get_day_min(datetime.today())
        today_max = tp.get_day_max(datetime.today())
        for share in shares:
            access_count = db.session.query(func.count(ShareVisit.id)).filter(
                ShareVisit.share_id == share.id
            ).scalar()

            today_visit = db.session.query(func.count(ShareVisit.id)).filter(
                ShareVisit.share_id == share.id,
                ShareVisit.created_at >= today_min,
                ShareVisit.created_at <= today_max
            ).scalar()

            res.append({
                'title': self.get_title(share),
                'access_count': access_count,  # 访问此页面的总访问量
                'today_visit': today_visit,  # 今日访问此页面的总用户量
            })
        res.sort(key=lambda x: (x['title']))
        return res

    def compare_title(self, visit_list):
        # 将标题相同的数据合并
        result = []
        title_list = []
        for r in visit_list:
            title = r.get('title')
            if title not in title_list:
                title_list.append(title)

        for t in title_list:
            title_visit = self.get_title_visit(t, visit_list)
            result.append(title_visit)

        return result

    @staticmethod
    def get_title_visit(title, visit_list):
        v_list = [visit for visit in visit_list if visit.get('title') == title]
        access_count = 0
        today_visit = 0
        for v in v_list:
            access_count += v.get('access_count')
            today_visit += v.get('today_visit')
        return {
            'title': title,
            'access_count': access_count,
            'today_visit': today_visit,
        }


class PageType:
    Coach = 'coach'
    Course = 'course'
    Place = 'place'
    Video = 'video'
    Salesman = 'salesman'
    User = 'user'
    CheckIn = 'check_in'
    GroupCourse = 'group_course'
    ALL = [Coach, Course, Place, Video, Salesman, User, CheckIn, GroupCourse]
