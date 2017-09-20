FROM ubuntu:16.04
RUN apt-get update -yq
RUN apt-get install -yq parted e2fsprogs jq sudo s3cmd curl python-pip jq
ADD add_tenant_token.sh .
ADD entrypoint.sh .
ADD .s3cfg /root/
RUN sudo pip install awscli
ENTRYPOINT ["./entrypoint.sh"]
