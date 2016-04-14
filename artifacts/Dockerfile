FROM iron/base

ARG S3_KEY
ARG S3_SECRET

ARG S3_BIN_PATH
ARG S3_CONFIG_PATH

WORKDIR /usr/bin

RUN apk update && \
    apk add curl

COPY scripts/s3-get ./

RUN s3-get $S3_BIN_PATH artifacts
RUN chmod +x artifacts

RUN s3-get $S3_CONFIG_PATH config.yaml

ENTRYPOINT ["./artifacts"]
