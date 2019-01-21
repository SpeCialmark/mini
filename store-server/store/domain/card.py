from abc import ABCMeta, abstractmethod


class CardFactory:
    @staticmethod
    def get_card(json_data):

        pass


class BaseCard(metaclass=ABCMeta):
    pass


class BannerCard(BaseCard):
    def __bool__(self):
        return bool(self.card.get('images'))


class ImagesVerticalCard(BaseCard):
    def __bool__(self):
        return bool(self.card.get('images'))


class TextCard(BaseCard):
    def __bool__(self):
        return bool(self.card.get('text'))


class TrainerCaseCard(BaseCard):
    def __bool__(self):
        return bool(self.card.get('cases'))


class ContactCard(BaseCard):
    def __bool__(self):
        return bool(self.card.get('contact'))
