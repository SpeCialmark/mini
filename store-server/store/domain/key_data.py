from typing import List

from sqlalchemy import desc
from store.domain.models import BodyData


class KeyDataType(object):
    """ 体测数据的类型 """
    name = None
    unit = None


class Height(KeyDataType):
    # 此数据不放在体测数据中(属于用户档案数据)
    name = '身高'
    unit = 'cm'


class Weight(KeyDataType):
    name = '体重'
    unit = 'kg'


class Bust(KeyDataType):
    name = '胸围'
    unit = 'cm'


class Waistline(KeyDataType):
    name = '腰围'
    unit = 'cm'


class HipCircumference(KeyDataType):
    name = '臀围'
    unit = 'cm'


class ThighCircumference(KeyDataType):
    name = '大腿围'
    unit = 'cm'


class CalfCircumference(KeyDataType):
    name = '小腿围'
    unit = 'cm'


class ArmCircumference(KeyDataType):
    name = '臂围'
    unit = 'cm'


class ShoulderWidth(KeyDataType):
    name = '肩宽'
    unit = 'cm'


class BMI(KeyDataType):
    name = '身体质量指数'
    unit = 'kg/cm²'


class BFP(KeyDataType):
    name = '体脂率'
    unit = '%'


class SkeletalMuscle(KeyDataType):
    name = '骨骼肌'
    unit = 'kg'


class BasalMetabolism(KeyDataType):
    name = '基础代谢'
    unit = 'kcal'


class StaticHeartRate(KeyDataType):
    name = '静态心率'
    unit = '次/min'


class StationPerspectiveFlexion(KeyDataType):
    name = '站立体前屈'
    unit = 'cm'


class PushUp(KeyDataType):
    name = '俯卧撑'
    unit = '次/min'


class SquatWallHold(KeyDataType):
    name = '靠墙静蹲'
    unit = '秒'


class Plank(KeyDataType):
    name = '平板支撑'
    unit = '秒'


class Crunches(KeyDataType):
    name = '卷腹'
    unit = '个'


class StepTest(KeyDataType):
    name = '台阶测试心率'
    unit = '次/min'


def get_all_name(plan=None):
    all_name = [Weight.name, Bust.name, Waistline.name,
                HipCircumference.name,
                ThighCircumference.name, CalfCircumference.name, ArmCircumference.name,
                ShoulderWidth.name, BMI.name, BFP.name, SkeletalMuscle.name,
                BasalMetabolism.name, StaticHeartRate.name, StepTest.name, PushUp.name,
                SquatWallHold.name, Plank.name, Crunches.name,
                StationPerspectiveFlexion.name]
    if not plan or not plan.key_data:
        return all_name
    for kd in plan.key_data:
        if kd.get('name') not in all_name:
            all_name.append(kd.get('name'))
    return all_name


def get_all_type(plan=None):
    all_name = get_all_name(plan)
    all_type = [Weight, Bust, Waistline,
                HipCircumference,
                ThighCircumference, CalfCircumference, ArmCircumference,
                ShoulderWidth, BMI, BFP, SkeletalMuscle,
                BasalMetabolism, StaticHeartRate, StepTest, PushUp,
                SquatWallHold, Plank, Crunches,
                StationPerspectiveFlexion]
    if not plan or not plan.key_data:
        return all_type, all_name

    for kd in plan.key_data:
        if kd.get('name') not in all_name:
            customize_type = KeyDataType()
            customize_type.name = kd.get('name')
            customize_type.unit = kd.get('unit')
            all_type.append(customize_type)
    return all_type, all_name


def get_base_data():
    base_data = [Weight, BFP, SkeletalMuscle, BasalMetabolism]
    names = [b.name for b in base_data]
    return {
        'names': names,
        'objects': base_data
    }


def get_circumference():
    circumference = [Bust, Waistline, HipCircumference, ThighCircumference, CalfCircumference, ArmCircumference, ShoulderWidth]
    names = [c.name for c in circumference]
    return {
        'names': names,
        'objects': circumference
    }


def get_physical_performance():
    physical_performance = [StaticHeartRate, StepTest, PushUp, SquatWallHold, Plank, Crunches, StationPerspectiveFlexion]
    names = [p.name for p in physical_performance]
    return {
        'names': names,
        'objects': physical_performance
    }


def get_nearest_record(customer_id, plan=None):
    # 获取最近一次的体测数据(所有类别)
    all_type, all_name = get_all_type(plan)
    body_datas: List[BodyData] = BodyData.query.filter(
        BodyData.customer_id == customer_id,
        BodyData.record_type.in_(all_name)
    ).order_by(desc(BodyData.recorded_at)).all()
    res = []
    for t in all_type:
        t_datas = [b for b in body_datas if b.record_type == t.name]
        t_datas.sort(key=lambda x: (x.recorded_at), reverse=True)
        t_data = t_datas[0] if t_datas else None
        brief = {
            'name': t.name,
            'data': t_data.data if t_data else None,
            'unit': t.unit
        }
        if plan and plan.key_data:
            for k_data in plan.key_data:
                if k_data.get('name') == t.name and k_data.get('initial_data'):
                    brief.update({'initial_data': k_data.get('initial_data')})
                if k_data.get('name') == t.name and k_data.get('target'):
                    brief.update({'target': k_data.get('target')})
        res.append(brief)
    return res


def check_key_data(key_data):
    names = []
    res = []
    for k in key_data:
        if k.get('name') not in names:
            names.append(k.get('name'))
        else:
            return False, '请勿重复选取关键指标', res
        if not all([k.get('target'), k.get('initial_data')]):
            return False, '请填写初始数据或健身目标', res
        res.append({
            'name': k.get('name'),
            'target': k.get('target'),
            'initial_data': k.get('initial_data'),
            'unit': k.get('unit'),
        })
    return True, '', res


def sort_key_data(key_data: List):
    if not key_data:
        return []
    base_data = get_base_data().get('names')
    circumference = get_circumference().get('names')
    physical_performance = get_physical_performance().get('names')
    all_sort_list = []
    all_sort_list.extend(base_data)
    all_sort_list.extend(circumference)
    all_sort_list.extend(physical_performance)
    res = []
    for k in all_sort_list:
        for kd in key_data:
            if k == kd.get('name'):
                res.append(kd)
                break

    return res
