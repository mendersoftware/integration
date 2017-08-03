import filelock
import logging
from mendertesting import MenderTesting

artifact_lock = filelock.FileLock(".artifact_modification_lock")
logger = logging.getLogger("mender")
