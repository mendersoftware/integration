FROM python:2
WORKDIR /usr/src/app
ENV CHROME_BIN="/usr/bin/google-chrome"
ENV DISPLAY=":99.0"
RUN apt-get -q update && apt-get -yq install chromium=73.0.3683.75-1~deb9u1
RUN wget -q "https://chromedriver.storage.googleapis.com/73.0.3683.68/chromedriver_linux64.zip" -O /tmp/chromedriver.zip \
  && unzip /tmp/chromedriver.zip -d /usr/bin/ \
  && rm /tmp/chromedriver.zip
RUN pip install -U --user 'fabric<2.0' filelock paramiko psutil pytest requests selenium
RUN ln -s /usr/bin/chromedriver .
COPY tests .
RUN mkdir -p downloaded-tools && \
  curl -SL --fail "https://mender.s3-accelerate.amazonaws.com/temp_master/core-image-full-cmdline-qemux86-64.ext4" \
  -o core-image-full-cmdline-qemux86-64.ext4 && \
  curl -SL --fail "https://d1b0l86ne08fsf.cloudfront.net/mender-artifact/master/mender-artifact" \
  -o /usr/bin/mender-artifact && \
  curl -SL --fail "https://stress-client.s3-accelerate.amazonaws.com/release/mender-stress-test-client" \
  -o /usr/bin/mender-stress-test-client && \
  chmod +x /usr/bin/mender-artifact && \
  chmod +x /usr/bin/mender-stress-test-client && \
  ln -s /usr/bin/mender-artifact . && ln -s /usr/bin/mender-stress-test-client .
RUN mv e2e_tests/* .
CMD python -u test_ui.py
