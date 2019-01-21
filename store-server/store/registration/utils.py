from store.domain.cache import CourseCache


def get_seat_course_name(seat):
    course_name = ''
    if seat.course_id:
        course_cache = CourseCache(seat.course_id)
        course_brief = course_cache.get('brief')
        course_name = course_brief.get('title')
        if seat.is_group:
            course_name += "(多人)"
    return course_name
