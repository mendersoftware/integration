import pytest

class MenderTesting(object):
    slow_cond = False
    fast_cond = False
    nightly_cond = False
    aws_cond = False
    upgrade_from = False

    slow = None
    fast = None
    nightly = None

if getattr(pytest, "config", False):
    if pytest.config.getoption("--runslow"):
        MenderTesting.slow_cond = True
    else:
        MenderTesting.slow_cond = False

    if pytest.config.getoption("--runfast"):
        MenderTesting.fast_cond = True
    else:
        MenderTesting.fast_cond = False

    if pytest.config.getoption("--runnightly"):
        MenderTesting.nightly_cond = True
    else:
        MenderTesting.nightly_cond = False

    if pytest.config.getoption("--runs3"):
        MenderTesting.aws_cond = True

    if pytest.config.getoption("--upgrade-from"):
        MenderTesting.upgrade_from = pytest.config.getoption("--upgrade-from")

    if not MenderTesting.slow_cond and not MenderTesting.fast_cond and not MenderTesting.nightly_cond and not MenderTesting.aws_cond:
        # Default to running everything but nightly.
        MenderTesting.slow_cond = True
        MenderTesting.fast_cond = True

    MenderTesting.slow = pytest.mark.skipif(not MenderTesting.slow_cond, reason="need --runslow option to run")
    MenderTesting.fast = pytest.mark.skipif(not MenderTesting.fast_cond, reason="need --runfast option to run")
    MenderTesting.nightly = pytest.mark.skipif(not MenderTesting.nightly_cond, reason="need --runnightly option to run")
    MenderTesting.aws_s3 = pytest.mark.skipif(not MenderTesting.aws_cond, reason="need --runs3 option to run")
    MenderTesting.upgrade_from = pytest.mark.skipif(not MenderTesting.upgrade_from, reason="need --upgrade-from option to run")
