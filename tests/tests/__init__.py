import filelock
from mendertesting import MenderTesting

artifact_lock = filelock.FileLock(".artifact_modification_lock")
exposed_ports_lock = filelock.FileLock(".exposed_ports_lock")
