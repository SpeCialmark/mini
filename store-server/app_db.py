from store.config import cfg
from store.database import db
from flask import Flask
from flask_script import Manager
from flask_migrate import Migrate, MigrateCommand
# declare tables
from store.domain import models

app = Flask(__name__)

app.config['SECRET_KEY'] = cfg['SECRET_KEY']
app.config['SQLALCHEMY_DATABASE_URI'] = cfg['postgresql']
app.config['SQLALCHEMY_ECHO'] = True

db.init_app(app)

migrate = Migrate(app, db)

manager = Manager(app)
manager.add_command('db', MigrateCommand)

if __name__ == '__main__':
    manager.run()
