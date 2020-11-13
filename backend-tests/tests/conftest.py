# Copyright 2018 Northern.tech AS
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
import urllib3
import pytest

from requests.packages import urllib3
from testutils.common import wait_for_traefik

urllib3.disable_warnings()

# See https://docs.pytest.org/en/latest/writing_plugins.html#assertion-rewriting
pytest.register_assert_rewrite("testutils")

wait_for_traefik("mender-api-gateway")
