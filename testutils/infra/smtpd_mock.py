# Copyright 2020 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import smtpd


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

    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        self.messages.append(Message(peer, mailfrom, rcpttos, data))
