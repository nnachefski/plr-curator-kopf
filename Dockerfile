FROM docker.io/library/python:3.8

ADD . /

RUN pip install -r requirements.txt

CMD kopf run -A handlers.py

