# Copyright 2024 Northern.tech AS
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
import base64
import email
import imaplib
import os
import pytest
import time
import logging

from aiosmtpd.controller import Controller

from threading import Condition

from redo import retriable


class Message:
    def __init__(self, peer, mail_from, rcpt_tos, subject, data):
        self.peer = peer
        self.mail_from = mail_from
        self.rcpt_tos = rcpt_tos
        self.subject = subject
        self.data = data

    def __repr__(self):
        return f"<Message peer={self.peer} mail_from={self.mail_from} rcpt_tos={self.rcpt_tos} subject={self.subject}>"


class SMTPServerMockHandler:
    def __init__(self, *args, **kwargs):
        self.messages = []
        self._msg_cond = Condition()

    # https://aiosmtpd.readthedocs.io/en/stable/handlers.html#handle_DATA
    async def handle_DATA(self, server, session, envelope):
        self.messages.append(
            Message(
                session.peer,
                envelope.mail_from,
                envelope.rcpt_tos,
                None,
                envelope.content,
            )
        )
        logging.info(f"got a message from: {envelope.mail_from}")
        with self._msg_cond:
            self._msg_cond.notify_all()
        return "200 OK"

    def wait_for_messages(self, n=1, timeout=None):
        with self._msg_cond:
            while True:
                if len(self.messages) >= n:
                    break
                if not self._msg_cond.wait(timeout):
                    raise TimeoutError("timed out waiting for email")


class SMTPMock:
    def __init__(self):
        self.handler = SMTPServerMockHandler()
        self.controller = Controller(
            self.handler, hostname="0.0.0.0", port=4444, enable_SMTPUTF8=True
        )

    def start(self):
        self.controller.start()

    def stop(self):
        self.controller.stop()

    def await_messages(self, _, n=1, timeout=None):
        self.handler.wait_for_messages(n, timeout)

    def filtered_messages(self, email):
        return tuple(filter(lambda m: m.rcpt_tos[0] == email, self.handler.messages))

    def assert_called(self, email):
        msgs = self.filtered_messages(email)
        assert len(msgs) == 1
        m = msgs[0]
        assert m.mail_from.rsplit("@", 1)[-1] == "mender.io"
        assert m.rcpt_tos[0] == email
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

    def await_messages(self, email, n=1, timeout=None):
        timeout = int(timeout) if timeout else 60
        for i in range(timeout):
            time.sleep(1)
            if len(self.filtered_messages(email)) >= n:
                break

    @retriable(sleeptime=1, attempts=3)
    def filtered_messages(self, address):
        mail = self.connect()
        try:
            type, data = mail.search(None, "X-GM-RAW \"deliveredto:'%s'\"" % address)
            assert type == "OK"
            messages = []
            mail_ids = data[0].decode("utf-8").split()
            if not mail_ids:
                return messages
            mail_ids.reverse()
            for i in mail_ids:
                type, data = mail.fetch(str(i), "(RFC822)")
                body = data[0][1]
                msg = email.message_from_string(body.decode("utf-8"))
                if msg["Delivered-To"] != address:
                    continue
                messages.append((msg, body))
            return [
                Message(None, msg["from"], [msg["to"]], msg["subject"], body)
                for (msg, body) in sorted(
                    messages, key=lambda x: x[0]["Date"], reverse=True
                )
            ]
        finally:
            mail.close()

    def assert_called(self, email):
        msgs = self.filtered_messages(email)
        assert len(msgs) == 1
        m = msgs[0]
        assert "@mender.io" in m.mail_from, m.mail_from
        assert email in m.rcpt_tos[0]
        assert len(m.data) > 0


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
        yield smtp
        return
    server = SMTPMock()
    server.start()
    yield server
    server.stop()
    # need to wait for the port to be released
    time.sleep(30)
