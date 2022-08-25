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

import logging
import pytest
import time

from ..common_setup import standard_setup_one_client

logger = logging.getLogger("root")


def test_kvm_acceleration_enabled(standard_setup_one_client):
    """Start a client, and make sure that no kvm errors are present in the log from 'mender-qemu'"""

    time.sleep(10)

    mender_qemu_script_logs = standard_setup_one_client.get_logs_of_service(
        "mender-client"
    )

    logger.debug(mender_qemu_script_logs)

    assert "failed to enable kvm" not in mender_qemu_script_logs
