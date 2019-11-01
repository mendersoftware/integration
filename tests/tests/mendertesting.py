import pytest

class MenderTesting(object):
    slow_cond = False
    fast_cond = False
    nightly_cond = False
    upgrade_from = False

    slow = None
    fast = None
    nightly = None

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

        if config.getoption("--runnightly"):
            MenderTesting.nightly_cond = True
        else:
            MenderTesting.nightly_cond = False

        if not MenderTesting.slow_cond and not MenderTesting.fast_cond and not MenderTesting.nightly_cond:
            # Default to running everything but nightly.
            MenderTesting.slow_cond = True
            MenderTesting.fast_cond = True

        MenderTesting.slow = pytest.mark.skipif(not MenderTesting.slow_cond, reason="need --runslow option to run")
        MenderTesting.fast = pytest.mark.skipif(not MenderTesting.fast_cond, reason="need --runfast option to run")
        MenderTesting.nightly = pytest.mark.skipif(not MenderTesting.nightly_cond, reason="need --runnightly option to run")
