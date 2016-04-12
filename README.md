# Integration

This project provides a Docker-based environment allowing to run all Mender
backend services as a single system.

##Requirements

* docker-engine 1.10
* docker-compose 1.7

##Overview

The solution is based on the following assumptions:

* each service has a dedicated Dockerfile
* upon building, each Dockerfile pulls the service's latest build artifacts
  from Mender's S3 storage
* upon running, the Docker container starts the service
* coordinated building and running of all Docker containers is performed by
  `docker-compose` via the master `docker-compose.yml` file
* common service configuration is included in `common.yml/mender-base`, which
  can be extended by any new service

##Basic Usage

Before building, set the following environment variables (credentials for
the `mender-buildsystem` S3 bucket).

* `S3_KEY`
* `S3_SECRET`

Next, build the environment:

```
sudo -E docker-compose build
```

Run the environment:

```
sudo -E docker-compose up -d
```

At this point all services should be up and running, which can be verified by:

```
sudo docker-compose ps

       Name               Command         State           Ports
------------------------------------------------------------------------
mender-api-gateway   ./dummy-entrypoint   Up
mender-artifacts     ./artifacts          Up      0.0.0.0:8080->8080/tcp
mender-device-auth   ./dummy-entrypoint   Up
...

```

(NOTE: for now only the `mender-artifacts` service is implemented - other
containers run 'dummy' entrypoints just to demonstrate the idea).

A couple of important points to notice:

* dockerized services join a common network, where they can access each other
  via their service names (e.g. `http://mender-artifacts:8080`)
* a service can also be accessed from the Docker host (localhost) via its mapped
  ports (`ports` directive in `docker-compose.yml`)
* if necessary, a service can access the Docker host via the host's address on
  the `docker0` interface, e.g.:

```
ip a

...
8: docker0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state DOWN group default
    link/ether 02:42:31:dd:6e:6c brd ff:ff:ff:ff:ff:ff
    inet 172.17.0.1/16 scope global docker0
       valid_lft forever preferred_lft forever
...
```

##Integrating a new service

Adding a new service to the setup involves:

* creating a dedicated Dockerfile
* adding the service's config under `docker-compose.yml`

Guidelines/things to consider:

* assign the service a name that is unique within `docker-compose.yml`
* extend the service `mender-common/common.yml`
* include a port mapping to make the service available via `localhost`
    * important in development for quick requests via curl/DHC/etc.
* include the S3 build paths as `build args` in `docker-compose.yml`
    * enables the image to pull a different build than `latest`, if necessary
* mount log destinations to Docker host's folder, e.g.:

```
    myservice:
        ...
        volumes:
            - /var/log/myservice:/var/log/myservice
        ...
```

##How to use in development

The simple build & run procedure sets up a complete system of services in their
latest versions. As such it can readily be used for testing, staging or production
environments.

In development however, it might be necessary to do some tweaking to e.g. work
with a different build than `latest`, or substitute one of the services with a
locally developed (not-yet-dockerized) version.

Below are some tips on using this setup in such scenarios.

### Specifying a different build version
Provided that a service correctly parametrizes its build artifacts' S3 paths,
selecting a different build is a matter of tweaking the build args, e.g. setting:

```
    build:
        args:
            S3_BIN_PATH: "mender-buildsystem/mendersoftware/artifacts/dev/master/216/linux_amd64/artifacts"
```

instead of:

```
    build:
        args:
            S3_BIN_PATH: "mendersoftware/artifacts/latest/master/linux_amd64/artifacts"
```

### Providing a customized service config
A service's downloaded config file can be overriden by mounting a modified
version in its place:

```
    myservice:
        volumes:
            - ./some/localhost/folder/config.yaml:/usr/bin/config.yaml
```

### Developing a new service
When developing a new service (not included in `docker-compose` yet) against an
existing system:

* build and run the environment
* use `localhost` and exposed/mapped service ports to access existing services

### Troubleshooting/developing an existing service
* disable the service in `docker-compose` (comment the relevant section)
* modify the service and run it from its binary
* all other services should be temporarily configured to access the developed
  one via `localhost`'s `docker0` address
* as above, the service under dev should access other services via ports exposed
  on `localhost`

##TODOs, next steps, etc.
* agree on configuration management strategy across all services and environments
    * config files?
    * environment vars?
