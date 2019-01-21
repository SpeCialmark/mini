FROM python:3.6

RUN cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

RUN mkdir -p /project/store-server

WORKDIR /project/store-server

ADD requirements.txt /project/store-server/
RUN pip install -r requirements.txt

ADD store /project/store-server/store
ADD res /project/store-server/res
ADD store_app.py /project/store-server/
ADD wxopen_app.py /project/store-server/
ADD celery_worker.py /project/store-server/
ADD ws_app.py /project/store-server/