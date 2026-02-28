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

from . import protomsg

PROTO_TYPE_SHELL = 1

MSG_TYPE_SHELL_COMMAND = "shell"
MSG_TYPE_SPAWN_SHELL = "new"
MSG_TYPE_STOP_SHELL = "stop"

MSG_BODY_SHELL_STARTED = b"Shell started"


class ProtoShell:
    def __init__(self, ws):
        self.protomsg = protomsg.ProtoMsg(PROTO_TYPE_SHELL)
        self.ws = ws

    def startShell(self):
        self.protomsg.clear()

        self.protomsg.setTyp(MSG_TYPE_SPAWN_SHELL)
        msg = self.protomsg.encode(b"")
        self.ws.send(msg)

        msg = self.ws.recv()
        body = self.protomsg.decode(msg)
        assert self.protomsg.protoType == PROTO_TYPE_SHELL
        assert self.protomsg.typ == MSG_TYPE_SPAWN_SHELL, (
            'Did not receive confirmation that shell was started (received command "%s").'
            % self.protomsg.typ
        )
        self.sid = self.protomsg.sid

        return body

    def sendInput(self, data):
        self.protomsg.clear()
        self.protomsg.setTyp(MSG_TYPE_SHELL_COMMAND)
        msg = self.protomsg.encode(data)
        self.ws.send(msg)

    def recvOutput(self, timeout=55):
        body = b""
        try:
            while True:
                msg = self.ws.recv(timeout)
                body += self.protomsg.decode(msg)
                assert self.protomsg.protoType == PROTO_TYPE_SHELL
                assert (
                    self.protomsg.typ == MSG_TYPE_SHELL_COMMAND
                ), "Did not receive shell output."
        except TimeoutError:
            return body
        raise RuntimeError("Should never get here")

    def stopShell(self):
        self.protomsg.clear()
        self.protomsg.setTyp(MSG_TYPE_STOP_SHELL)
        msg = self.protomsg.encode(b"")
        self.ws.send(msg)

        msg = self.ws.recv()
        body = self.protomsg.decode(msg)
        assert self.protomsg.protoType == PROTO_TYPE_SHELL
        assert (
            self.protomsg.typ == MSG_TYPE_STOP_SHELL
        ), "Did not receive confirmation that shell was started."
        self.sid = None
        return body
