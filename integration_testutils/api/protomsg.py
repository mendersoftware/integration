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

import sys

PROP_STATUS_NORMAL = 1
PROP_STATUS_ERROR = 2

try:
    import msgpack
except ModuleNotFoundError:
    print("Please run `python3 -m pip install msgpack`.")
    sys.exit(1)


class ProtoMsg:
    def __init__(self, protoType):
        self.protoType = protoType

        self.clearAll()

    # Clear enough to send a new message.
    def clear(self):
        self.typ = None
        self.props = None

    # Clears everything.
    def clearAll(self):
        self.clear()
        self.sid = None

    def setTyp(self, typ):
        self.typ = typ

    def setSid(self, sid):
        self.sid = sid

    def setProps(self, props):
        self.props = props

    # Takes body object, attributes are fetched from the ProtoMsg object.
    def encode(self, obj):
        protomsg = {
            "hdr": {
                "proto": self.protoType,
                "typ": self.typ,
                "sid": self.sid,
                "props": self.props,
            },
            "body": obj,
        }
        return msgpack.packb(protomsg)

    # Returns body, attributes can be fetched from the ProtoMsg object.
    def decode(self, buf):

        obj = msgpack.unpackb(buf)
        if type(obj.get("hdr")) is not dict:
            raise TypeError("Malformed protomsg received.")

        hdr = obj["hdr"]
        if hdr.get("proto") != self.protoType:
            raise TypeError(
                f'Decoded message is not the right type, expected {self.protoType}, got {obj.get("proto")}'
            )

        self.typ = hdr.get("typ")
        self.sid = hdr.get("sid")
        self.props = hdr.get("props")
        self._body = obj.get("body", b"")

        return obj.get("body")

    @property
    def body_raw(self) -> bytes:
        return self._body

    @property
    def body(self) -> dict:
        return msgpack.loads(self._body)
