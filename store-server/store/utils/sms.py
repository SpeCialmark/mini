from store.aliyunsdkdysmsapi.request.v20170525 import SendSmsRequest
from store.aliyunsdkdysmsapi.request.v20170525 import QuerySendDetailsRequest
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.profile import region_provider
import uuid
from store.cache import code_redis_store
from store.config import cfg
from random import randint

REGION = "cn-hangzhou"
PRODUCT_NAME = "Dysmsapi"
DOMAIN = "dysmsapi.aliyuncs.com"
SIGN_NAME = cfg['aliyun_sms']['sign_name']

acs_client = AcsClient(cfg['aliyun_sms']['access_key'], cfg['aliyun_sms']['secret'], REGION)
region_provider.add_endpoint(PRODUCT_NAME, REGION, DOMAIN)

TEMPLATE_VERIFY = cfg['aliyun_sms']['template_verify']
TEMPLATE_RESERVATION = cfg['aliyun_sms']['template_reservation']
TEMPLATE_GROUP_FAIL = cfg['aliyun_sms']['template_group_fail']
_cache_sms_code_format = '{phone_number}:{sms_code}'


def send_sms(business_id, template_code, phone_numbers, template_param=None):
    sms_request = SendSmsRequest.SendSmsRequest()
    # 申请的短信模板编码,必填
    sms_request.set_TemplateCode(template_code)

    # 短信模板变量参数
    if template_param is not None:
        sms_request.set_TemplateParam(template_param)

    # 设置业务请求流水号，必填。
    sms_request.set_OutId(business_id)

    # 短信签名
    sms_request.set_SignName(SIGN_NAME)

    # 数据提交方式
    # smsRequest.set_method(MT.POST)

    # 数据提交格式
    # smsRequest.set_accept_format(FT.JSON)

    # 短信发送的号码列表，必填。
    sms_request.set_PhoneNumbers(phone_numbers)

    # 调用短信发送接口，返回json
    sms_response = acs_client.do_action_with_exception(sms_request)

    # TODO 业务处理
    return sms_response


def random_num(count):
    result = ''
    for i in range(0, count):
        num = randint(0, 9)
        result += str(num)
    return result


def send_sms_code(phone_number):
    sms_code = random_num(6)
    key = _cache_sms_code_format.format(phone_number=phone_number, sms_code=sms_code)
    code_redis_store.setex(key, cfg['redis_expire']['sms_code'], 1)

    __business_id = uuid.uuid1()
    params = '{\"code\":\"' + sms_code + '\"}'
    send_sms(__business_id, TEMPLATE_VERIFY, phone_number, params)

    return sms_code


def verify_sms_code(phone_number, sms_code):
    key = _cache_sms_code_format.format(phone_number=phone_number, sms_code=sms_code)
    value = code_redis_store.get(key)

    if not value:  # 过期, 或者没有
        return False, '验证码有误'

    return True, ''


def send_reservation_sms(phone_number, time, name):
    __business_id = uuid.uuid1()
    params = '{\"time\":\"' + time + '\",\"name\":\"' + name + '\"}'
    result = send_sms(__business_id, TEMPLATE_RESERVATION, phone_number, params)
    return result


def send_group_fail_sms(phone_number, activity_name, app_name):
    __business_id = uuid.uuid1()
    params = '{\"activity\":\"' + activity_name + '\",\"app\":\"' + app_name + '\"}'
    result = send_sms(__business_id, TEMPLATE_GROUP_FAIL, phone_number, params)
    return result
