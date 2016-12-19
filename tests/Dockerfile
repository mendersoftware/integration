FROM        ubuntu:14.04
RUN         apt-get -qq -y update && apt-get -qq install python-pip python-dev build-essential e2tools curl libffi-dev libssl-dev
RUN         pip install fabric pytest requests --upgrade
WORKDIR     /testing
COPY        / /testing/
ENV         INSIDE_DOCKER=1
CMD         /bin/bash run.sh
