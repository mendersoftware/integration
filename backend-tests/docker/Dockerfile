FROM python:3.8

RUN apt-get -y -qq update && apt-get -qq -y install \
    docker.io

COPY requirements-py3.txt .

RUN pip3 install -r requirements-py3.txt

ENTRYPOINT ["bash", "/tests/run.sh"]
