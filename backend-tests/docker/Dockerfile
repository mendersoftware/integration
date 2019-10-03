FROM ubuntu:16.04

RUN apt-get -y -qq update && apt-get -qq -y install \
    python3-pip \
    docker.io \
    python3-crypto

RUN pip3 install --quiet requests==2.19 pymongo==3.6.1

# NOTE: pytest-html 1.13 is the latest one compatible with Python 3.5 (Ubuntu 16.04 latest)
RUN pip3 install "pytest<3.0" pytest-html==1.13

ENTRYPOINT ["bash", "/tests/run.sh"]
