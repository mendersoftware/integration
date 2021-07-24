# Copyright 2021 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import asyncore
import pytest
import time
import smtpd
import logging

from threading import Thread, Condition


class Message:
    def __init__(self, peer, mailfrom, rcpttos, data):
        self.peer = peer
        self.mailfrom = mailfrom
        self.rcpttos = rcpttos
        self.data = data


class SMTPServerMock(smtpd.SMTPServer):
    def __init__(self, *args, **kwargs):
        self.messages = []
        smtpd.SMTPServer.__init__(self, *args, **kwargs)
        self._msg_cond = Condition()

    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        self.messages.append(Message(peer, mailfrom, rcpttos, data))
        logging.warning("got a message: %s" % mailfrom)
        with self._msg_cond:
            self._msg_cond.notify_all()

    def wait_for_messages(self, n=1, timeout=None):
        with self._msg_cond:
            while True:
                if len(self.messages) >= n:
                    break
                if not self._msg_cond.wait(timeout):
                    raise TimeoutError("timed out waiting for email")


class SMTPMock:
    def start(self):
        self.server = SMTPServerMock(("0.0.0.0", 4444), None, enable_SMTPUTF8=True)
        asyncore.loop()

    def stop(self):
        self.server.close()

    def await_messages(self, n=1, timeout=None) -> None:
        self.server.wait_for_messages(n, timeout)

    def messages(self):
        return self.server.messages.copy()

    def filtered_messages(self, email):
        return tuple(filter(lambda m: m.rcpttos[0] == email, self.server.messages))

    def assert_called(self, email):
        msgs = self.filtered_messages(email)
        assert len(msgs) == 1
        m = msgs[0]
        assert m.mailfrom.rsplit("@", 1)[-1] == "mender.io"
        assert m.rcpttos[0] == email
        assert len(m.data) > 0


@pytest.fixture(scope="function")
def smtp_mock():
    smtp_mock = SMTPMock()
    thread = Thread(target=smtp_mock.start)
    thread.daemon = True
    thread.start()
    yield smtp_mock
    smtp_mock.stop()
    # need to wait for the port to be released
    time.sleep(30)
