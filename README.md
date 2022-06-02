Mender: Integration
==============================================

Mender is an open source over-the-air (OTA) software updater for embedded Linux
devices. Mender comprises a client running at the embedded device, as well as a
server that manages deployments across many devices.


This repository contains a Docker-based environment allowing to run all Mender
backend services as a single system. Each service has a dedicated Dockerhub
repository, where tagged Docker builds are stored. Images are pulled and started
in a coordinated fashion via `docker-compose` and the associated
`docker-compose.yml` file.

Requirements:

* docker-engine 1.10
* docker-compose 1.7


![Mender logo](mender_logo.png)


## Getting started

To start using Mender, we recommend that you begin with the Getting started
section in [the Mender documentation](https://docs.mender.io/).


## Services

The integration environment brings together the following services:

- [Mender Device Authentication Service](https://github.com/mendersoftware/deviceauth)
- [Mender Deployment Service](https://github.com/mendersoftware/deployments)
- [Mender Device Inventory Service](https://github.com/mendersoftware/inventory)
- [Mender User Administration Service](https://github.com/mendersoftware/useradm)
- [Træfik](https://traefik.io/traefik/)
- [Minio](https://www.minio.io/) object storage

## How to use in production

A provided `docker-compose.yml` file will provision the following set of
services:

```
        |
        |                                            +-------------------------+
        |                                            |                         |
        |                                       +--->|  Device Authentication  |<---+
        |                                       |    |  (mender-device-auth)   |    |
        |                                       |    +-------------------------+    |
        |        +-----------------------+      |    |                         |    |
   port |        |                       |      +--->|  Inventory              |<---+     +----------------------------------+
    443 | <----> |  API Gateway          |      |    |  (mender-inventory)     |    +---> |  Workflows Engine                |
        |        |  (traefik)            |<-----+    +-------------------------+    |     |  (mender-workflows-server)       |
        |        +-----------------------+      |    |                         |    |     |  (mender-workflows-worker)       |
        |                                       +--->|  User Administration    |    |     |  (mender-create-artifact-worker) |
        |                                       |    |  (mender-useradm)       |<---+     +----------------------------------+
        |                                       |    +-------------------------+    |
        |                                       +--->|                         |    |
        |                                       |    |  Device Config          |<---+
        |                                       |    |  (mender-deviceconfig)  |    |
        |                                       |    +-------------------------+    |
        |                                       +--->|                         |    |
        |                                       |    |  Deployments            |<---+
        |                                       |    |  (mender-deployments)   |    |
        |                                       |    +-------------------------+    |
        |                                       +--->|                         |<---+
        |                                       |    |  Device Connect         |          +--------+
        |                                       |    |  (mender-deviceconnect) |<-------->|        |
        |                                       |    +-------------------------+          |  Nats  |
        |                                       +--->|                         |          |        |
        |                                            |  Minio                  |          +--------+
        |                                            |                         |
        |                                            +-------------------------+
        |
```

It is customary to provide deployment specific overrides in a separate compose
file. This can either be `docker-compose.override.yml` file (detected and
included automatically by `docker-compose` command) or a separate file. If a
separate file is used, it needs to be explicitly included in command line when
running `docker-compose` like this:

```
docker-compose -f docker-compose.yml -f my-other-file.yml up
```

Mender artifacts file are served from storage backend provided by Minio object
storage in the reference setup.

A demo setup uses `docker-compose.demo.yml` overlay file to override different
aspects of configuration and can be used as an example when deploying to
production.

For details on configuration and administration
consult [Administration guide](https://docs.mender.io/Administration)
in [Mender documentation](https://docs.mender.io/).

## Integrating a new service

Adding a new service to the setup involves:

* creating a dedicated Dockerfile
* setting up a Dockerhub repository and a CI build pipeline
* adding the service's config under `docker-compose.yml`

Guidelines and things to consider:

* assign the service a name that is unique within `docker-compose.yml`
* add the service to the `mender` network
* setup the correct routing and authentication for the new service in the
[API gateway config](https://github.com/mendersoftware/integration/tree/master/config/traefik)

## How to use in development

Running the integration setup brings up a complete system of services; as such
it can readily be used for testing, staging or demo environments.

In development scenarios however some additional strategies apply, described in
the following sections.

### Developing a new service

The default approach to integrating a service, involving the full build
pipeline, is not conducive to quick develop/build/test cycles. Therefore, when
prototyping a new service against an existing system, it can be useful to:

* create a dedicated Dockerfile for your service and build it locally:
```
cd FOLDER_WITH_DOCKERFILE
docker build -t MY_DOCKER_TAG  .
```

* include the service as usual in `docker-compose.yml`, paying attention to the
  image tag you just created:

```
    #
    # myservice
    #
    myservice:
        image: MY_DOCKER_TAG
```

* add any number of [volumes](https://docs.docker.com/compose/compose-file/#/volumes-volume-driver)
to your service, to mount your local binaries and config files into the Docker
container, e.g.:

```
    myservice:
        ...
        volumes:
             /some/localhost/folder/myconfig.yaml:/usr/bin/myconfig.yaml
             /some/localhost/folder/mybinary:/usr/bin/mybinary
            ...
```

When you run the setup, your new service will be a part of it; also, it will be
running binaries from your local machine, which means you can quickly recompile
them and restart `integration` for changes to take effect.

Note that the correct routing and auth still have to be set up in the Mender API Gateway for the service to be accessible
from the outside. To experiment with the new configuration:

* modify `config/traefik/traefik.yaml` to achieve the configuration you desire

or

* mount an additional config to the `mender-api-gateway` service under `/etc/traefik/config/traefik.<new-service-name>.yaml`
your changes will take effect when you restart the whole setup

### Troubleshooting/developing an existing service

For troubleshooting and debugging, a similar approach involving Docker `volumes`
can be used. Assuming that a given service's image has been pulled to your local
machine, mount your local binaries and config files via `docker-compose.yml`:

```
    service:
        ...
        volumes:
             /some/localhost/folder/myconfig.yaml:/usr/bin/config.yaml
             /some/localhost/folder/mybinary:/usr/bin/service-binary
            ...
```

To obtain the locations of both binaries and config files, refer the service's
dedicated Dcokerfile.

Again, recompiling your local binary and restarting `integration` will make your
changes take effect. Note that the correct API Gateway config is probably
already set up for an existing service; if not, refer the previous section on
how to modify it.

### Enabling non-SSL access

For debugging purposes or when using third party SSL reverse proxy, it may be useful to enable non-SSL access.  
API Gateway configuration enables plain HTTP on port 80 when setting the `SSL` environment variable to `'false'`.  
The nginx configuration will only be changed on container creation. If you previously ran with SSL, delete and re-create the container.  
An example compose file can be included like this:

```
./demo -f docker-compose.no-ssl.yml up
```

**NOTE** make sure that plain HTTP port is not published in production
deployment. Use a reverse proxy for example.

## Demo client

The setup comes with a predefined client service (mender-client) that runs a
qemu VM in a container. The client will connect to the backend by accessing
`docker.mender.io` host (an alias assigned to `mender-api-gateway` service). The
client container will not be started by default and needs to be included
explicitly when running docker compose by listing multiple compose files as
described in [compose manual](https://docs.docker.com/compose/extends/#/multiple-compose-files).

To start the backend and a demo client run the following command:

```
docker-compose -f docker-compose.yml -f docker-compose.client.yml up
```
## Known issues

For some a ValueError with the message "password and salt must not be empty" may occur when the `device.ssh_is_opened()` method in `device.py` gets called. If this happens the test tries to use your personal ssh key. A simple work around is to use the command

```
export HOME = /dummy
```

You may also be asked to "Enter password to private key". If you enter the keys password, the tests will continue. Your private key will not be used.

## Contributing

We welcome and ask for your contribution. If you would like to contribute to
Mender, please read our guide on how to best get started
[contributing code or documentation](https://github.com/mendersoftware/mender/blob/master/CONTRIBUTING.md).

## License

Mender is licensed under the Apache License, Version 2.0. See
[LICENSE](https://github.com/mendersoftware/integration/blob/master/LICENSE) for the
full license text.

## Security disclosure

We take security very seriously. If you come across any issue regarding
security, please disclose the information by sending an email to
[security@mender.io](security@mender.io). Please do not create a new public
issue. We thank you in advance for your cooperation.

## Connect with us

* Join the [Mender Hub discussion forum](https://hub.mender.io)
* Follow us on [Twitter](https://twitter.com/mender_io). Please
  feel free to tweet us questions.
* Fork us on [Github](https://github.com/mendersoftware)
* Create an issue in the [bugtracker](https://tracker.mender.io/projects/MEN)
* Email us at [contact@mender.io](mailto:contact@mender.io)
* Connect to the [#mender IRC channel on Libera](https://web.libera.chat/?#mender)

## Authors

Mender was created by the team at [Northern.tech AS](https://northern.tech), with many contributions from
the community. Thanks [everyone](https://github.com/mendersoftware/mender/graphs/contributors)!

[Mender](https://mender.io) is sponsored by [Northern.tech AS](https://northern.tech).
