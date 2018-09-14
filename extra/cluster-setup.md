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
    - [`minikube`](#minikube)
    - [Deploying mender to Kubernetes cluster](#deploying-mender-to-kubernetes-cluster)
        - [Converting `docker-compose.yaml` with `kompose`](#converting-docker-composeyaml-with-kompose)
            - [Defining services](#defining-services)
        - [Publishing Mender services](#publishing-mender-services)
        - [Deploying Mender](#deploying-mender)
        - [Files](#files)
- [Followups & issues](#followups--issues)

<!-- markdown-toc end -->

# Intro

This guide details installation of Mender backend using a two clustering setups:
Docker Swarm and Kubernetes.

**NOTE**: the setup described here is for demonstration purposes only with the main
goal of giving the readers a head start if they want to explore possibilities of
deploying Mender to a cluster.

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
Creating integration_mender-mongo-useradm_1
Creating integration_mender-mongo-device-auth_1
Creating integration_mender-client_1
Creating integration_mender-mongo-deployments_1
Creating integration_mender-gui_1
Creating integration_mender-etcd_1
Creating integration_mender-inventory_1
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
91fea707e5a5        mendersoftware/inventory:latest            "/usr/bin/inventory -"   39 seconds ago      Up 15 seconds                                integration_mender-inventory_1
49ea9afc78b4        microbox/etcd:latest                       "/bin/etcd -data-dir="   51 seconds ago      Up 16 seconds       4001/tcp, 7001/tcp       integration_mender-etcd_1
6f435208ea54        mendersoftware/mender-client-qemu:latest   "./entrypoint.sh"        51 seconds ago      Up 23 seconds       8822/tcp                 integration_mender-client_1
738887c23dcb        mendersoftware/gui:latest                  "/bin/sh -c '/root/se"   51 seconds ago      Up 26 seconds                                integration_mender-gui_1
1cb5465256c3        mongo:latest                               "/entrypoint.sh mongo"   51 seconds ago      Up 28 seconds       27017/tcp                integration_mender-mongo-deployments_1
4c4a0dc6ce5c        mongo:latest                               "/entrypoint.sh mongo"   51 seconds ago      Up 32 seconds       27017/tcp                integration_mender-mongo-device-auth_1
ed2af2f6653a        mongo:latest                               "/entrypoint.sh mongo"   51 seconds ago      Up 37 seconds       27017/tcp                integration_mender-mongo-useradm_1
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

**NOTE**: minio is expected to be found under `s3.docker.mender.io` alias, however
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

* Deployments service

**NOTE**: we're directing deployments service to use `minio` instead of
`s3.docker.mender.io`.

**NOTE2**: mongo instance is named `mongo-deployments`.

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
4ugq2wpg9nnn  mender-mongo-inventory    1/1       mongo:latest                              
7z1bpw95r02d  mender-deployments        1/1       mendersoftware/deployments:latest         
8vamv85n4dcd  mender-gui                1/1       mendersoftware/gui:latest                 
bp69jjb3itrh  mongo-deployments         1/1       mongo:latest
```

List containers running on respective nodes bu calling `docker node ps <node>`:

```
user@localhost# docker node ps comp-006-thk                                                                               <<< 1 ↵
ID                         NAME                    IMAGE                            NODE          DESIRED STATE  CURRENT STATE        ERROR
7xwt7dd5dcgbglgobqyqh209k  mender-gui.1            mendersoftware/gui:latest        comp-006-thk  Running        Running 2 hours ago  
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

Suppose we want to scale `mender-device-auth` service and have 2 instances
instead of one. This can be achieved by running:

```
user@localhost# docker service scale mender-device-auth=2
mender-device-auth scaled to 2
```

This should be visible in `docker service ps` output:

```
user@localhost: docker service ps mender-device-auth
ID                         NAME                 IMAGE                            NODE          DESIRED STATE  CURRENT STATE          ERROR
b9kb8pxjzozchxdaaszvzkh0b  mender-device-auth.1  mendersoftware/deviceauth:latest  localhost     Running        Running 2 hours ago
4f9pjmkgs03fgomxe5z911a4u  mender-device-auth.2  mendersoftware/deviceauth:latest  node1         Running        Running 6 minutes ago
```

Second instance of `mender-device-auth` was scheduled to run on `localhost` node.


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

Required components:

* [kubectl](https://storage.googleapis.com/kubernetes-release/release/v1.4.6/bin/linux/amd64/kubectl), version 1.4.6
* [minikube](https://github.com/kubernetes/minikube), version 0.13.1
* [kompose](https://github.com/kubernetes-incubator/kompose), version 0.1.2 (92ea047)
* (optional)
  [docker-machine-driver-kvm](https://github.com/dhiltgen/docker-machine-kvm),
  version 0.7.0, build a3882af

## `minikube`

Setup described here uses `minikube` to create and provision a local Kubernetes
cluster. The tool, similarly to `docker-machine`, sets up a VM running
boot2docker Linux distibution. In this case, a clean boot2docker distibution has
been provisioned with necessary services. The ISO is hosted
https://storage.googleapis.com/minikube/minikube-0.7.iso and comes with an older
version of Docker Engine, namely 1.11.

Setup is performed by running:

```
user@localhost# minikube start 
Starting local Kubernetes cluster...
Kubectl is now configured to use the cluster.
```

`minikube` sets up a namespace called `default`:

```
user@localhost# kubectl get namespaces
NAME          STATUS    AGE
default       Active    2h
kube-system   Active    2h
```

Once setup, a single node becomes available:

```
user@localhost# kubectl get nodes
NAME       STATUS    AGE
minikube   Ready     2h
```


## Deploying mender to Kubernetes cluster

### Converting `docker-compose.yaml` with `kompose`

`kompose` is a tool for converting `docker-compose` deployment into Kubernetes
deployments/services/pods.

Conversion, assuming one is at the root of Mender `integration` repository, is
performed like this:`

```
user@localhost# mkdir kubernetes
user@localhost# cd kubernetes
user@localhost# kompose -f ../docker-compose.yml convert -y
WARN[0000] Unsupported network configuration of compose v2 - ignoring
WARN[0000] Unsupported key networks - ignoring
WARN[0000] Unsupported key depends_on - ignoring
WARN[0000] Unsupported key extends - ignoring
WARN[0000] [mender-inventory] Service cannot be created because of missing port.
WARN[0000] [mender-client] Service cannot be created because of missing port.
WARN[0000] [mender-device-auth] Service cannot be created because of missing port.
WARN[0000] [mender-gui] Service cannot be created because of missing port.
WARN[0000] [mender-deployments] Service cannot be created because of missing port.
WARN[0000] [mender-mongo-deployments] Service cannot be created because of missing port.
WARN[0000] [mender-mongo-inventory] Service cannot be created because of missing port.
WARN[0000] [mender-mongo-useradm] Service cannot be created because of missing port.
WARN[0000] [mender-mongo-device-auth] Service cannot be created because of missing port.
WARN[0000] [mender-etcd] Service cannot be created because of missing port.
WARN[0000] [mender-useradm] Service cannot be created because of missing port.
INFO[0000] file "minio-service.yaml" created
INFO[0000] file "mender-api-gateway-service.yaml" created
INFO[0000] file "mender-inventory-deployment.yaml" created
INFO[0000] file "mender-client-deployment.yaml" created
INFO[0000] file "mender-device-auth-deployment.yaml" created
INFO[0000] file "mender-gui-deployment.yaml" created
INFO[0000] file "minio-deployment.yaml" created
INFO[0000] file "mender-api-gateway-deployment.yaml" created
INFO[0000] file "mender-deployments-deployment.yaml" created
INFO[0000] file "mender-mongo-deployments-deployment.yaml" created
INFO[0000] file "mender-mongo-inventory-deployment.yaml" created
INFO[0000] file "mender-mongo-useradm-deployment.yaml" created
INFO[0000] file "mender-mongo-device-auth-deployment.yaml" created
INFO[0000] file "mender-etcd-deployment.yaml" created
INFO[0000] file "mender-useradm-deployment.yaml" created
user@localhost# ls -1
mender-api-gateway-deployment.yaml
mender-api-gateway-service.yaml
mender-client-deployment.yaml
mender-deployments-deployment.yaml
mender-device-auth-deployment.yaml
mender-etcd-deployment.yaml
mender-gui-deployment.yaml
mender-inventory-deployment.yaml
mender-mongo-deployments-deployment.yaml
mender-mongo-device-auth-deployment.yaml
mender-mongo-inventory-deployment.yaml
mender-mongo-useradm-deployment.yaml
mender-useradm-deployment.yaml
minio-deployment.yaml
minio-service.yaml
```

`kompose` raises warnings about inability to create a Service definition for all
containers with exception of `mender-api-gateway` and `minio`. This is expected
because only these 2 services publishes their ports to the outside world.

Due to `kompose` issue #318, generated deployment definition files set a
disallowed restartPolicy of in a pod template spec. This can be fixed by
running:

```
sed -e 's/ restartPolicy:/# restartPolicy:/' -i *-deployment.yaml
```

Outstanding issues:
- [kompose #318](https://github.com/kubernetes-incubator/kompose/issues/318)

#### Defining services

Services in a Mender cluster need to be able to find each other by DNS names.
Each service is started in a separate pod, hence we need to device `Service`
objects that expose services to the whole cluster.

Define the following service template in `templates/service.template.yaml`:

```
apiVersion: v1
kind: Service
metadata:
  name: ${SERVICE}
spec:
  ports:
  - port: ${PORT}
    protocol: TCP
  selector:
    service: ${SERVICE}
```

Then run the following command:

```
for service in mender-deployments mender-inventory mender-device-auth mender-useradm; do \
    SERVICE=$service PORT=8080 envsubst < templates/service.template.yml > $service-service.yaml; \
done
```

GUI service uses a different port:

```
SERVICE=mender-gui PORT=80 envsubst < templates/service.template.yml > mender-gui-service.yaml
```

Similarly, Mender services need to locate their database instances. We need to
generate `Service` definitions for mongo:

```
for service in mongo-deployments mongo-mender-inventory mongo-mender-device-auth mongo-mender-useradm; do \
    SERVICE=$service PORT=27017 envsubst < templates/service.template.yml > $service-service.yaml; \
done
```

**NOTE**: services: `mongo-mender-inventory`, `mongo-mender-device-auth`,
`mongo-mender-useradm` will be generated with an incorrect selector that needs
to be updated manually. The incorrect selector is
`service=mongo-mender-inventory` and should be changed to
`service=mender-mongo-inventory` (similarly for `device-auth` and `useradm`
definitions).

**NOTE**: `mender-api-gateway` needs to be modified by adding `spec.type=NodePort`
in `mender-api-gateway-service.yaml`.

### Publishing Mender services

Create services:

```
user@localhost# for f in  *-service.yaml; do kubectl create -f $f; done
service "mender-api-gateway" created
service "minio" created
...
```

Verify their status:

```
user@localhost# kubectl get svc
NAME                       CLUSTER-IP   EXTERNAL-IP   PORT(S)     AGE
kubernetes                 10.0.0.1     <none>        443/TCP     19m
mender-api-gateway         10.0.0.171   <nodes>       8080/TCP    12m
mender-deployments         10.0.0.110   <none>        8080/TCP    12m
mender-device-auth         10.0.0.46    <none>        8080/TCP    12m
mender-gui                 10.0.0.74    <none>        80/TCP      12m
mender-inventory           10.0.0.226   <none>        8080/TCP    12m
mender-useradm             10.0.0.77    <none>        8080/TCP    12m
minio                      10.0.0.161   <none>        9000/TCP    12m
mongo-deployments          10.0.0.251   <none>        27017/TCP   12m
mongo-mender-device-auth   10.0.0.16    <none>        27017/TCP   12m
mongo-mender-inventory     10.0.0.248   <none>        27017/TCP   12m
mongo-mender-useradm       10.0.0.120   <none>        27017/TCP   12m
```

### Deploying Mender

Deploy Mender services and minio storage backend:

```
user@localhost# for f in  mender*-deployment.yaml; do kubectl create -f $f; done
deployment "mender-api-gateway" created
deployment "mender-client" created
deployment "mender-deployments" created
deployment "mender-device-auth" created
deployment "mender-etcd" created
deployment "mender-gui" created
deployment "mender-inventory" created
deployment "mender-mongo-deployments" created
deployment "mender-mongo-device-auth" created
deployment "mender-mongo-inventory" created
deployment "mender-mongo-useradm" created
deployment "mender-useradm" created
user@localhost# kubectl create -f minio-deployment.yaml; done
```

Verify status of deployments:

```
user@localhost#
NAME                       DESIRED   CURRENT   UP-TO-DATE   AVAILABLE   AGE
mender-api-gateway         1         1         1            1           10m
mender-client              1         1         1            1           10m
mender-deployments         1         1         1            1           10m
mender-device-auth         1         1         1            1           10m
mender-etcd                1         1         1            1           10m
mender-gui                 1         1         1            1           10m
mender-inventory           1         1         1            1           10m
mender-mongo-deployments   1         1         1            1           10m
mender-mongo-device-auth   1         1         1            1           10m
mender-mongo-inventory     1         1         1            1           10m
mender-mongo-useradm       1         1         1            1           10m
mender-useradm             1         1         1            1           10m
minio                      1         1         1            1           10m
```

Pods:

```
user@localhost# kubectl get pods
NAME                                        READY     STATUS    RESTARTS   AGE
mender-api-gateway-1307175598-33pcj         1/1       Running   0          10m
mender-client-753708454-13jlq               1/1       Running   0          10m
mender-deployments-3147238546-7hc3o         1/1       Running   3          10m
mender-device-auth-1830858332-4y4r3         1/1       Running   0          10m
mender-etcd-2806034080-bx2zp                1/1       Running   0          10m
mender-gui-1131980139-oyz5m                 1/1       Running   0          10m
mender-inventory-1458285926-yjpvd           1/1       Running   0          10m
mender-mongo-deployments-2272570281-u9k0y   1/1       Running   0          10m
mender-mongo-device-auth-2107026143-2m173   1/1       Running   0          10m
mender-mongo-inventory-1573235229-eiwsl     1/1       Running   0          10m
mender-mongo-useradm-156543011-1m1hr        1/1       Running   0          10m
mender-useradm-1803790959-w4jj4             1/1       Running   0          10m
minio-82903772-w5ha7                        1/1       Running   0          10m
```

Once all service have their containers running, endpoints listing should show up
to date in-cluster IP addresses:

```
] kubectl get endpoints
NAME                       ENDPOINTS             AGE
kubernetes                 192.168.122.42:8443   25m
mender-api-gateway         172.17.0.4:443        18m
mender-deployments         172.17.0.6:8080       18m
mender-device-auth         172.17.0.8:8080       18m
mender-gui                 172.17.0.10:80        18m
mender-inventory           172.17.0.11:8080      18m
mender-useradm             172.17.0.17:8080      18m
minio                      172.17.0.18:9000      18m
mongo-deployments          172.17.0.12:27017     18m
mongo-mender-device-auth   172.17.0.14:27017     18m
mongo-mender-inventory     172.17.0.16:27017     18m
mongo-mender-useradm       172.17.0.15:27017     18m
```

Finally, access the UI:

```
user@localhost# minikube service mender-api-gateway             
Opening kubernetes service default/mender-api-gateway in default browser...
```

**NOTE**: due to API gateway redirect, the browser will be first directed to the
correct address and then redirected to port 8080 which may or may not work on a
particular setup. To workaround this problem first inspect details of
`mender-api-gateway`:

```
kubectl describe service mender-api-gateway
Name:                   mender-api-gateway
Namespace:              default
Labels:                 service=mender-api-gateway
Selector:               service=mender-api-gateway
Type:                   NodePort
IP:                     10.0.0.171
Port:                   8080    8080/TCP
NodePort:               8080    30961/TCP   <---- this port
Endpoints:              172.17.0.4:443
Session Affinity:       None
```

Next, find out the IP of `minikube` node:

```
user@localhost# minikube ip
192.168.42.173
```

Now, direct your browser to `https://192.168.42.173:30961`.

### Files

All deployment and service definitions are found in `kubernetes` directory.

# Followups & issues

- deployments service DB name is `mongo-deployments`, other services use
  `mender-mongo-<service-name>` pattern - needs verification
  
- API gateway fails to start if some service names cannot be resolved (though it
  continues to work if services go away after it has started) - explore using
  `upstream` config in `nginx.conf`
  
- uniform logging, services start and go down in case of trouble, it is hard to
  track down the reason for service dying unexpectedly

- need a large number of services and multiple mongo instances, even for a tiny
  setup

- network aliases in `docker-compose` do not have a similiar functionality in
  kubernetes, this causes problems when setting up `mender-deployments` to work
  with `minio` as deployments service uses `http://s3.docker.mender.io:9000` as
  `AWS_URI`
  
- API gateway automatically redirects to port 8080, this is not desired as the
  service may be exposed on a different port

- services `mender-deployments`, `mender-useradm`, `mender-device-auth`,
  `mender-inventory` make use of `iron/base`, that in
  turned is based on Alpine Linux 3.3, this version is known to cause issues
  with Kubernets DNS name resolution
