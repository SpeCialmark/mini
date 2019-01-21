import logging
from flask import Flask, Response
from raven.contrib.flask import Sentry
from store.config import cfg
from store.database import db
from store import wechat
from flask_cors import CORS


app = Flask(__name__, template_folder='store/templates')
CORS(app)

if 'wxopen_sentry_dsn' in cfg:
    sentry = Sentry()
    sentry.init_app(app, dsn=cfg['wxopen_sentry_dsn'], logging=True, level=logging.ERROR)

app.config['WXOPEN_SECRET_KEY'] = cfg['WXOPEN_SECRET_KEY']
app.config['SQLALCHEMY_DATABASE_URI'] = cfg['postgresql']
app.config['SQLALCHEMY_ECHO'] = True
# app.config['ELASTIC_APM'] = cfg['WXOPEN_ELASTIC_APM']

db.init_app(app)
# apm.init_app(app)

app.register_blueprint(wechat.apis.blueprint, url_prefix='/wechat')


@app.route('/1274189842.txt', methods=['GET'])
def get_text():
    return Response('875c46fc407ae4c3eb4ed8fada27c1df', mimetype='text/plain')
