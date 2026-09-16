# Mender Integration Testing

![Mender logo](../mender_logo.png)

**Table of Contents**

- [Mender Integration Testing](#mender-integration-testing)
    - [Getting Started](#getting-started)
        - [What mender-testkit provides](#what-mender-testkit-provides)
    - [Installing Dependencies](#installing-dependencies)
        - [Isolating Python Dependencies (Optional, but recommended)](#isolating-python-dependencies-optional-but-recommended)
            - [Initialize the Virtual Environment](#initialize-the-virtual-environment)
            - [Activate the Virtual Environment](#activate-the-virtual-environment)
        - [System Dependencies](#system-dependencies)
            - [Alpine Linux](#alpine-linux)
            - [Debian](#debian)
        - [Python](#python)
    - [Running the Tests Locally](#running-the-tests-locally)
        - [Running the Tests](#running-the-tests)
        - [Selecting the Server Version](#selecting-the-server-version)
    - [Running with Custom Images](#running-with-custom-images)
        - [A Custom Backend Service](#a-custom-backend-service)
        - [A Custom Client](#a-custom-client)
    - [Known Issues](#known-issues)
        - [OS X](#os-x)
    - [Tips and Tricks](#tips-and-tricks)


-------------------------------------------------------------------------------


## Getting Started

The dependencies for the integration tests are collected and organized in
dependency files in the `./requirements-*` folders, and separated into


| Alpine                                     | Debian                                     | Python                                        |
| :----------------------------------------: | :----------------------------------------: | :-------------------------------------------: |
| *requirements-system/apk-requirements.txt* | *requirements-system/deb-requirements.txt* | *requirements-python/python-requirements.txt* |

### What mender-testkit provides

The server side of the test bed does not live in this repository. The Python
requirements pin [mender-testkit](https://pypi.org/project/mender-testkit/),
which supplies three things vendored from a pinned mender-server commit:

- `testutils` -- the API clients, container manager and device helpers
- the `Server` facade the fixtures build on
- mender-server's docker compose files

`tests/conftest.py` writes that compose tree to `tests/mender_server/` on every
run, which is the path a git submodule used to occupy, so the `include:`
directives in `tests/compose/*.yml` keep working unchanged. **The directory is
generated and gitignored -- do not edit it or check it in.** To change anything
in it, change mender-testkit and release a new version.

## Installing Dependencies

### Isolating Python Dependencies (Optional, but recommended)

In order to avoid dependency mismanagement due to Python packages differing from
one test environment to the other, it is recommended to use a Python virtual
environment.

#### Initialize the Virtual Environment

```bash
cd <integration-dir>/tests
python3 -m venv <name-of-virtualenv-folder>
```

#### Activate the Virtual Environment

```bash
source <name-of-virtualenv-folder>/bin/activate
```

This now means that you have a clean Python environment, and no packages you
have previously installed outside of this virtual environment will be
discoverable by Python.

Verify the virtual environment through running

```bash
python3 --version
Python 3.12.x
which python3
/path/to/current/dir/venv/bin/python3
```

mender-testkit requires Python 3.10 or newer. 

Once you are done, the virtual environment is deactivated with

```bash
deactivate
```

### System Dependencies

#### Alpine Linux

```bash
apk --update add $(cat requirements-system/apk-requirements.txt)
```

#### Debian

```bash
apt install -yq $(cat requirements-system/deb-requirements.txt)
```

### Python

```bash
pip3 install -r requirements-python/python-requirements.txt
```

> The Python install works the same whether or not a Python virtual environment
> is active. But with a virtual environment active, the dependencies will keep
> your native Python environment clean.


-------------------------------------------------------------------------------


## Running the Tests Locally

> The tests can be run locally without any further involvement as long as all
> the dependencies have been installed and are at the correct version. However,
> managing dependencies, especially with Python, can be a hassle. Therefore it is
> recommended to add a virtual Python environment to isolate the dependencies
> needed for running the integration tests.

### Running the Tests

Next, run all the tests (Open-Source and Enterprise) with the `run.sh` script.

```bash
./run.sh
```

Run only the Open-Source tests with

```bash
./run.sh -- -k 'not Enterprise'
```

And Enterprise only

```bash
./run.sh -- -k 'Enterprise'
```

**NOTE**: This is dependent upon having a functioning Docker environment, and
being logged in to `registry.mender.io` for the Enterprise tests.

`run.sh --help` lists the rest. The two flags worth knowing:

| Flag                 | Effect                                                                        |
| :------------------- | :---------------------------------------------------------------------------- |
| `--no-download`      | Skip downloading `mender-artifact` and the artifact-gen scripts, and skip the up-front `docker compose pull` of the backend images |
| `--get-requirements` | Download those tools into `./downloaded-tools` and exit                        |

Parallelism comes from pytest-xdist; `XDIST_JOBS_IN_PARALLEL_INTEGRATION` sets
the worker count (default `auto`).

### Selecting the Server Version

`MENDER_IMAGE_TAG` picks the tag of every backend image, and defaults to `main`:

```bash
MENDER_IMAGE_TAG=v4.1.3 ./run.sh
```

`MENDER_SERVER_TAG` is accepted as an alias for it, so the older pipeline
schedules that pin released server versions keep working. Set one or the other,
not an empty value -- an empty `MENDER_IMAGE_TAG` falls through to the compose
file's own `${MENDER_IMAGE_TAG:-latest}` and would test `:latest` rather than
`:main`.

## Running with Custom Images

### A Custom Backend Service

The backend services are built in the
[mender-server](https://github.com/mendersoftware/mender-server) repository, not
this one. Its Makefile takes the same `MENDER_IMAGE_TAG` variable the compose
files do, so building and running against your own build is a matter of agreeing
on a tag:

```bash
cd /path/to/mender-server
MENDER_IMAGE_TAG=my-build make -C backend docker
```

```bash
cd /path/to/integration/tests
MENDER_IMAGE_TAG=my-build ./run.sh --no-download
```

Two things to note. `MENDER_IMAGE_TAG` applies to *every* backend image, so all
of them have to exist locally at that tag -- hence `make docker` rather than a
single `<service>-docker` target. And `--no-download` is what stops `run.sh`
from trying to pull that tag from the registry before the run.

The Enterprise overlay already defaults to
`registry.mender.io/mender-server-enterprise`, so an Enterprise build needs
nothing beyond the same tag. Override `MENDER_IMAGE_REGISTRY` and
`MENDER_IMAGE_REPOSITORY` only if you built under different coordinates.

### A Custom Client

Client images are still selected from this repository, by the `MENDER_CLIENT_*`
variables in the root [`.env`](../.env) file. For building a custom client the
approach is a little different from the backend, due to the fact that the client
comes bundled with a Yocto image. Therefore, in order to build and run a custom
client with the integration test setup, first build a Yocto image containing the
custom client, then build a Docker image containing that client:

```bash
cd /path/to/yocto/dir
source oe-init-build-env
bitbake core-image-full-cmdline
cd /path/to/meta-mender
cd meta-mender-qemu/docker
./build-docker qemux86-64 -t mendersoftware/mender-client-qemu:my-build
```

Then point the tests at it:

```bash
MENDER_CLIENT_QEMU_TAG=my-build ./run.sh
```

Also remember to add the custom sources to the Yocto `conf/local.conf` file,
which for the Mender client is

> 'conf/local.conf'
```bash
PREFERRED_VERSION:pn-mender = "master-git%"
EXTERNALSRC:pn-mender = "$GOPATH"
```

And for Mender-Artifact

> 'conf/local.conf'
```bash
PREFERRED_VERSION:pn-mender-artifact = "master-git%"
EXTERNALSRC:pn-mender-artifact = "$GOPATH"
PREFERRED_VERSION:pn-mender-artifact-native = "master-git%"
EXTERNALSRC:pn-mender-artifact-native = "$GOPATH"
```

> Remember to add your '$GOPATH' in the conf file, it is not taken from the environment.

-------------------------------------------------------------------------------

## Known Issues

#### OS X

Running the integration tests on OS X has historically not been straightforward,
due to https://github.com/docker/docker/issues/22753. It is not covered by CI.


## Tips and Tricks

An interrupted run leaves roughly twenty containers per xdist worker behind,
under compose projects named `mender<N>`. `run.sh` sweeps those up on the next
start; to see what is still lying around:

```bash
docker ps -a --format '{{.Label "com.docker.compose.project"}}' | sort -u | grep -E '^mender[0-9]+$'
```

Per-test logs and mongodumps from failures land in `mender_test_logs/`, and the
HTML summary in `report.html`.
