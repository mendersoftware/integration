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


## Running the demo server

Start the Mender demo server with the following command:

```
./demo up
```

Access the Mender server on `https://localhost` using the user and password created by the script.
Save the credentials for later re-use.

For consequent runs of the script to create a new password, delete first all volumes with:

```
./demo down -v
```

### Virtual client

The setup comes with a predefined client service (mender-client) that runs a
qemu VM in a container. The client will connect to the backend by accessing
`docker.mender.io` host (an alias assigned to the API gateway service). The
client container will not run by default. You can manually launch it with:

```
docker-compose --client up
```

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
