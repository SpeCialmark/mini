from datetime import datetime
from http import HTTPStatus
from typing import List

from flask import Blueprint
from flask import jsonify, request, g
from sqlalchemy import desc

from store.database import db
from store.domain.models import Article

blueprint = Blueprint('_articles', __name__)


@blueprint.route('', methods=['POST'])
def post_article():
    json_data = request.get_json()
    if not json_data:
        return jsonify(msg='missing json data'), HTTPStatus.BAD_REQUEST
    content = json_data.get('content')
    title = json_data.get('title')

    if not all([title, content]):
        return jsonify(msg='缺少标题或内容'), HTTPStatus.BAD_REQUEST
    article = Article(
        title=title,
        content=content,
        created_at=datetime.now()
    )
    db.session.add(article)
    db.session.commit()
    return jsonify(msg='添加成功')


@blueprint.route('', methods=['GET'])
def get_article():
    articles: List[Article] = Article.query.order_by(desc(Article.created_at)).all()
    res = [{
        'title': a.title,
        'content': a.content
    } for a in articles]
    return jsonify({
        'articles': res
    })
