Mender Integration testing
===================


####Requirements
Python 2.7, requests, pytest, fabric, docker, docker-compose

Install all Python requirements by running:  `pip2.7 install -r requirements.txt`

Running tests is straight forward, just execute `bash run.sh`

`run.sh` is simple wrapper that  grabs the latest test images, artifacts tools, and other test requirements. It also calls `py.test` with `--runfast` and `--runslow`, which runs all fast and slow tests.

####OS X

Currently, running integration tests on OS X is not straight forward due to: 
https://github.com/docker/docker/issues/22753

####Known issues

Since we attempting to SSH into the virtual mender device, before the OS is up and running, you may see errors such as:

`Fatal error: Needed to prompt for a connection or sudo password (host: 172.18.0.6:8822), but abort-on-prompts was set to True Aborting.`

These can simply be ignored.
