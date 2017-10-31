FROM ubuntu:16.04

RUN apt-get -y update && apt-get -y install git python3 python3-setuptools curl dnsutils

RUN git clone https://github.com/Netflix/conductor.git

RUN cd conductor/client/python && \
       python3 setup.py install

RUN mkdir -p /usr/bin/mender/prepare_welcome_email && \
    mkdir -p /usr/bin/mender/send_email

COPY prepare_welcome_email/* /usr/bin/mender/prepare_welcome_email/
COPY send_email/* /usr/bin/mender/send_email/

COPY entrypoint.sh /usr/bin/mender

ENTRYPOINT ["/usr/bin/mender/entrypoint.sh"]
