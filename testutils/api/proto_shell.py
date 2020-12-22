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

from . import protomsg

PROTO_TYPE_SHELL = 1

MSG_TYPE_SHELL_COMMAND = "shell"
MSG_TYPE_SPAWN_SHELL = "new"
MSG_TYPE_STOP_SHELL = "stop"

# TODO: This, and all references to it, should be removed once we have fixed all
# issues.
WRONG_BEHAVIOR = True
WRONG_BEHAVIOR_COUNTER = 0


class ProtoShell:
    def __init__(self, ws):
        self.protomsg = protomsg.ProtoMsg(PROTO_TYPE_SHELL)
        self.ws = ws

    def startShell(self, user="ui-user"):
        global WRONG_BEHAVIOR_COUNTER

        if WRONG_BEHAVIOR and WRONG_BEHAVIOR_COUNTER > 1:
            # MEN-4240
            pass
        else:
            self.protomsg.clear()

        self.protomsg.setTyp(MSG_TYPE_SPAWN_SHELL)
        msg = self.protomsg.encode(user.encode())
        self.ws.send(msg)

        if WRONG_BEHAVIOR and WRONG_BEHAVIOR_COUNTER > 1:
            # MEN-4240
            try:
                msg = self.ws.recv(1)
                body = self.protomsg.decode(msg)
                assert (
                    self.protomsg.typ == MSG_TYPE_SHELL_COMMAND
                ), "self.protomsg.typ unexpected (%s)" % self.protomsg.typ
                return b""
            except TimeoutError:
                return b""
        else:
            msg = self.ws.recv()
        body = self.protomsg.decode(msg)
        assert (
            self.protomsg.typ == MSG_TYPE_SPAWN_SHELL
        ), "Did not receive confirmation that shell was started (received command \"%s\")." % self.protomsg.typ
        self.sid = self.protomsg.sid

        WRONG_BEHAVIOR_COUNTER += 1

        return body

    def sendInput(self, data):
        self.protomsg.clear()
        self.protomsg.setTyp(MSG_TYPE_SHELL_COMMAND)
        msg = self.protomsg.encode(data)
        self.ws.send(msg)

    def recvOutput(self, timeout=1):
        body = b""
        try:
            while True:
                msg = self.ws.recv(timeout)
                body += self.protomsg.decode(msg)
                assert (
                    self.protomsg.typ == MSG_TYPE_SHELL_COMMAND
                ), "Did not receive shell output."
        except TimeoutError:
            return body
        raise RuntimeError("Should never get here")

    def stopShell(self, user="ui-user"):
        self.protomsg.clear()
        self.protomsg.setTyp(MSG_TYPE_STOP_SHELL)
        msg = self.protomsg.encode(user.encode())
        self.ws.send(msg)

        msg = self.ws.recv()
        body = self.protomsg.decode(msg)
        assert (
            self.protomsg.typ == MSG_TYPE_STOP_SHELL
        ), "Did not receive confirmation that shell was started."
        self.protomsg.clearAll()
        return body
