import pytest

class MenderTesting(object):
    slow = pytest.mark.skipif(not pytest.config.getoption("--runslow"), reason="need --runslow option to run")
    fast = pytest.mark.skipif(not pytest.config.getoption("--runfast"), reason="need --runfast option to run")
