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

# Synchronous wrapper around websockets. In tests it is more useful to have a
# synchronous API.

import asyncio
import logging
import socket
import ssl
import time
import websockets

logger = logging.getLogger()


class Websocket:
    def __init__(
        self, url, headers=[], insecure=False, retry_connect=True, connect_to=None
    ):
        self.url = url
        self.headers = headers
        self.insecure = insecure
        self.retry_connect = retry_connect
        # Optional (host, port) to open the TCP connection to, instead of the
        # host in 'url'. Needed because Traefik routes on the Host header while
        # tests can only reach it by container IP: putting the IP in the URL
        # would send the wrong Host, and passing Host via additional_headers
        # emits it twice (the library already derives one from the URL).
        # Connecting a socket ourselves keeps the URL -- and therefore both the
        # Host header and the TLS SNI name -- canonical.
        self.connect_to = connect_to

    def __enter__(self):
        ssl_context = ssl.create_default_context()
        if self.insecure:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        async def connect():
            kwargs = {"additional_headers": self.headers, "ssl": ssl_context}
            if self.connect_to is not None:
                sock = socket.create_connection(self.connect_to, timeout=30)
                sock.setblocking(False)
                # websockets forwards 'sock' to loop.create_connection and skips
                # its own DNS resolution; server_hostname still defaults to the
                # URL's host, so SNI stays correct.
                kwargs["sock"] = sock
            self.ws = await websockets.connect(self.url, **kwargs)

        attempts = 15
        sleep_seconds = 15
        while True:
            try:
                asyncio.get_event_loop().run_until_complete(connect())
                break
            except websockets.exceptions.InvalidHandshake:
                if self.retry_connect and attempts > 0:
                    attempts -= 1
                    logger.info(
                        "websockets: %d retrying on InvalidHandshake" % attempts
                    )
                    time.sleep(sleep_seconds)
                else:
                    logger.info("websockets: out of retries on InvalidHandshake")
                    raise

        return self

    def __exit__(self, exception_type, exception_value, traceback):
        async def close():
            await self.ws.close()

        asyncio.get_event_loop().run_until_complete(close())

    def send(self, msg):
        async def send():
            await self.ws.send(msg)

        asyncio.get_event_loop().run_until_complete(send())

    def recv(self, timeout=20):
        result = None

        async def recv():
            nonlocal result

            async def recv2():
                nonlocal result
                result = await self.ws.recv()

            await asyncio.wait_for(recv2(), timeout=timeout)

        try:
            asyncio.get_event_loop().run_until_complete(recv())
        except asyncio.TimeoutError as e:
            raise TimeoutError(e)

        assert result is not None
        return result
