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

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from testutils.api.client import GATEWAY_HOSTNAME


# Will retry on server errors (5xx)
#
# 'host' is the value sent as the Host header. It only needs overriding when
# talking to something other than the namespace's own gateway -- the failover
# server, for instance, whose routers match a different hostname.
def requests_retry(status_forcelist=[500, 502, 503, 504], host=GATEWAY_HOSTNAME):
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=status_forcelist,
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    # Every caller addresses the gateway by container IP, and Traefik routes on
    # the Host header, so without this nothing matches a router and every
    # request comes back 404. Session headers apply to all requests made through
    # this session; a per-request 'headers' kwarg still wins if one ever needs to
    # override it.
    if host:
        s.headers.update({"Host": host})
    return s


def requests_get(url):
    """Plain GET that raises on a non-2xx.

    Moved here when this repo stopped forking mender-server's testutils; it was
    the one helper in that fork's common.py which upstream does not have.
    """
    req = requests.get(url, timeout=30)
    req.raise_for_status()
    return req
