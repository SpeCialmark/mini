from datetime import datetime
from typing import List

from sqlalchemy import or_, desc

from store.database import db
from store.domain.cache import CoachCache, CustomerCache
from store.domain.models import OperationLog, WxOpenUser


def post_log(biz_id, operator_id, operation, operating_object_id, content):
    log = OperationLog(
        biz_id=biz_id,
        operator_id=operator_id,
        operation=operation,
        operating_object_id=operating_object_id,
        content=content,
        operated_at=datetime.now()
    )
    db.session.add(log)
    db.session.commit()
    return


def get_logs(biz_id, start_time, end_time, operator_id=None, operating_object_id=None):
    logs: List[OperationLog] = OperationLog.query.filter(
        OperationLog.biz_id == biz_id,
        OperationLog.operated_at >= start_time,
        OperationLog.operated_at <= end_time,
        or_(
            OperationLog.operator_id == operator_id,
            OperationLog.operating_object_id == operating_object_id
        )
    ).order_by(desc(OperationLog.operated_at)).all()
    operator_dict = {}
    res = []
    for log in logs:
        if log.operator_id not in operator_dict.keys():
            wx_open_user: WxOpenUser = WxOpenUser.query.filter(
                WxOpenUser.id == log.operator_id
            ).first()
            if wx_open_user.role == "coach":
                coach_cache = CoachCache(wx_open_user.coach_id)
                brief = coach_cache.get('brief')
                operator_dict.update({
                    str(log.operator_id): brief.get('name')
                })
            else:
                operator_dict.update({
                    str(log.operator_id): CustomerCache(wx_open_user.customer_id).get('nick_name')
                })

        # [2018年12月06日 15:33:32] 教练主管：李志昂 修改了 苏家小妖的体测数据
        logs_format = "[{operated_at}] {operator} {operation}了 {object}的{content}".format(
            operator=operator_dict.get(str(log.operator_id)),
            operation=log.operation,
            object=CustomerCache(operating_object_id).get('nick_name'),
            content=log.content,
            operated_at=log.operated_at.strftime("%Y年%m月%d日 %H:%M:%S")
        )
        res.append(logs_format)
    return res
