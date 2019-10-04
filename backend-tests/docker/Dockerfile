FROM ubuntu:18.04

RUN apt-get -y -qq update && apt-get -qq -y install \
    python3-pip \
    docker.io \
    python3-crypto \
    python3-pytest

RUN pip3 install --quiet requests==2.19 pymongo==3.6.1

ENTRYPOINT ["bash", "/tests/run.sh"]
