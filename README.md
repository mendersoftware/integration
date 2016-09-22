# Integration

This project provides a Docker-based environment allowing to run all Mender
backend services as a single system.

##Requirements

* docker-engine 1.10
* docker-compose 1.7

##Overview

The solution is based on the following assumptions:

* each service has a dedicated Dockerfile, typically living in the service's
  github repo
* for each service, Travis automatically builds a docker image and pushes it to
  a dedicated Dockerhub repo
* coordinated pulling/running of all Docker containers is performed by
  `docker-compose` via the master `docker-compose.yml` file
* common service configuration is included in `common.yml/mender-base`, which
  can be extended by any new service

##Basic Usage

Run the environment:

```
bash up
```

At this point all services should be up and running, which can be verified by:

```
sudo docker-compose ps

       Name               Command         State           Ports
------------------------------------------------------------------------
mender-api-gateway   ./dummy-entrypoint   Up
mender-artifacts     ./artifacts          Up      0.0.0.0:8080->8080/tcp
mender-device-auth   ./deviceauth         Up
...

```

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
* setting up a Dockerhub repo + Travis image build
* adding the service's config under `docker-compose.yml`

Guidelines/things to consider:

* assign the service a name that is unique within `docker-compose.yml`
* extend the service `mender-common/common.yml`
* include a port mapping to make the service available via `localhost`
    * important in development for quick requests via curl/DHC/etc.
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

In development scenarios however some additional strategies apply, described in
the following sections.

### Developing a new service
When developing a new service (not included in `docker-compose` yet) against an
existing system:

* build and run the environment
* temporarily use `localhost` and exposed/mapped service ports to access
  existing services

### Troubleshooting/developing an existing service
It's important to note that for every docker image, the embedded binaries and
configs can be overriden by mounting a local version in their place, e.g.:

```
    myservice:
        volumes:
            - /some/localhost/folder/config.yaml:/usr/bin/config.yaml
            - /some/localhost/folder/mybinary:/usr/bin/mybinary
```
The primary strategy of developing existing services should be:
* make the necessary local modifications
* compile the service
* mount the compiled binary
* run the environemt as usual via ```docker-compose up```

An alternative, but more complex approach:
* disable the service in `docker-compose` (comment the relevant section)
* modify the service and run it from its binary
* all other services should be temporarily configured to access the developed
  one via `localhost`'s `docker0` address
* as above, the service under dev should access other services via ports exposed
  on `localhost`

## Configuration management
* currently some default configuration is embedded in built images
* eventually configuration will be managed by etcd, so services should gradually
migrate to use it instead

## Helpers & `/etc/hosts`

Script `up` can be used to automate augmenting `/etc/hosts` with required
entries (as needed) and running `docker-compose` in one shot.

...note

    `up` script modifies `/etc/hosts`, thus it requires root privileges to run

Running `up -n` will only update `/etc/hosts`, without starting docker
environment.
