from datetime import datetime
import base62
from store.database import db
from store.domain.cache import AppCache, AppAuditCache
from store.domain.models import WxAuthorizer, StoreTemplate, Qrcode, Store, WxMsgTemplate, AppMark, StoreBiz, Share, \
    ShareType
from store.domain.authorizer import update_authorizer
from store.wxopen import component, release_client, release_agent_id
from sqlalchemy import and_
import copy
from abc import ABCMeta, abstractmethod
import json
from store.utils.oss import bucket, encode_app_id, qrcode_path
from wechatpy.exceptions import WeChatClientException
from store.config import cfg, get_res, _env
from enum import Enum
from store.domain.msg_template import binding_template, reservation_template, cancel_template, confirm_template, \
    group_success_template, group_fail_template, all_template


def format_dict(d: dict, params):
    for k, v in d.items():
        if isinstance(v, dict):
            format_dict(v, params)
        else:
            if v and type(v) is str:
                new_v = v.format(**params)
                d.update({k: new_v})


def update_ext_json(settings: list, ext_json: dict, app_mark: int) -> dict:
    for setting in settings:
        s_app_mark = int(setting.get('mark'))
        s_ext = setting.get('ext')
        s_window = setting.get('window')

        if s_app_mark == app_mark:
            ext = ext_json.get('ext')
            window = ext_json.get('window')
            if "reservationToshop" in s_ext:
                ext.update({'reservationToshop': s_ext.get('reservationToshop')})

            for s_k, s_v in s_window.items():
                if s_k in window:
                    window.update({s_k: s_v})

    return ext_json


_ERRCODE = 'errcode'    # 借鉴微信接口返回的错误字段定义, 不过变成了数组
_ERRMSG = 'errmsg'


class ActionStatus(Enum):
    NO_STARTED = 0
    PASSED = 1
    FAILED = -1


class Action(metaclass=ABCMeta):
    def __init__(self, wx_authorizer: WxAuthorizer):
        self.wx_authorizer = wx_authorizer

    def get_client(self):
        app_id = self.wx_authorizer.app_id
        client = component.get_client_by_appid(app_id)
        return client

    @property
    @abstractmethod
    def name(self):
        """ 显示给客户端 """
        pass

    @property
    @abstractmethod
    def result(self):
        pass

    @property
    @abstractmethod
    def time(self) -> datetime:
        pass

    @abstractmethod
    def execute(self):
        pass

    @property
    def status(self) -> Enum:
        if not self.result:
            return ActionStatus.NO_STARTED
        assert _ERRCODE in self.result    # result 必须得有_ERRCODE字段
        error_codes = self.result.get(_ERRCODE)
        if len(error_codes) == 0:       # 空数组
            return ActionStatus.PASSED
        # 非空数组
        if any(errcode != 0 for errcode in error_codes):
            return ActionStatus.FAILED
        else:
            return ActionStatus.PASSED

    @property
    def display(self):
        if self.status == ActionStatus.NO_STARTED:
            return {
                'action': self.name,
                'status': self.status.value
            }
        elif self.status == ActionStatus.PASSED:
            return {
                'action': self.name,
                'status': self.status.value,
                'msg': self.passed_msg,
                'time': self.time.strftime('%-m月%-d日 %H:%M') if self.time else None,
                'attachment': self.attachment
            }
        elif self.status == ActionStatus.FAILED:
            return {
                'action': self.name,
                'status': self.status.value,
                'errmsg': self.error_msg,
                'time': self.time.strftime('%-m月%-d日 %H:%M') if self.time else None,
                'attachment': self.attachment
            }

    @property
    def error_msg(self):
        if self.result:
            return self.result.get(_ERRMSG)
        else:
            return None

    @property
    def passed_msg(self):
        return ['已通过']

    @property
    def attachment(self):
        """ 附件, 子类可以自定义 """
        return None

    @staticmethod
    def notify(content):
        """ 往企业微信应用发通知 """
        release_client.message.send_text(
            agent_id=release_agent_id,
            party_ids=[cfg['party_id']['wxapp']],
            user_ids=[],
            content=content
        )


class CheckInfoAction(Action):
    """ 检查所有信息, 头像,昵称, 类别, domain设置, 模板消息 """

    @property
    def name(self):
        return 'check_info'

    @property
    def result(self):
        return self.wx_authorizer.check_info_result

    @property
    def time(self):
        return self.wx_authorizer.check_info_time

    domain_dict = {
        85015: '该账号不是小程序账号',
        85016: '域名数量超过限制',
        85017: '没有新增域名，请确认小程序已经添加了域名或该域名是否没有在第三方平台添加',
        85018: '域名没有在第三方平台设置'
    }
    category_dict = {
        -1: '系统繁忙'
    }

    def execute(self):
        now = datetime.now()

        check_info_result = dict()
        error_msgs = []
        error_codes = []
        client = self.get_client()

        # check nick_name, head_img
        authorizer_appid = self.wx_authorizer.app_id
        info_result = component.get_authorizer_info(authorizer_appid)

        self.wx_authorizer = update_authorizer(
            authorizer_appid, info_result['authorization_info'], info_result['authorizer_info'])
        if not self.wx_authorizer.nick_name:
            error_codes.append(-2)
            error_msgs.append('请设置小程序的名称')
        if not self.wx_authorizer.head_img:
            error_codes.append(-2)
            error_msgs.append('请设置小程序的头像')
        check_info_result.update({
            'profile': {
                'nick_name': self.wx_authorizer.nick_name,
                'head_img': self.wx_authorizer.head_img
            }
        })

        # check category
        try:
            r_category = client.wxa.get_category()
            for cat in r_category:
                if cat.get('first_class') == '体育':
                    if cat.get('second_class') not in ['在线健身', '体育场馆服务']:
                        error_msgs.append('请设置小程序的类别为【体育】->【体育场馆服务】, 或者【体育】->【在线健身】')

            check_info_result.update({
                'category': r_category
            })
        except WeChatClientException as e:
            error_codes.append(e.errcode)
            error_msgs.append('获取类目失败,' + str(self.domain_dict.get(e.errcode)))

        # check domain
        request_domain = cfg['wxapp_domain']['request_domain']
        wsrequest_domain = cfg['wxapp_domain']['wsrequest_domain']
        upload_domain = cfg['wxapp_domain']['upload_domain']
        download_domain = cfg['wxapp_domain']['download_domain']

        try:
            r_get_domain = client.wxa.modify_domain('get')
            if r_get_domain and r_get_domain.get('requestdomain') == request_domain \
                    and r_get_domain.get('wsrequestdomain') == wsrequest_domain \
                    and r_get_domain.get('uploaddomain') == upload_domain \
                    and r_get_domain.get('downloaddomain') == download_domain:
                check_info_result.update({
                    'domain': r_get_domain
                })
            else:
                action = 'set'
                try:
                    r_modify_domain = client.wxa.modify_domain(
                        action, request_domain, wsrequest_domain, upload_domain, download_domain)
                    check_info_result.update({
                        'domain': r_modify_domain
                    })
                except WeChatClientException as e:
                    error_codes.append(e.errcode)
                    error_msgs.append('设置域名失败,' + str(self.domain_dict.get(e.errcode)))
        except WeChatClientException as e:
            error_codes.append(e.errcode)
            error_msgs.append('查询域名设置失败')

        # check template
        if self.wx_authorizer.mark != AppMark.BOSS:     # BOSS端暂不用template
            self.check_template(error_codes, error_msgs)

        check_info_result.update({
            _ERRCODE: error_codes,
            _ERRMSG: error_msgs
        })

        self.wx_authorizer.check_info_time = now
        self.wx_authorizer.check_info_result = check_info_result
        db.session.commit()
        db.session.refresh(self.wx_authorizer)

    def check_template(self, error_codes, error_msgs):
        client = self.get_client()
        # templates = [binding_template, reservation_template, confirm_template, cancel_template, group_success_template,
        #              group_fail_template]
        templates = all_template
        try:
            r_templates = client.wxa.list_templates(offset=0, count=20)
            if not r_templates:
                titles = list()
            else:
                titles = [r_template.get('title') for r_template in r_templates]

            for t in templates:
                if t.title not in titles:
                    self.add_template(t, error_codes, error_msgs)
        except WeChatClientException as e:
            error_codes.append(e.errcode)
            error_msgs.append('查询模板信息失败')

    def add_template(self, t, error_codes, error_msgs):
        try:
            client = self.get_client()
            new_id = client.wxa.add_template(
                template_short_id=t.short_id, keyword_id_list=t.keyword_id_list)
            now = datetime.now()
            msg_template: WxMsgTemplate = WxMsgTemplate.query.filter(and_(
                WxMsgTemplate.app_id == self.wx_authorizer.app_id,
                WxMsgTemplate.short_id == t.short_id
            )).first()
            if not msg_template:
                msg_template = WxMsgTemplate(
                    app_id=self.wx_authorizer.app_id,
                    short_id=t.short_id,
                    created_at=now
                )
                db.session.add(msg_template)

            msg_template.template_id = new_id
            msg_template.title = t.title
            msg_template.keyword_id_list = t.keyword_id_list
            db.session.commit()
        except WeChatClientException as e:
            error_codes.append(e.errcode)
            error_msgs.append('添加{}模板信息失败'.format(t.title))


class SetTemplateAction(Action):
    @property
    def name(self):
        return 'set_template'

    @property
    def result(self):
        return self.wx_authorizer.set_template_result

    @property
    def time(self):
        return self.wx_authorizer.set_template_time

    def execute(self, template_id):
        """ 设置模板 """
        now = datetime.now()

        self.wx_authorizer.template_id = template_id

        self.wx_authorizer.set_template = {
            'template_id': template_id
        }
        self.wx_authorizer.set_template_time = now
        self.wx_authorizer.set_template_result = {
            _ERRCODE: [],
            _ERRMSG: []
        }
        db.session.commit()
        db.session.refresh(self.wx_authorizer)

    @property
    def attachment(self):
        if not self.wx_authorizer.template_id:
            return None
        template: StoreTemplate = StoreTemplate.query.filter(
            StoreTemplate.id == self.wx_authorizer.template_id).first()
        return {
            'template': template.get_brief()
        }


class SetDbAction(Action):
    """ 设置数据库 """
    @property
    def name(self):
        return 'set_db'

    @property
    def result(self):
        return self.wx_authorizer.set_db_result

    @property
    def time(self):
        return self.wx_authorizer.set_db_time

    def execute(self):
        biz_data = get_res(directory='store_biz', file_name='store_biz.yml')
        # print(biz_data)

        store: Store = Store.query.filter(and_(
            Store.biz_id == self.wx_authorizer.biz_id
        )).first()

        now = datetime.now()

        if not store:
            store = Store(
                biz_id=self.wx_authorizer.biz_id,
                created_at=now
            )
            db.session.add(store)

            store_template = biz_data.get('template_name_base')
            store.cards = store_template['store']['cards']
            store.contact = store_template['store']['contact']
            # store.coach_indexes = biz_data['coach_indexes']
            # store.course_indexes = biz_data['course_indexes']
            store.modified_at = now

            db.session.commit()

        # TODO 判断store的template_id是否一致

        self.wx_authorizer.set_db = {
            'template_id': self.wx_authorizer.template_id
        }
        self.wx_authorizer.set_db_time = now
        self.wx_authorizer.set_db_result = {
            _ERRCODE: [],
            _ERRMSG: []
        }

        db.session.commit()
        db.session.refresh(self.wx_authorizer)

    @property
    def passed_msg(self):
        return ['设置数据库成功']


class CommitAction(Action):
    """ 提交代码  """
    @property
    def name(self):
        return 'commit'

    @property
    def result(self):
        return self.wx_authorizer.commit_result

    @property
    def time(self):
        return self.wx_authorizer.commit_time

    code_dict = {
        -1: '系统繁忙',
        85013: '无效的自定义配置',
        85014: '无效的模版编号',
        85043: '模版错误',
        85044: '代码包超过大小限制',
        85045: 'ext_json有不存在的路径',
        85046: 'tabBar中缺少path',
        85047: 'pages字段为空',
        85048: 'ext_json解析失败'
    }

    def execute(self):
        if not self.wx_authorizer.template_id:
            raise LookupError('Template not set')
        template: StoreTemplate = StoreTemplate.query.filter(
            StoreTemplate.id == self.wx_authorizer.template_id).first()
        if not template:
            raise LookupError('Template not found. id=' + str(self.wx_authorizer.template_id))

        client = self.get_client()
        now = datetime.now()
        error_msgs = []
        error_codes = []

        params = {
            'version': template.version,
            'app_id': self.wx_authorizer.app_id,
            'app_name': self.wx_authorizer.nick_name
        }

        ext_json_format = copy.deepcopy(template.ext_json_format)
        format_dict(ext_json_format, params)
        # update ext_json
        store_biz: StoreBiz = StoreBiz.query.filter(
            StoreBiz.id == self.wx_authorizer.biz_id
        ).first()
        app_mark = self.wx_authorizer.mark
        if store_biz.settings:
            settings = json.loads(store_biz.settings)
            if settings:
                ext_json_format = update_ext_json(settings=settings, ext_json=ext_json_format, app_mark=app_mark)
        if app_mark == AppMark.COACH.value:
            # 若为教练端则将客户端的app_id添加到跳转小程序的列表中
            customer_wx_authorizer: WxAuthorizer = WxAuthorizer.query.filter(
                WxAuthorizer.biz_id == self.wx_authorizer.biz_id,
                WxAuthorizer.mark == AppMark.CUSTOMER.value
            ).first()
            ext_json_format.update({
                'navigateToMiniProgramAppIdList': [customer_wx_authorizer.app_id]
            })
        ext_json_str = json.dumps(ext_json_format, ensure_ascii=False)

        commit = {
            'template_params': params,
            'template_id': template.wx_template_id,
            'ext_json': ext_json_str,
            'version': template.version,
            'description': template.description
        }

        # ext_json_format = json.dumps(template.ext_json_format, ensure_ascii=False)
        # ext_json_str = ext_json_format.format(**params)
        # print(ext_json_str)

        try:
            r_commit = client.wxa.commit(
                template_id=commit['template_id'],
                ext_json=commit['ext_json'],
                version=commit['version'],
                description=commit['description']
            )

            app_audit_cache = AppAuditCache(biz_id=store_biz.id, app_mark=app_mark)
            app_audit_cache.set_version(template.version)

        except WeChatClientException as e:
            error_codes.append(e.errcode)
            error_msgs.append('提交代码失败, ' + str(self.code_dict.get(e.errcode)))

        self.wx_authorizer.commit = commit
        self.wx_authorizer.commit_time = now
        self.wx_authorizer.commit_result = {
            _ERRCODE: error_codes,
            _ERRMSG: error_msgs
        }

        db.session.commit()
        db.session.refresh(self.wx_authorizer)

    @property
    def attachment(self):
        qrcode: Qrcode = BetaQrcode(app_id=self.wx_authorizer.app_id).get()
        return {
            'qrcode': qrcode.get_brief()
        }


class SubmitAction(Action):
    @property
    def name(self):
        return 'submit'

    @property
    def result(self):
        return self.wx_authorizer.submit_result

    @property
    def time(self):
        return self.wx_authorizer.submit_time

    code_dict = {
        -1: '系统繁忙',
        86000: '不是由第三方代小程序进行调用',
        86001: '不存在第三方的已经提交的代码',
        85006: '标签格式错误',
        85007: '页面路径错误',
        85008: '类目填写错误',
        85009: '已经有正在审核的版本',
        85010: 'item_list有项目为空',
        85011: '标题填写错误',
        85023: '审核列表填写的项目数不在1-5以内',
        85077: '小程序类目信息失效（类目中含有官方下架的类目，请重新选择类目）',
        86002: '小程序还未设置昵称、头像、简介。请先设置完后再重新提交。',
        85085: '近7天提交审核的小程序数量过多，请耐心等待审核完毕后再次提交'
    }

    def get_item_list(self):
        check_info_result = self.wx_authorizer.check_info_result
        if not check_info_result:
            raise LookupError('check info not set')

        item_list__a = [
            {
                'address': 'pages/home/index',
                'tag': '健身房',
                'first_class': '体育',
                'second_class': '体育场馆服务',
                'first_id': 674,
                'second_id': 676,
                'title': '首页'
            }
        ]

        item_list__b = [
            {
                'address': 'pages/home/index',
                'tag': '健身房',
                'first_class': '体育',
                'second_class': '在线健身',
                'first_id': 674,
                'second_id': 682,
                'title': '首页'
            }
        ]

        item_list__a1 = [
            {
                'address': 'pages/reservation/index',
                'tag': '预约',
                'first_class': '体育',
                'second_class': '体育场馆服务',
                'first_id': 674,
                'second_id': 676,
                'title': '健身房预约'
            }
        ]

        item_list__b1 = [
            {
                'address': 'pages/reservation/index',
                'tag': '预约',
                'first_class': '体育',
                'second_class': '在线健身',
                'first_id': 674,
                'second_id': 682,
                'title': '首页'
            }
        ]

        item_list_boss = [
            {
                'address': 'pages/review/index',
                'tag': '健身房管理',
                'first_class': '体育',
                'second_class': '体育场馆服务',
                'first_id': 674,
                'second_id': 676,
                'title': '首页'
            }
        ]

        item_list_boss2 = [
            {
                'address': 'pages/review/index',
                'tag': '健身房管理',
                'first_class': '体育',
                'second_class': '在线健身',
                'first_id': 674,
                'second_id': 682,
                'title': '首页'
            }
        ]

        r_category = check_info_result.get('category')
        if not r_category:
            return None
        if self.wx_authorizer.mark == AppMark.CUSTOMER:
            for cat in r_category:
                if cat.get('first_class') == '体育':
                    if cat.get('second_class') == '体育场馆服务':
                        return item_list__a
                    elif cat.get('second_class') == '在线健身':
                        return item_list__b
        elif self.wx_authorizer.mark == AppMark.COACH:
            for cat in r_category:
                if cat.get('first_class') == '体育':
                    if cat.get('second_class') == '体育场馆服务':
                        return item_list__a1
                    elif cat.get('second_class') == '在线健身':
                        return item_list__b1
        elif self.wx_authorizer.mark == AppMark.BOSS:
            for cat in r_category:
                if cat.get('first_class') == '体育':
                    if cat.get('second_class') == '体育场馆服务':
                        return item_list_boss
                    elif cat.get('second_class') == '在线健身':
                        return item_list_boss2
        return None

    def execute(self):
        client = self.get_client()
        error_msgs = []
        error_codes = []
        now = datetime.now()
        submit_result = dict()
        item_list = self.get_item_list()

        app_audit_cache = AppAuditCache(biz_id=self.wx_authorizer.biz_id, app_mark=self.wx_authorizer.mark)
        version = app_audit_cache.get('version') or '未知'

        if not item_list:
            error_codes.append(-2)
            error_msgs.append('请设置小程序的类别为【体育】->【体育场馆服务】, 或者【体育】->【在线健身】')
            self.wx_authorizer.submit = {}
        else:
            try:
                r_submit = client.wxa.submit_audit(item_list)
                submit_result.update({
                    "auditid": r_submit
                })
                content = '{nick_name}, 版本{version}, 提交审核号{auditid}'.format(
                    nick_name=self.wx_authorizer.nick_name, version=version, auditid=r_submit)
                self.notify(content)
            except WeChatClientException as e:
                error_codes.append(e.errcode)
                error_msgs.append('提交审核失败' + str(self.code_dict.get(e.errcode)))

                reason_text = 'reason:{}'.format(str(self.code_dict.get(e.errcode)))
                title = '{nick_name}, 版本{version}, 提交审核失败'.format(
                    nick_name=self.wx_authorizer.nick_name, version=version)
                content = title + '\n' + reason_text
                self.notify(content)

            self.wx_authorizer.submit = {
                'item_list': item_list
            }
        submit_result.update({
            _ERRCODE: error_codes,
            _ERRMSG: error_msgs
        })
        self.wx_authorizer.submit_result = submit_result
        self.wx_authorizer.submit_time = now
        db.session.commit()
        db.session.refresh(self.wx_authorizer)


class AuditAction(Action):
    """ 接受审核结果 """
    @property
    def name(self):
        return 'audit'

    @property
    def result(self):
        return self.wx_authorizer.audit_result

    @property
    def time(self):
        return self.wx_authorizer.audit_time

    def execute(self, event_type, reason=None):
        _AUDIT_SUCCESS = 'weapp_audit_success'
        _AUDIT_FAIL = 'weapp_audit_fail'
        if event_type not in (_AUDIT_SUCCESS, _AUDIT_FAIL):
            raise LookupError('Unknown event_type. event_type=', event_type)
        now = datetime.now()
        error_msgs = []
        error_codes = []
        app_audit_cache = AppAuditCache(biz_id=self.wx_authorizer.biz_id, app_mark=self.wx_authorizer.mark)
        version = app_audit_cache.get('version')
        if event_type == _AUDIT_SUCCESS:
            if not self.wx_authorizer.auto_release:  # 如果没有自动发布, 发审核结果邮件. 如果已经设置了自动发布, 那么不必要发.
                content = '{nick_name}, 版本{version}, 审核通过'.format(
                    nick_name=self.wx_authorizer.nick_name, version=version)
                self.notify(content)
        elif event_type == _AUDIT_FAIL:
            reason_text = 'reason:{}'.format(reason)
            title = '{nick_name}, 版本{version}, 审核失败'.format(
                nick_name=self.wx_authorizer.nick_name, version=version)
            content = title + '\n' + reason_text
            self.notify(content)
            error_codes.append(-2)
            error_msgs.append('审核失败. ' + str(reason))

        self.wx_authorizer.audit_result = {
            _ERRCODE: error_codes,
            _ERRMSG: error_msgs
        }
        self.wx_authorizer.audit_time = now
        db.session.commit()
        db.session.refresh(self.wx_authorizer)

        app_audit_cache.delete()    # 无论审核成功或者失败, 都清除审核标记

        if event_type == _AUDIT_SUCCESS and self.wx_authorizer.auto_release:
            release_action = ReleaseAction(wx_authorizer=self.wx_authorizer, version=version)
            release_action.execute()


class ReleaseAction(Action):
    def __init__(self, wx_authorizer, version='未知'):
        self.wx_authorizer = wx_authorizer
        self.version = version

    @property
    def name(self):
        return 'release'

    @property
    def result(self):
        return self.wx_authorizer.release_result

    @property
    def time(self):
        return self.wx_authorizer.release_time

    code_dict = {
        -1: '系统繁忙',
        85019: '没有审核版本',
        85020: '审核状态未满足发布'
    }

    def execute(self):
        now = datetime.now()
        client = self.get_client()
        error_msgs = []
        error_codes = []
        try:
            r_release = client.wxa.release()
            app_audit_cache = AppAuditCache(biz_id=self.wx_authorizer.biz_id, app_mark=self.wx_authorizer.mark)
            app_audit_cache.delete()  # 有时候审核没通知, 需要在此清除审核标记

            content = '{nick_name}, 版本{version}, 发布成功'.format(
                nick_name=self.wx_authorizer.nick_name, version=self.version)
            self.notify(content)
        except WeChatClientException as e:
            error_codes.append(e.errcode)
            error_msgs.append('发布失败. ' + str(self.code_dict.get(e.errcode)))
            # 由于是自动发布, 如果出错那么发通知
            title = '小程序发布失败, {nick_name}, 版本{version}'.format(
                nick_name=self.wx_authorizer.nick_name, version=self.version)
            content = title + '\n' + str(self.code_dict.get(e.errcode))
            self.notify(content)
        self.wx_authorizer.release_result = {
            _ERRCODE: error_codes,
            _ERRMSG: error_msgs
        }
        self.wx_authorizer.release_time = now
        db.session.commit()
        db.session.refresh(self.wx_authorizer)

    @property
    def attachment(self):
        qrcode: Qrcode = ReleaseQrcode(app_id=self.wx_authorizer.app_id).get()
        return {
            'qrcode': qrcode.get_brief()
        }


class BaseQrcode:
    def __init__(self, app_id: str):
        self.app_id = app_id
        self.app_hid = encode_app_id(app_id)

    @property
    def oss_path(self):
        return qrcode_path.format(app_hid=self.app_hid, file_name=self.file_name)

    def get_client(self):
        client = component.get_client_by_appid(self.app_id)
        return client

    def get(self) -> Qrcode:
        qrcode = Qrcode.query.filter(and_(
            Qrcode.app_id == self.app_id,
            Qrcode.name == self.name
        )).first()
        if not qrcode:
            qrcode = self.generate()
        else:
            # 更新头像和名称
            app_cache = AppCache(self.app_id)
            head_img, nick_name = app_cache.get('head_img', 'nick_name')
            if qrcode.app_head_img != head_img or qrcode.app_nick_name != nick_name:
                qrcode = self.generate()
        return qrcode

    @abstractmethod
    def generate(self) -> Qrcode:
        pass


class BetaQrcode(BaseQrcode):
    """ 体验版二维码 """

    name = '体验版'
    file_name = 'experience.jpg'

    def generate(self):
        now = datetime.now()
        client = self.get_client()
        r_qr = client.wxa.get_qrcode()

        r_put = bucket.put_object(self.oss_path, r_qr, {'Content-Disposition': 'attachment'})
        if r_put.status != 200:
            raise IOError('图片上传到阿里云失败')

        qrcode = Qrcode.query.filter(and_(
            Qrcode.app_id == self.app_id,
            Qrcode.name == self.name
        )).first()
        if not qrcode:
            qrcode = Qrcode(
                app_id=self.app_id,
                name=self.name,
                created_at=now
            )
            db.session.add(qrcode)

        app_cache = AppCache(self.app_id)
        if app_cache:
            head_img, nick_name = app_cache.get('head_img', 'nick_name')
            qrcode.app_head_img = head_img
            qrcode.app_nick_name = nick_name

        qrcode.file_name = self.file_name
        qrcode.modified_at = now
        db.session.commit()
        db.session.refresh(qrcode)
        return qrcode


class ReleaseQrcode(BaseQrcode):
    """ 正式版小程序码 """
    name = '正式版'
    file_name = 'release.jpg'

    def generate(self):
        path = 'pages/home/index'
        width = 430
        auto_color = False
        line_color = {"r": "0", "g": "0", "b": "0"}

        now = datetime.now()
        client = self.get_client()
        r_qr = client.wxa.get_wxa_code(path, width, auto_color, line_color)
        _dir = self.oss_path
        if _env == 'dev':
            _dir = 'dev/' + self.oss_path
        r_put = bucket.put_object(_dir, r_qr, {'Content-Disposition': 'attachment'})
        if r_put.status != 200:
            raise IOError('图片上传到阿里云失败')

        qrcode = Qrcode.query.filter(and_(
            Qrcode.app_id == self.app_id,
            Qrcode.name == self.name
        )).first()
        if not qrcode:
            qrcode = Qrcode(
                app_id=self.app_id,
                name=self.name,
                created_at=now
            )
            db.session.add(qrcode)

        app_cache = AppCache(self.app_id)
        if app_cache:
            head_img, nick_name = app_cache.get('head_img', 'nick_name')
            qrcode.app_head_img = head_img
            qrcode.app_nick_name = nick_name

        qrcode.path = path
        qrcode.width = width
        qrcode.file_name = self.file_name
        qrcode.auto_color = auto_color
        qrcode.line_color = line_color
        qrcode.modified_at = now
        db.session.commit()

        db.session.refresh(qrcode)
        return qrcode


class ReleaseCoverQrcode(BaseQrcode):
    """ 正式版小程序码 """
    name = '正式版'
    file_name = 'release_cover.jpg'

    def generate(self):
        path = 'pages/home/index'
        width = 860
        auto_color = False
        line_color = {"r": "0", "g": "0", "b": "0"}

        now = datetime.now()
        client = self.get_client()
        r_qr = client.wxa.get_wxa_code(path, width, auto_color, line_color)
        _dir = self.oss_path
        if _env == 'dev':
            _dir = 'dev/' + self.oss_path
        r_put = bucket.put_object(_dir, r_qr, {'Content-Disposition': 'attachment'})
        if r_put.status != 200:
            raise IOError('图片上传到阿里云失败')

        qrcode = Qrcode.query.filter(and_(
            Qrcode.app_id == self.app_id,
            Qrcode.name == self.name
        )).first()
        if not qrcode:
            qrcode = Qrcode(
                app_id=self.app_id,
                name=self.name,
                created_at=now
            )
            db.session.add(qrcode)

        app_cache = AppCache(self.app_id)
        if app_cache:
            head_img, nick_name = app_cache.get('head_img', 'nick_name')
            qrcode.app_head_img = head_img
            qrcode.app_nick_name = nick_name

        qrcode.path = path
        qrcode.width = width
        qrcode.file_name = self.file_name
        qrcode.auto_color = auto_color
        qrcode.line_color = line_color
        qrcode.modified_at = now
        db.session.commit()

        db.session.refresh(qrcode)
        return qrcode


class CheckInQrcode(BaseQrcode):
    """ 打卡小程序码 """
    name = '打卡小程序码'
    file_name = 'checkIn.jpg'

    def generate(self):
        path = 'pages/home/index?path=/pages/checkIn/checkIn&page=checkIn'
        width = 430
        auto_color = False
        line_color = {"r": "0", "g": "0", "b": "0"}

        now = datetime.now()
        client = self.get_client()
        r_qr = client.wxa.get_wxa_code(path, width, auto_color, line_color)
        _dir = self.oss_path
        if _env == 'dev':
            _dir = 'dev/' + self.oss_path
        r_put = bucket.put_object(_dir, r_qr, {'Content-Disposition': 'attachment'})
        if r_put.status != 200:
            raise IOError('图片上传到阿里云失败')

        qrcode = Qrcode.query.filter(and_(
            Qrcode.app_id == self.app_id,
            Qrcode.name == self.name
        )).first()
        if not qrcode:
            qrcode = Qrcode(
                app_id=self.app_id,
                name=self.name,
                created_at=now
            )
            db.session.add(qrcode)

        app_cache = AppCache(self.app_id)
        if app_cache:
            head_img, nick_name = app_cache.get('head_img', 'nick_name')
            qrcode.app_head_img = head_img
            qrcode.app_nick_name = nick_name

        qrcode.path = path
        qrcode.width = width
        qrcode.file_name = self.file_name
        qrcode.auto_color = auto_color
        qrcode.line_color = line_color
        qrcode.modified_at = now
        db.session.commit()

        db.session.refresh(qrcode)
        return qrcode


class CheckInCoverQrcode(BaseQrcode):
    """ 打卡小程序码 """
    name = '精装打卡小程序码'
    file_name = 'checkIn_cover.jpg'

    def generate(self):
        path = 'pages/home/index?path=/pages/checkIn/checkIn&page=checkIn'  # 从首页跳转进入
        width = 860
        auto_color = False
        line_color = {"r": "0", "g": "0", "b": "0"}

        now = datetime.now()
        client = self.get_client()
        r_qr = client.wxa.get_wxa_code(path, width, auto_color, line_color)
        _dir = self.oss_path
        if _env == 'dev':
            _dir = 'dev/' + self.oss_path
        r_put = bucket.put_object(_dir, r_qr, {'Content-Disposition': 'attachment'})
        if r_put.status != 200:
            raise IOError('图片上传到阿里云失败')

        qrcode = Qrcode.query.filter(and_(
            Qrcode.app_id == self.app_id,
            Qrcode.name == self.name
        )).first()
        if not qrcode:
            qrcode = Qrcode(
                app_id=self.app_id,
                name=self.name,
                created_at=now
            )
            db.session.add(qrcode)

        app_cache = AppCache(self.app_id)
        if app_cache:
            head_img, nick_name = app_cache.get('head_img', 'nick_name')
            qrcode.app_head_img = head_img
            qrcode.app_nick_name = nick_name

        qrcode.path = path
        qrcode.width = width
        qrcode.file_name = self.file_name
        qrcode.auto_color = auto_color
        qrcode.line_color = line_color
        qrcode.modified_at = now
        db.session.commit()

        db.session.refresh(qrcode)
        return qrcode


class PlaceQrcode(BaseQrcode):
    """ 场地小程序码 """

    def __init__(self, place_name, place_hid, app_id):
        self.place_name = place_name
        self.name = '{place_name}小程序码'.format(place_name=place_name)
        self.file_name = "place_{place_hid}.jpg".format(place_hid=place_hid)
        self.place_id = place_hid
        self.app_id = app_id
        self.app_hid = encode_app_id(app_id)

    def generate(self):
        path = 'pages/home/index?path=/pages/places/index&id={p_id}&page=place'.format(
            p_id=self.place_id)  # 从首页跳转进入
        width = 860
        auto_color = False
        line_color = {"r": "0", "g": "0", "b": "0"}

        now = datetime.now()
        client = self.get_client()
        r_qr = client.wxa.get_wxa_code(path, width, auto_color, line_color)
        _dir = self.oss_path
        if _env == 'dev':
            _dir = 'dev/' + self.oss_path
        r_put = bucket.put_object(_dir, r_qr, {'Content-Disposition': 'attachment'})
        if r_put.status != 200:
            raise IOError('图片上传到阿里云失败')

        qrcode = Qrcode.query.filter(and_(
            Qrcode.app_id == self.app_id,
            Qrcode.name == self.name
        )).first()
        if not qrcode:
            qrcode = Qrcode(
                app_id=self.app_id,
                name=self.name,
                created_at=now
            )
            db.session.add(qrcode)

        app_cache = AppCache(self.app_id)
        if app_cache:
            head_img, nick_name = app_cache.get('head_img', 'nick_name')
            qrcode.app_head_img = head_img
            qrcode.app_nick_name = nick_name

        qrcode.path = path
        qrcode.width = width
        qrcode.file_name = self.file_name
        qrcode.auto_color = auto_color
        qrcode.line_color = line_color
        qrcode.modified_at = now
        db.session.commit()

        db.session.refresh(qrcode)

        return qrcode


class SalesmanQrcode(BaseQrcode):
    """ 会籍人员小程序码(在pc端录入会籍时同步生成) """
    def __init__(self, app_id, salesman):
        self.app_id = app_id
        self.app_hid = encode_app_id(app_id)
        self.salesman = salesman
        self.name = "{salesman_name}会籍的小程序码".format(salesman_name=self.salesman.name)
        self.file_name = "salesman_{hid}.jpg".format(hid=self.salesman.get_hash_id())

    def generate(self):
        width = 430
        auto_color = False
        line_color = {"r": "0", "g": "0", "b": "0"}
        now = datetime.now()

        path = str(cfg['codetable']['p'])
        share_type = ShareType.QRCODE.value
        params = 'id={salesman_hid}'.format(salesman_hid=self.salesman.get_hash_id())
        s: Share = Share.query.filter(
            Share.biz_id == self.salesman.biz_id,
            Share.type == share_type,
            Share.path == path,
            Share.params == params,
            Share.shared_salesman_id == self.salesman.id
        ).first()

        if not s:
            s = Share(
                biz_id=self.salesman.biz_id,
                type=share_type,
                path=path,
                params=params,
                shared_salesman_id=self.salesman.id,  # 生成的时候默认分享者就是这位会籍
                created_at=now
            )
            db.session.add(s)
            db.session.commit()
            db.session.refresh(s)

        code_mode = 1
        path_id = 'p'  # 这个ID由客户端定义, 但是得注意版本兼容性
        share_id = base62.encode(s.id)
        scene = '{code_mode}&{path_id}&{share_id}'.format(code_mode=code_mode, path_id=path_id, share_id=share_id)
        page = 'pages/salesman/index'  # 开头不能加'/'
        unlimited_code = UnlimitedCode(self.app_id)
        r_qr = unlimited_code.get_raw_code(scene, page)
        _dir = self.oss_path
        if _env == 'dev':
            _dir = 'dev/' + self.oss_path
        r_put = bucket.put_object(_dir, r_qr, {'Content-Disposition': 'attachment'})
        if r_put.status != 200:
            raise IOError('图片上传到阿里云失败')

        qrcode = Qrcode.query.filter(and_(
            Qrcode.app_id == self.app_id,
            Qrcode.name == self.name
        )).first()
        if not qrcode:
            qrcode = Qrcode(
                app_id=self.app_id,
                name=self.name,
                created_at=now
            )
            db.session.add(qrcode)

        app_cache = AppCache(self.app_id)
        if app_cache:
            head_img, nick_name = app_cache.get('head_img', 'nick_name')
            qrcode.app_head_img = head_img
            qrcode.app_nick_name = nick_name

        qrcode.path = path
        qrcode.width = width
        qrcode.file_name = self.file_name
        qrcode.auto_color = auto_color
        qrcode.line_color = line_color
        qrcode.modified_at = now
        db.session.commit()

        db.session.refresh(qrcode)
        return qrcode


class UnlimitedCode:
    def __init__(self, app_id: str):
        self.app_id = app_id

    def get_client(self):
        client = component.get_client_by_appid(self.app_id)
        return client

    def get_raw_code(self, scene, page=None):
        client = self.get_client()
        r_qr = client.wxa.get_wxa_code_unlimited(scene=scene, page=page)
        return r_qr


class RegistrationQrcode(BaseQrcode):
    name = '前台到店码'
    file_name = "registration.jpg"

    def generate(self):
        path = 'pages/home/index?path=/pages/user/registration&page=registration'  # 从首页跳转进入
        width = 860
        auto_color = False
        line_color = {"r": "0", "g": "0", "b": "0"}

        now = datetime.now()
        client = self.get_client()
        r_qr = client.wxa.get_wxa_code(path, width, auto_color, line_color)
        _dir = self.oss_path
        if _env == 'dev':
            _dir = 'dev/' + self.oss_path
        r_put = bucket.put_object(_dir, r_qr, {'Content-Disposition': 'attachment'})
        if r_put.status != 200:
            raise IOError('图片上传到阿里云失败')

        qrcode = Qrcode.query.filter(and_(
            Qrcode.app_id == self.app_id,
            Qrcode.name == self.name
        )).first()
        if not qrcode:
            qrcode = Qrcode(
                app_id=self.app_id,
                name=self.name,
                created_at=now
            )
            db.session.add(qrcode)

        app_cache = AppCache(self.app_id)
        if app_cache:
            head_img, nick_name = app_cache.get('head_img', 'nick_name')
            qrcode.app_head_img = head_img
            qrcode.app_nick_name = nick_name

        qrcode.path = path
        qrcode.width = width
        qrcode.file_name = self.file_name
        qrcode.auto_color = auto_color
        qrcode.line_color = line_color
        qrcode.modified_at = now
        db.session.commit()

        db.session.refresh(qrcode)
        return qrcode
