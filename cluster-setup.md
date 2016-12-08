<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-generate-toc again -->
**Table of Contents**

- [Intro](#intro)
- [Docker Swarm](#docker-swarm)
    - [`docker-machine`](#docker-machine)
    - [Deploying mender to swarm](#deploying-mender-to-swarm)
        - [Create swarm manager](#create-swarm-manager)
        - [Create swarm nodes](#create-swarm-nodes)
        - [Deploying with docker-compose](#deploying-with-docker-compose)
            - [`docker-compose-swarm-mode`](#docker-compose-swarm-mode)
        - [Deploying with `docker service`](#deploying-with-docker-service)
            - [Cluster network](#cluster-network)
            - [Defining and starting services](#defining-and-starting-services)
            - [Scaling](#scaling)
            - [Troubleshooting](#troubleshooting)
- [Kubernetes](#kubernetes)

<!-- markdown-toc end -->

# Intro

This guide details installation of Mender backend using a two clustering setups:
Docker Swarm and Kubernetes.

# Docker Swarm

Required components:

* Docker, version 1.12.3, build 6b644ec
* [docker-machine](https://github.com/docker/machine/), version 0.8.2, build e18a919
* (optional)
  [docker-machine-driver-kvm](https://github.com/dhiltgen/docker-machine-kvm),
  version 0.7.0, build a3882af
* [docker-compose](https://github.com/docker/compose/), version 1.7.1, build 6c29830

## `docker-machine`

`docker-machine` is a tool for creating and managing docker machines. It is
capable of setting up virtual machines on local host
running [boot2docker](http://boot2docker.io/) Linux distribution. Machines
created this way can join a swarm setup acting as manager or worker nodes.
 
By default `docker-machine` uses a VirtualBox driver for creating VMs on Linux
hosts. While possibly user-friendly, the driver requires a working VirtualBox
installation. Given that VirtualBox requires kernel drivers that are maintained
out of the main tree, support for newere kernels is usually lagging, thus
limiting the practical use of this solution. `docker-machine-driver-kvm` is an
alternative driver that uses KVM/libvirt stack for creating VMs.

`docker-machine` provides a number of drivers capable of managing docker hosts
as VMs running locally as well as on a number of cloud provider setups (EC2,
Azure, DigitalOcean, OpenStack, GCE).

## Deploying mender to swarm

### Create swarm manager

In this guide, local machine will act as swarm manager. The machine needs to be
reachable by VMs that will become a part of the swarm. Depending on
`docker-machine` driver used, the VMs will be reachable through one the host
network interfaces. In this guide, we are using KVM/libvirt driver, hence
created machines will be bridged with one of `virbr*` interfaces. In this
particular case, the host interface used is `virbr1` with an IP address
`192.168.42.1/16`. Note, that both the interface name and its address are host
specific.

To make current machine act as a swarm manager run the following command:

```
user@localhost# docker swarm init --advertise-addr 192.168.42.1

Swarm initialized: current node (2jksrvbhm0xd9hjbm12p62jut) is now a manager.

To add a worker to this swarm, run the following command:

    docker swarm join \
    --token SWMTKN-1-280hmdlzp85mmwggm5k02yppeiy8ln6yrlgpswnu5xjffxdhu5-64mtt8dzxjarsazs0qqnbgoyn \
    192.168.42.1:2377

To add a manager to this swarm, run 'docker swarm join-token manager' and follow the instructions.
```

### Create swarm nodes

Create 2 nodes that will act as workers.

Create the first node:

```
docker-machine create -d kvm --swarm node0
```

Create second node:

```
docker-machine create -d kvm --swarm node1
```

Have each node join the swarm by running the following command, replacing
`<node-name>` with actual node name, ex. `node0`, `node1`:

```
user@localhost# docker-machine ssh <node-name> "docker swarm join \
     --token SWMTKN-1-280hmdlzp85mmwggm5k02yppeiy8ln6yrlgpswnu5xjffxdhu5-64mtt8dzxjarsazs0qqnbgoyn \
     192.168.42.1:2377"
This node joined a swarm as a worker.
```

Running `docker info` on swarm manager host (local machine) will show basic
information about swarm status:

```
user@localhost# docker info
<....>
Swarm: active
 NodeID: 2jksrvbhm0xd9hjbm12p62jut
 Is Manager: true
 ClusterID: 1gol4qwi27yivjlb79swtc5jo
 Managers: 1
 Nodes: 3
 Orchestration:
  Task History Retention Limit: 5
 Raft:
  Snapshot Interval: 10000
  Heartbeat Tick: 1
  Election Tick: 3
 Dispatcher:
  Heartbeat Period: 5 seconds
 CA Configuration:
  Expiry Duration: 3 months
 Node Address: 192.168.42.1
<...>
```

The nodes should be visible when listing them with `docker node ls`:

```
user@localhost# docker node ls
ID                           HOSTNAME      STATUS  AVAILABILITY  MANAGER STATUS
2jksrvbhm0xd9hjbm12p62jut *  localhost     Ready   Active        Leader
9ea4s5zp89gw7kusxuqqp9ah0    node1         Ready   Active        
au6g1ipw98d3r3vugl9ht3v85    node0         Ready   Active        

```

Running `docker info` on swarm nodes will contain this output:

```
user@localhost# docker-machine ssh node1 "docker info"
<....>
Swarm: active
 NodeID: 9ea4s5zp89gw7kusxuqqp9ah0
 Is Manager: false
 Node Address: 192.168.42.227
<....>

```

### Deploying with docker-compose

The process of deploying Mender with `docker-compose` is largely unchanged from
the single host setup. To start the stack:

```
user@localhost# docker-compose up -d
Creating network "integration_mender" with the default driver
Creating integration_minio_1
Creating integration_mender-mongo-inventory_1
Creating integration_mender-mongo-device-adm_1
Creating integration_mender-mongo-useradm_1
Creating integration_mender-mongo-device-auth_1
Creating integration_mender-client_1
Creating integration_mender-mongo-deployments_1
Creating integration_mender-gui_1
Creating integration_mender-etcd_1
Creating integration_mender-inventory_1
Creating integration_mender-device-adm_1
Creating integration_mender-useradm_1
Creating integration_mender-device-auth_1
Creating integration_mender-deployments_1
Creating integration_mender-api-gateway_1
```

Unfortunately docker-compose is not yet up to date with Docker's 1.12 features
and the services are not automatically scheduled to run on swarm cluster nodes.

Running `docker ps` locally reveals that all services are running on local
machine:

```
user@localhost# docker ps
CONTAINER ID        IMAGE                                      COMMAND                  CREATED             STATUS              PORTS                    NAMES
70d19898a37b        mendersoftware/api-gateway:latest          "/usr/local/openresty"   7 seconds ago       Up 3 seconds        0.0.0.0:8080->443/tcp    integration_mender-api-gateway_1
d930d6675162        mendersoftware/deployments:latest          "/usr/bin/deployments"   26 seconds ago      Up 7 seconds                                 integration_mender-deployments_1
64ba78a3651e        mendersoftware/deviceauth:latest           "/usr/bin/deviceauth "   28 seconds ago      Up 7 seconds                                 integration_mender-device-auth_1
452a0d063646        mendersoftware/useradm:latest              "/usr/bin/useradm -co"   35 seconds ago      Up 9 seconds                                 integration_mender-useradm_1
66cd0b2627e3        mendersoftware/deviceadm:latest            "/usr/bin/deviceadm -"   36 seconds ago      Up 13 seconds                                integration_mender-device-adm_1
91fea707e5a5        mendersoftware/inventory:latest            "/usr/bin/inventory -"   39 seconds ago      Up 15 seconds                                integration_mender-inventory_1
49ea9afc78b4        microbox/etcd:latest                       "/bin/etcd -data-dir="   51 seconds ago      Up 16 seconds       4001/tcp, 7001/tcp       integration_mender-etcd_1
6f435208ea54        mendersoftware/mender-client-qemu:latest   "./entrypoint.sh"        51 seconds ago      Up 23 seconds       8822/tcp                 integration_mender-client_1
738887c23dcb        mendersoftware/gui:latest                  "/bin/sh -c '/root/se"   51 seconds ago      Up 26 seconds                                integration_mender-gui_1
1cb5465256c3        mongo:latest                               "/entrypoint.sh mongo"   51 seconds ago      Up 28 seconds       27017/tcp                integration_mender-mongo-deployments_1
4c4a0dc6ce5c        mongo:latest                               "/entrypoint.sh mongo"   51 seconds ago      Up 32 seconds       27017/tcp                integration_mender-mongo-device-auth_1
ed2af2f6653a        mongo:latest                               "/entrypoint.sh mongo"   51 seconds ago      Up 37 seconds       27017/tcp                integration_mender-mongo-useradm_1
01883e627535        mongo:latest                               "/entrypoint.sh mongo"   51 seconds ago      Up 40 seconds       27017/tcp                integration_mender-mongo-device-adm_1
b944374f62e0        mongo:latest                               "/entrypoint.sh mongo"   51 seconds ago      Up 41 seconds       27017/tcp                integration_mender-mongo-inventory_1
21c9034a85e5        minio/minio:RELEASE.2016-10-07T01-16-39Z   "minio server /export"   51 seconds ago      Up 46 seconds       0.0.0.0:9000->9000/tcp   integration_minio_1
```

At the same time, none of the services defined in compose file is running on
cluster nodes:

```
docker-machine ssh node0 docker ps
CONTAINER ID        IMAGE               COMMAND                  CREATED             STATUS                          PORTS               NAMES
6c0136807fee        swarm:latest        "/swarm join --advert"   About an hour ago   Restarting (1) 18 minutes ago   2375/tcp            swarm-agent
```

The problem is captured in the following docker issues:
- [docker-compose #3656](https://github.com/docker/compose/issues/3656)

Alternatives are to use `docker-compose bundle` (an experimental feature) along with `docker deploy`.

#### `docker-compose-swarm-mode`

A community solution to deploying docker-compose setup into a swarm cluster is
provided in form of [`docker-compose-swarm-mode`](https://github.com/ddrozdov/docker-compose-swarm-mode) script.

The script (revision 86d0f726ee48e1dc2a2e82cbf26f68fd4c151334) does not work and
crashes under both Python 3.5 and 2.7.


### Deploying with `docker service`

Since swarm mode has been integrated with Docker in release 1.12, `docker
service` is the preferred method of starting services in a swarm cluster.

Setting up mender in a cluster is a more complicated process and requires
setting/creating missing bits and pieces by hand. 

#### Cluster network

Mender cluster is using its own internal network. The network is created by
running:

`docker network create --driver overlay cluster-mender`

Note, `--opt encrypted` does not work with boot2docker.

#### Defining and starting services

Currently (v1.12) it is not possible to assign network aliases to services
inside swarm. However, mender setup in docker-compose relies on particular
service naming and their aliases. For swarm mender cluster to work, names of
respective services had to be altered.

* Minio storage

NOTE: minio is expected to be found under `s3.docker.mender.io` alias, however
Docker does not allow names to include other characters than [a-zA-Z0-9]. Hence,
the services is named `minio` instead. Configuration of deployments service
needs to be updated accordingly.

```
docker service create --with-registry-auth \
 --name minio \
 --publish '9000:9000' \
 --network cluster-mender \
 --env 'MINIO_ACCESS_KEY=minio' \
 --env 'MINIO_SECRET_KEY=minio123' \
 --restart-max-attempts 2 \
 minio/minio:RELEASE.2016-10-07T01-16-39Z
```

* User Administration service 

```
docker service create --with-registry-auth \
 --name mender-useradm \
 --restart-max-attempts 2 \
 --network cluster-mender \
 --replicas 1 \
 mendersoftware/useradm:latest
```

```
docker service create --with-registry-auth \
 --name mender-mongo-useradm \
 --network cluster-mender \
 --restart-max-attempts 2 \
 --replicas 1 \
mongo:latest
```

* Inventory service

```
docker service create --with-registry-auth \
 --name mender-inventory \
 --restart-max-attempts 2 \
 --network cluster-mender \
 --replicas 1 \
 mendersoftware/inventory:latest
```

```
docker service create --with-registry-auth \
 --name mender-mongo-inventory \
 --network cluster-mender \
 --restart-max-attempts 2 \
 --replicas 1 \
mongo:latest
```

* Device Authentication service

```
docker service create --with-registry-auth \
 --name mender-device-auth \
 --restart-max-attempts 2 \
 --network cluster-mender \
 --replicas 1 \
 mendersoftware/deviceauth:latest
```

```
docker service create --with-registry-auth \
 --name mender-mongo-device-auth \
 --network cluster-mender \
 --restart-max-attempts 2 \
 --replicas 1 \
mongo:latest
```

* Device Admission service

```
docker service create --with-registry-auth \
 --name mender-device-adm \
 --restart-max-attempts 2 \
 --network cluster-mender \
 --replicas 1 \
 mendersoftware/deviceadm:latest
```

NOTE: device admission expects its mongo instance to be named
`mongo-device-adm`.

```
docker service create --with-registry-auth \
 --name mongo-device-adm \
 --network cluster-mender \
 --restart-max-attempts 2 \
 --replicas 1 \
mongo:latest
```

* Deployments service

NOTE: we're directing deployments service to use `minio` instead of
`s3.docker.mender.io`.

NOTE2: mongo instance is named `mongo-deployments`.

```
docker service create --with-registry-auth \
 --name mender-deployments \
 --network cluster-mender \
 --restart-max-attempts 2 \
 --replicas 1 \
 --env 'AWS_ACCESS_KEY_ID=minio' \
 --env 'AWS_SECRET_ACCESS_KEY=minio123' \
 --env 'AWS_URI=http://minio:9000' \
 mendersoftware/deployments:latest
```

```
docker service create --with-registry-auth \
 --name mongo-deployments \
 --network cluster-mender \
 --restart-max-attempts 2 \
 --replicas 1 \
mongo:latest
```

* GUI

```
docker service create --with-registry-auth \
 --name mender-gui \
 --restart-max-attempts 2 \
 --network cluster-mender \
 --replicas 1 \
 mendersoftware/gui:latest
```

* API Gateway

```
docker service create --with-registry-auth \
 --name mender-api-gateway \
 --network cluster-mender \
 -p 8080:443 \
 --env 'MAPPED_PORT=8080' \
 --restart-max-attempts 2 \
 --replicas 1 \
 mendersoftware/api-gateway:latest
```

List defined services by calling `docker service ls`:

```
user@localhost# docker service ls
ID            NAME                      REPLICAS  IMAGE                                     COMMAND
03ulho5i1txp  mender-mongo-device-auth  1/1       mongo:latest                              
0sbl53n2nnde  mender-mongo-useradm      1/1       mongo:latest                              
20qai1rfww5e  mender-useradm            1/1       mendersoftware/useradm:latest             
298dmk6q8i6u  mender-api-gateway        1/1       mendersoftware/api-gateway:latest         
2cwticyra10r  minio                     1/1       minio/minio:RELEASE.2016-10-07T01-16-39Z  
3runedol5f16  mender-device-auth        1/1       mendersoftware/deviceauth:latest          
4anhz8jcmdfi  mender-inventory          1/1       mendersoftware/inventory:latest           
4r6biar5zzb3  mender-device-adm         1/1       mendersoftware/deviceadm:latest           
4ugq2wpg9nnn  mender-mongo-inventory    1/1       mongo:latest                              
5xkm42z8ms49  mongo-device-adm          1/1       mongo:latest                              
7z1bpw95r02d  mender-deployments        1/1       mendersoftware/deployments:latest         
8vamv85n4dcd  mender-gui                1/1       mendersoftware/gui:latest                 
bp69jjb3itrh  mongo-deployments         1/1       mongo:latest
```

List containers running on respective nodes bu calling `docker node ps <node>`:

```
user@localhost# docker node ps comp-006-thk                                                                               <<< 1 ↵
ID                         NAME                    IMAGE                            NODE          DESIRED STATE  CURRENT STATE        ERROR
7xwt7dd5dcgbglgobqyqh209k  mender-gui.1            mendersoftware/gui:latest        comp-006-thk  Running        Running 2 hours ago  
b9kb8pxjzozchxdaaszvzkh0b  mender-device-adm.1     mendersoftware/deviceadm:latest  comp-006-thk  Running        Running 2 hours ago  
2czeuorsbqbxjfzygtt9m59tv  mender-inventory.1      mendersoftware/inventory:latest  comp-006-thk  Running        Running 2 hours ago  
5ii0b0c7laro4ohnm0oqap98i  mender-mongo-useradm.1  mongo:latest                     comp-006-thk  Running        Running 2 hours ago  
user@localhost# docker node ps node0       
ID                         NAME                        IMAGE                              NODE   DESIRED STATE  CURRENT STATE          ERROR
b7ofnkc1e6xo8nng7abujhtyq  mender-api-gateway.1        mendersoftware/api-gateway:latest  node0  Running        Running 7 minutes ago  
6fvq2aupfg0h3cl1viaj8p93l  mender-deployments.1        mendersoftware/deployments:latest  node0  Running        Running 9 minutes ago  
6t8apcav2a3030jf1txaq3yic  mender-mongo-device-auth.1  mongo:latest                       node0  Running        Running 2 hours ago    
cdujnmfc8wroraofl6dj7umzp  mender-device-auth.1        mendersoftware/deviceauth:latest   node0  Running        Running 2 hours ago    
4kyjpbxlkw20b52d8la9bsct2  mender-useradm.1            mendersoftware/useradm:latest      node0  Running        Running 2 hours ago    
user@localhost# docker node ps node1
ID                         NAME                      IMAGE                                     NODE   DESIRED STATE  CURRENT STATE          ERROR
3q1utj6f3je8mux7yzwlhitfm  mongo-deployments.1       mongo:latest                              node1  Running        Running 9 minutes ago  
8p0gg5z3mgk4vbw3s5taw0yga  mender-api-gateway.1      mendersoftware/api-gateway:latest         node1  Shutdown       Failed 2 hours ago     "task: non-zero exit (1)"
2hqa7iykxaagtamtofk01moi0   \_ mender-api-gateway.1  mendersoftware/api-gateway:latest         node1  Shutdown       Failed 2 hours ago     "task: non-zero exit (1)"
3jhqfyb5vyqv67q0ngzz1xupa   \_ mender-api-gateway.1  mendersoftware/api-gateway:latest         node1  Shutdown       Failed 2 hours ago     "task: non-zero exit (1)"
655d3jdbd8kx9ie4u37auhvgk  mongo-device-adm.1        mongo:latest                              node1  Running        Running 2 hours ago    
7aco7k9buhgl06ewhdl7p8zhv  mender-mongo-inventory.1  mongo:latest                              node1  Running        Running 2 hours ago    
67lb0nf2bsk4q9bkhjo8u22pb  minio.1                   minio/minio:RELEASE.2016-10-07T01-16-39Z  node1  Running        Running 2 hours ago 
```

Services `mender-api-gateway` show failures that happened in the past. Further
inspecting `mender-api-gateway` failures:

```
user@localhost# docker service ps mender-api-gateway
ID                         NAME                      IMAGE                              NODE   DESIRED STATE  CURRENT STATE          ERROR
b7ofnkc1e6xo8nng7abujhtyq  mender-api-gateway.1      mendersoftware/api-gateway:latest  node0  Running        Running 9 minutes ago  
8p0gg5z3mgk4vbw3s5taw0yga   \_ mender-api-gateway.1  mendersoftware/api-gateway:latest  node1  Shutdown       Failed 2 hours ago     "task: non-zero exit (1)"
2hqa7iykxaagtamtofk01moi0   \_ mender-api-gateway.1  mendersoftware/api-gateway:latest  node1  Shutdown       Failed 2 hours ago     "task: non-zero exit (1)"
3jhqfyb5vyqv67q0ngzz1xupa   \_ mender-api-gateway.1  mendersoftware/api-gateway:latest  node1  Shutdown       Failed 2 hours ago     "task: non-zero exit (1)"

```

The leftmost column contains task IDs, these be further inspected by calling
`docker inspect <ID>`.

Outstanding docker issues: 
- [docker service ps truncated output](https://github.com/docker/docker/issues/25332)
- [docker service --net-alias support](https://github.com/docker/docker/issues/24787)

#### Scaling

Suppose we want to scale `mender-device-adm` service and have 2 instances
instead of one. This can be achieved by running:

```
user@localhost# docker service scale mender-device-adm=2
mender-device-adm scaled to 2
```

This should be visible in `docker service ps` output:

```
user@localhost: docker service ps mender-device-adm
ID                         NAME                 IMAGE                            NODE          DESIRED STATE  CURRENT STATE          ERROR
b9kb8pxjzozchxdaaszvzkh0b  mender-device-adm.1  mendersoftware/deviceadm:latest  localhost     Running        Running 2 hours ago
4f9pjmkgs03fgomxe5z911a4u  mender-device-adm.2  mendersoftware/deviceadm:latest  node1         Running        Running 6 minutes ago
```

Second instance of `mender-device-adm` was scheduled to run on `localhost` node.


#### Troubleshooting

* `docker service ls` - check REPLICAS count

* `docker service ps mender-api-gateway` - list failed tasks, determine node the
  task was running on
* `docker inspect <id>` - inspect failed task

* `docker-machine ssh <node> docker ps` - list containers on particular node,
  find a failed or a running container
  
* `docker-machine ssh <node> docker logs <container-ID>` - see the logs of a
  particular container


# Kubernetes

