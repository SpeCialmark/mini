from flask_socketio import SocketIO
from flask import Flask, Response
from flask import jsonify, request, g
import json
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

socketio = SocketIO(async_mode='eventlet')
sentry_sdk.init(
    dsn="https://572a5f393a7740cc989d190d7c9a6c95@sentry.io/1306017",
    integrations=[FlaskIntegration()]
)

app = Flask(__name__)
# app.config['ELASTIC_APM'] = {
#     'SERVICE_NAME': 'websocket',
#     'SERVER_URL': 'http://172.18.248.179:8200',
#     'DEBUG': 'true'
# }
socketio.init_app(app)


@app.route('/customer_arrived', methods=['POST'])
def customer_arrived():
    data = request.get_json()
    msg_raw_json = data.get('Message')
    msg = json.loads(msg_raw_json)

    namespace = '/' + msg.get('biz_hid')
    brief = msg.get('brief')
    socketio.emit('arrived', brief, namespace=namespace)
    return jsonify()


@app.route('/health', methods=['GET'])
def health():
    return jsonify(msg='Hello 11train!')
