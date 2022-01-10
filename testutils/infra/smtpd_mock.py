# Copyright 2022 Northern.tech AS
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
import base64
import email
import imaplib
import os
import pytest
import time
import smtpd
import logging

from threading import Thread, Condition


class Message:
    def __init__(self, peer, mailfrom, rcpttos, subject, data):
        self.peer = peer
        self.mailfrom = mailfrom
        self.rcpttos = rcpttos
        self.subject = subject
        self.data = data

    def __repr__(self):
        return f"<Message peer={self.peer} mailfrom={self.mailfrom} rcpttos={self.rcpttos} subject={self.subject}>"


class SMTPServerMock(smtpd.SMTPServer):
    def __init__(self, *args, **kwargs):
        self.messages = []
        smtpd.SMTPServer.__init__(self, *args, **kwargs)
        self._msg_cond = Condition()

    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        self.messages.append(Message(peer, mailfrom, rcpttos, None, data))
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


class SMTPGmail:
    def __init__(self, server, address, password):
        self._server = server
        self._address = address
        self._password = password

    def connect(self):
        mail = imaplib.IMAP4_SSL(self._server)
        mail.login(self._address, self._password)
        mail.select("INBOX")
        return mail

    def await_messages(self, n=1, timeout=None):
        timeout = int(timeout) if timeout else 60
        for i in range(timeout):
            time.sleep(1)
            if len(self.messages()) >= n:
                break

    def messages(self):
        mail = self.connect()
        try:
            type, data = mail.search(None, "ALL")
            assert type == "OK"
            messages = []
            mail_ids = data[0].decode("utf-8").split()
            if not mail_ids:
                return messages
            for i in range(int(mail_ids[-1]), int(mail_ids[0]) - 1, -1):
                type, data = mail.fetch(str(i), "(RFC822)")
                body = data[0][1]
                msg = email.message_from_string(body.decode("utf-8"))
                messages.append(
                    Message(None, msg["from"], [msg["to"]], msg["subject"], body)
                )
            return messages
        finally:
            mail.close()

    def filtered_messages(self, email):
        messages = self.messages()
        return tuple(filter(lambda m: email in m.rcpttos[0], messages))

    def assert_called(self, email):
        msgs = self.filtered_messages(email)
        assert len(msgs) == 1
        m = msgs[0]
        assert "@mender.io" in m.mailfrom, m.mailfrom
        assert email in m.rcpttos[0]
        assert len(m.data) > 0

    def clear(self):
        mail = self.connect()
        try:
            type, data = mail.search(None, "ALL")
            assert type == "OK"
            mail_ids = data[0].decode("utf-8").split()
            if not mail_ids:
                return
            for i in range(int(mail_ids[-1]), int(mail_ids[0]) - 1, -1):
                mail.store(str(i), "+FLAGS", "\\Deleted")
            mail.expunge()
        finally:
            mail.close()


def smtp_server_gmail():
    server = "imap.gmail.com"
    address = os.environ.get("GMAIL_ADDRESS")
    password = (
        base64.b64decode(os.environ.get("GMAIL_PASSWORD")).decode("utf-8")
        if os.environ.get("GMAIL_PASSWORD")
        else None
    )
    return SMTPGmail(server, address, password)


@pytest.fixture(scope="function")
def smtp_server():
    if os.environ.get("GMAIL_ADDRESS"):
        smtp = smtp_server_gmail()
        smtp.clear()
        yield smtp
        return
    server = SMTPMock()
    thread = Thread(target=server.start)
    thread.daemon = True
    thread.start()
    yield server
    server.stop()
    # need to wait for the port to be released
    time.sleep(30)
