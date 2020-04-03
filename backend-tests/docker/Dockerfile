FROM python:3.8

RUN apt-get -y -qq update && apt-get -qq -y install \
    docker.io \
    libzbar0

COPY requirements-py3.txt .

RUN pip3 install -r requirements-py3.txt
COPY ./downloaded-tools/mender-artifact /usr/local/bin/mender-artifact
RUN chmod 755 /usr/local/bin/mender-artifact

ENTRYPOINT ["bash", "/tests/run.sh"]
