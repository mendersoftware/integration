Mender: Integration
==============================================

Mender is an open source over-the-air (OTA) software updater for embedded Linux
devices. Mender comprises a client running at the embedded device, as well as
a server that manages deployments across many devices.

This repository contains a Docker-based environment allowing to run all Mender backend services as a single system. Each service has a dedicated Dockerhub repository, where tagged Docker builds are stored. Images are pulled and started in a coordinated fashion via `docker-compose` and the associated `docker-compose.yml` file.

Requirements:

* docker-engine 1.10
* docker-compose 1.7


![Mender logo](https://mender.io/user/pages/04.resources/_logos/logoS.png)


## Getting started

To start using Mender, we recommend that you begin with the Getting started
section in [the Mender documentation](https://docs.mender.io/).


## Services

The integration environment brings together the following services:

- [Mender Device Admission Service](https://github.com/mendersoftware/deviceadm)
- [Mender Device Authentication Service](https://github.com/mendersoftware/deviceauth)
- [Mender Deployment Service](https://github.com/mendersoftware/deployments)
- [Mender Device Inventory Service](https://github.com/mendersoftware/inventory)
- [Mender API Gateway](https://github.com/mendersoftware/mender-api-gateway-docker)
- [fake-s3](https://github.com/lphoward/fake-s3)

## Integrating a new service

Adding a new service to the setup involves:

* creating a dedicated Dockerfile
* setting up a Dockerhub repository and a CI build pipeline
* adding the service's config under `docker-compose.yml`

Guidelines and things to consider:

* assign the service a name that is unique within `docker-compose.yml`
* add the service to the `mender` network
* setup the correct routing and authentication for the new service in the
[Mender API Gateway](https://github.com/mendersoftware/mender-api-gateway-docker)
* extend the common service `mender-common/common.yml`

## How to use in development

Running the integration setup brings up a complete system of services; as such
it can readily be used for testing, staging or demo environments.

In development scenarios however some additional strategies apply, described in
the following sections.

### Developing a new service

The default approach to integrating a service, involving the full build pipeline, is not conducive to
quick develop/build/test cycles. Therefore, when prototyping a new service against an existing system,
it can be useful to:

* create a dedicated Dockerfile for your service and build it locally:
```
cd FOLDER_WITH_DOCKERFILE
docker build -t MY_DOCKER_TAG  .
```

* include the service as usual in `docker-compose.yml`, paying attention to the image tag you just created:
```
    #
    # myservice
    #
    myservice:
        image: MY_DOCKER_TAG
```

* add any number of [volumes](https://docs.docker.com/compose/compose-file/#/volumes-volume-driver) to your service,
to mount your local binaries and config files into the Docker container, e.g.:
```
    myservice:
        ...
        volumes:
             /some/localhost/folder/myconfig.yaml:/usr/bin/myconfig.yaml
             /some/localhost/folder/mybinary:/usr/bin/mybinary
            ...
```

When you run the setup, your new service will be a part of it; also, it will be running
binaries from your local machine, which means you can quickly recompile them and restart `integration`
for changes to take effect.

Note that the correct routing and auth still have to be set up in the Mender API Gateway for the service
to be accessible from the outside. To experiment with new configuration:
* copy the [Gateway's main config file](https://github.com/mendersoftware/mender-api-gateway-docker/blob/master/nginx.conf) locally
* in `docker-compose.yml`, again mount your local version inside the Gateway container:
```
    #
    # mender-api-gateway
    #
    mender-api-gateway:
        ...
        /some/localhost/folder/nginx.conf:/usr/local/openresty/nginx/conf/nginx.conf
```
Your changes will take effect when you restart the whole setup.

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

Again, recompiling your local binary and restarting `integration` will make
your changes take effect. Note that the correct API Gateway config is probably already
set up for an existing service; if not, refer the previous section on how to modify it.

## Contributing

We welcome and ask for your contribution. If you would like to contribute to Mender, please read our guide on how to best get started [contributing code or
documentation](https://github.com/mendersoftware/mender/blob/master/CONTRIBUTING.md).

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

* Join our [Google
  group](https://groups.google.com/a/lists.mender.io/forum/#!forum/mender)
* Follow us on [Twitter](https://twitter.com/mender_io?target=_blank). Please
  feel free to tweet us questions.
* Fork us on [Github](https://github.com/mendersoftware)
* Email us at [contact@mender.io](mailto:contact@mender.io)
