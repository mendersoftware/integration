FROM ubuntu:16.04

RUN apt-get -y -qq update && apt-get -qq -y install \
    python3-pip \
    python3-pytest \
    docker.io \
    python3-crypto

RUN pip3 install --quiet requests==2.19 pymongo==3.6.1

ENTRYPOINT ["bash", "/tests/run.sh"]
