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

import pytest


class MenderTesting(object):
    slow_cond = False
    fast_cond = False

    slow = None
    fast = None

    @staticmethod
    def set_test_conditions(config):
        if config.getoption("--runslow"):
            MenderTesting.slow_cond = True
        else:
            MenderTesting.slow_cond = False

        if config.getoption("--runfast"):
            MenderTesting.fast_cond = True
        else:
            MenderTesting.fast_cond = False

        if not MenderTesting.slow_cond and not MenderTesting.fast_cond:
            # Default to running everything
            MenderTesting.slow_cond = True
            MenderTesting.fast_cond = True

        MenderTesting.slow = pytest.mark.skipif(
            not MenderTesting.slow_cond, reason="need --runslow option to run"
        )
        MenderTesting.fast = pytest.mark.skipif(
            not MenderTesting.fast_cond, reason="need --runfast option to run"
        )
