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

# Will retry on 500 Server error
def requests_retry(status_forcelist=[500, 502]):
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=status_forcelist,
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s
