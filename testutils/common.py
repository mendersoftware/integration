# Copyright 2022 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
import json
import pytest
import random
import time
import string
import tempfile
import uuid
import os
import subprocess
from contextlib import contextmanager

import docker
import redo
import requests

import testutils.api.deviceauth as deviceauth
import testutils.api.inventory as inventory
import testutils.api.reporting as reporting
import testutils.api.tenantadm as tenantadm
import testutils.api.useradm as useradm
import testutils.util.crypto
from testutils.api.client import ApiClient, GATEWAY_HOSTNAME
from testutils.infra.container_manager.kubernetes_manager import isK8S
from testutils.infra.mongo import MongoClient
from testutils.infra.cli import CliUseradm, CliTenantadm
from testutils.infra.device import MenderDevice, MenderDeviceGroup


@pytest.fixture(scope="session")
def mongo():
    return MongoClient("mender-mongo:27017")


@pytest.fixture(scope="function")
def clean_mongo(mongo):
    """Fixture setting up a clean (i.e. empty database). Yields
    pymongo.MongoClient connected to the DB."""
    elasticsearch_cleanup()
    mongo_cleanup(mongo)
    yield mongo.client


def elasticsearch_cleanup():
    try:
        requests.post(
            reporting.ELASTICSEARCH_DELETE_URL, json={"query": {"match_all": {}}}
        )
    except requests.RequestException:
        pass


def mongo_cleanup(mongo):
    mongo.cleanup()


class User:
    def __init__(self, id, name, pwd, roles=[]):
        self.name = name
        self.pwd = pwd
        self.id = id
        self.token = None
        self.roles = roles


class Authset:
    def __init__(self, id, did, id_data, pubkey, privkey, status):
        self.id = id
        self.did = did
        self.id_data = id_data
        self.pubkey = pubkey
        self.privkey = privkey
        self.status = status


class Device:
    def __init__(self, id, id_data, pubkey, tenant_token="", status=""):
        self.id = id
        self.id_data = id_data
        self.pubkey = pubkey
        self.tenant_token = tenant_token
        self.authsets = []
        self.token = None
        self.status = status


class Tenant:
    def __init__(self, name, id, token):
        self.name = name
        self.users = []
        self.devices = []
        self.id = id
        self.tenant_token = token


def create_random_authset(dauthd1, dauthm, utoken, tenant_token=""):
    """create_device with random id data and keypair"""
    priv, pub = testutils.util.crypto.get_keypair_rsa()
    mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), "x") for i in range(6)])
    id_data = {"mac": mac}

    return create_authset(dauthd1, dauthm, id_data, pub, priv, utoken, tenant_token)


def create_authset(
    dauthd1, dauthm, id_data, pubkey, privkey, utoken, tenant_token=""
) -> Authset:
    body, sighdr = deviceauth.auth_req(id_data, pubkey, privkey, tenant_token)

    # submit auth req
    r = dauthd1.call("POST", deviceauth.URL_AUTH_REQS, body, headers=sighdr)
    assert r.status_code == 401, r.text

    # dev must exist and have *this* aset
    api_dev = get_device_by_id_data(dauthm, id_data, utoken)
    assert api_dev is not None

    aset = [
        a
        for a in api_dev["auth_sets"]
        if testutils.util.crypto.compare_keys(a["pubkey"], pubkey)
    ]
    assert len(aset) == 1, str(aset)

    aset = aset[0]

    assert aset["identity_data"] == id_data
    assert aset["status"] == "pending"

    return Authset(aset["id"], api_dev["id"], id_data, pubkey, privkey, "pending")


def create_user(
    name: str,
    pwd: str,
    tid: str = "",
    containers_namespace: str = "backend-tests",
    roles: list = [],
) -> User:
    cli = CliUseradm(containers_namespace)
    uid = cli.create_user(name, pwd, tid, roles=roles)

    return User(uid, name, pwd)


def create_org(
    name: str,
    username: str,
    password: str,
    plan: str = "os",
    containers_namespace: str = "backend-tests",
    container_manager=None,
) -> Tenant:
    cli = CliTenantadm(
        containers_namespace=containers_namespace, container_manager=container_manager
    )
    user_id = None
    tenant_id = cli.create_org(name, username, password, plan=plan)
    tenant_token = json.loads(cli.get_tenant(tenant_id))["tenant_token"]

    host = GATEWAY_HOSTNAME
    if container_manager is not None:
        host = container_manager.get_mender_gateway()
    api = ApiClient(useradm.URL_MGMT, host=host)

    # Try log in every second for 3 minutes.
    # - There usually is a slight delay (in order of ms) for propagating
    #   the created user to the db.
    for i in range(3 * 60):
        rsp = api.call("POST", useradm.URL_LOGIN, auth=(username, password))
        if rsp.status_code == 200:
            break
        time.sleep(1)

    assert (
        rsp.status_code == 200
    ), "User could not log in within three minutes after organization has been created."

    user_token = rsp.text
    rsp = api.with_auth(user_token).call("GET", useradm.URL_USERS)
    users = json.loads(rsp.text)
    for user in users:
        if user["email"] == username:
            user_id = user["id"]
            break
    if user_id is None:
        raise ValueError("Error retrieving user id.")

    tenant = Tenant(name, tenant_id, tenant_token)
    user = User(user_id, username, password)
    user.token = user_token
    tenant.users.append(user)
    return tenant


def get_device_by_id_data(dauthm, id_data, utoken):
    page = 0
    per_page = 20
    qs_params = {}
    found = None
    while True:
        page = page + 1
        qs_params["page"] = page
        qs_params["per_page"] = per_page
        r = dauthm.with_auth(utoken).call(
            "GET", deviceauth.URL_MGMT_DEVICES, qs_params=qs_params
        )
        assert r.status_code == 200
        api_devs = r.json()

        found = [d for d in api_devs if d["identity_data"] == id_data]
        if len(found) > 0:
            break

        if len(api_devs) == 0:
            break

    assert len(found) == 1, "device not found by id data"

    return found[0]


def change_authset_status(dauthm, did, aid, status, utoken):
    r = dauthm.with_auth(utoken).call(
        "PUT",
        deviceauth.URL_AUTHSET_STATUS,
        deviceauth.req_status(status),
        path_params={"did": did, "aid": aid},
    )
    assert r.status_code == 204


def rand_id_data():
    mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), "x") for i in range(6)])
    sn = "".join(["{}".format(random.randint(0x00, 0xFF)) for i in range(6)])

    return {"mac": mac, "sn": sn}


def make_pending_device(
    dauthd1: ApiClient, dauthm: ApiClient, utoken: str, tenant_token: str = ""
) -> Device:
    """Create one device with "pending" status."""
    id_data = rand_id_data()

    priv, pub = testutils.util.crypto.get_keypair_rsa()
    new_set = create_authset(
        dauthd1, dauthm, id_data, pub, priv, utoken, tenant_token=tenant_token
    )

    dev = Device(new_set.did, new_set.id_data, pub, tenant_token)

    dev.authsets.append(new_set)

    dev.status = "pending"

    return dev


def make_accepted_device(
    dauthd1: ApiClient,
    dauthm: ApiClient,
    utoken: str,
    tenant_token: str = "",
    test_type: str = "regular",
) -> Device:
    """Create one device with "accepted" status."""
    test_types = ["regular", "azure"]
    if test_type not in test_types:
        raise RuntimeError("Given test type is not allowed")
    dev = make_pending_device(dauthd1, dauthm, utoken, tenant_token=tenant_token)
    aset_id = dev.authsets[0].id
    change_authset_status(dauthm, dev.id, aset_id, "accepted", utoken)
    aset = dev.authsets[0]
    aset.status = "accepted"

    # TODO: very bad workaround for Azure IoT Hub backend test; following part is responsible for creating
    # TODO: additonal, unnecessary auth set which causes Azure test to fail
    if test_type == "regular":
        # obtain auth token
        body, sighdr = deviceauth.auth_req(
            aset.id_data, aset.pubkey, aset.privkey, tenant_token
        )
        r = dauthd1.call("POST", deviceauth.URL_AUTH_REQS, body, headers=sighdr)
        assert r.status_code == 200
        dev.token = r.text

    dev.status = "accepted"

    return dev


def make_accepted_devices(devauthd, devauthm, utoken, tenant_token="", num_devices=1):
    """Create accepted devices.
    returns list of Device objects."""
    devices = []

    # some 'accepted' devices, single authset
    for _ in range(num_devices):
        dev = make_accepted_device(devauthd, devauthm, utoken, tenant_token)
        devices.append(dev)

    return devices


def make_device_with_inventory(attributes, utoken, tenant_token):
    devauthm = ApiClient(deviceauth.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)
    invm = ApiClient(inventory.URL_MGMT)

    d = make_accepted_device(devauthd, devauthm, utoken, tenant_token)
    """
    verify that the status of the device in inventory is "accepted"
    """
    accepted = False
    timeout = 10
    for i in range(timeout):
        r = invm.with_auth(utoken).call("GET", inventory.URL_DEVICE.format(id=d.id))
        if r.status_code == 200:
            dj = r.json()
            for attr in dj["attributes"]:
                if attr["name"] == "status" and attr["value"] == "accepted":
                    accepted = True
                    break
        if accepted:
            break
        time.sleep(1)
    if not accepted:
        raise ValueError(
            "status for device %s has not been propagated within %d seconds"
            % (d.id, timeout)
        )

    submit_inventory(attributes, d.token)

    d.attributes = attributes

    return d


def submit_inventory(attrs, token):
    invd = ApiClient(inventory.URL_DEV)
    r = invd.with_auth(token).call("PATCH", inventory.URL_DEVICE_ATTRIBUTES, attrs)
    assert r.status_code == 200


@contextmanager
def get_mender_artifact(
    artifact_name="test",
    update_module="dummy",
    device_types=("arm1",),
    size=256,
    depends=(),
    provides=(),
):
    data = "".join(random.choices(string.ascii_uppercase + string.digits, k=size))
    f = tempfile.NamedTemporaryFile(delete=False)
    f.write(data.encode("utf-8"))
    f.close()
    #
    filename = f.name
    artifact = "%s.mender" % filename
    args = [
        "mender-artifact",
        "write",
        "module-image",
        "-o",
        artifact,
        "--artifact-name",
        artifact_name,
        "-T",
        update_module,
        "-f",
        filename,
    ]
    for device_type in device_types:
        args.extend(["-t", device_type])
    for depend in depends:
        args.extend(["--depends", depend])
    for provide in provides:
        args.extend(["--provides", provide])
    try:
        subprocess.call(args)
        yield artifact
    finally:
        os.unlink(filename)
        os.path.exists(artifact) and os.unlink(artifact)


def wait_until_healthy(compose_project: str = "", timeout: int = 60):
    """
    wait_until_healthy polls all running containers health check
    endpoints until they return a non-error status code.
    :param compose_project: the docker-compose project ID, if empty it
                            checks all running containers.
    :param timeout: timeout in seconds.
    """
    client = docker.from_env()
    kwargs = {}
    if compose_project != "":
        kwargs["filters"] = {"label": f"com.docker.compose.project={compose_project}"}

    path_map = {
        "mender-api-gateway": "/ping",
        "mender-auditlogs": "/api/internal/v1/auditlogs/health",
        "mender-deviceconnect": "/api/internal/v1/deviceconnect/health",
        "mender-deviceconfig": "/api/internal/v1/deviceconfig/health",
        "mender-device-auth": "/api/internal/v1/devauth/health",
        "mender-deployments": "/api/internal/v1/deployments/health",
        "mender-inventory": "/api/internal/v1/inventory/health",
        "mender-tenantadm": "/api/internal/v1/tenantadm/health",
        "mender-useradm": "/api/internal/v1/useradm/health",
        "mender-workflows": "/api/v1/health",
        "minio": "/minio/health/live",
    }

    containers = client.containers.list(all=True, **kwargs)
    for container in containers:

        container_ip = None
        for _, net in container.attrs["NetworkSettings"]["Networks"].items():
            container_ip = net["IPAddress"]
            break
        if container_ip is None or container_ip == "":
            continue

        service = container.labels.get(
            "com.docker.compose.service", container.name
        ).split("-enterprise")[0]
        if service.startswith("mender-workflows-server"):
            service = "mender-workflows"

        path = path_map.get(service)
        if path is None:
            continue
        port = 8080 if service != "minio" else 9000

        for _ in redo.retrier(attempts=timeout, sleeptime=1):
            try:
                rsp = requests.request("GET", f"http://{container_ip}:{port}{path}")
            except requests.exceptions.ConnectionError:
                # A ConnectionError is expected if the service is not running yet
                continue
            if rsp.status_code < 300:
                break
        else:
            raise TimeoutError(
                f"Timed out waiting for service '{service}' to become healthy"
            )


def update_tenant(tid, addons=None, plan=None, container_manager=None):
    """Call internal PUT tenantadm/tenants/{tid}"""
    update = {}
    if addons is not None:
        update["addons"] = tenantadm.make_addons(addons)

    if plan is not None:
        update["plan"] = plan

    tenantadm_host = (
        tenantadm.HOST
        if isK8S() or container_manager is None
        else container_manager.get_ip_of_service("mender-tenantadm")[0] + ":8080"
    )
    tadm = ApiClient(tenantadm.URL_INTERNAL, host=tenantadm_host, schema="http://")
    res = tadm.call(
        "PUT", tenantadm.URL_INTERNAL_TENANT, body=update, path_params={"tid": tid},
    )
    assert res.status_code == 202


def new_tenant_client(
    test_env, name: str, tenant: str, docker: bool = False, network: str = "mender"
) -> MenderDevice:
    """Create new Mender client in the test environment with the given name for the given tenant.

    The passed test_env must implement new_tenant_client and/or new_tenant_docker_client.

    This helper attaches the recently created Mender client to the test environment, so that systemd
    logs can be printed on test failures.
    """

    pre_existing_clients = set(test_env.get_mender_clients(network=network))
    if docker:
        test_env.new_tenant_docker_client(name, tenant)
    else:
        test_env.new_tenant_client(name, tenant)
    all_clients = set(test_env.get_mender_clients(network=network))
    new_client = all_clients - pre_existing_clients
    assert len(new_client) == 1
    device = MenderDevice(new_client.pop())
    if hasattr(test_env, "device_group"):
        test_env.device_group.append(device)
    else:
        test_env.device = device
        test_env.device_group = MenderDeviceGroup(
            test_env.get_mender_clients(network=network)
        )
    return device


def create_tenant_test_setup() -> Tenant:
    """ Creates a tenant and a user belonging to the tenant (both tenant and user are created with random names). """
    uuidv4 = str(uuid.uuid4())
    tenant, username, password = (
        "test.mender.io-" + uuidv4,
        "some.user+" + uuidv4 + "@example.com",
        "secretsecret",
    )
    tenant = create_org(tenant, username, password, "enterprise")
    user = create_user(
        "foo+" + uuidv4 + "@user.com", "correcthorsebatterystaple", tid=tenant.id
    )

    response = ApiClient(useradm.URL_MGMT).call(
        "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
    )
    assert response.status_code == 200
    user.utoken = response.text
    tenant.users = [user]
    return tenant


def create_user_test_setup() -> User:
    """Create a user with random name, log user in. """
    uuidv4 = str(uuid.uuid4())
    user_name, password = (
        "some.user+" + uuidv4 + "@example.com",
        "secretsecret",
    )

    user = create_user(user_name, password)
    useradmm = ApiClient(useradm.URL_MGMT)
    # log in user
    response = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
    assert response.status_code == 200
    user.utoken = response.text
    return user


def useExistingTenant() -> bool:
    return bool(os.environ.get("USE_EXISTING_TENANT"))


def setup_tenant_devices(tenant, device_groups):
    """
    setup_user_devices authenticates the user and creates devices
    attached to (static) groups given by the proportion map from
    the groups parameter.
    :param users:     Users to setup devices for (list).
    :param n_devices: Number of accepted devices created for each
                      user (int).
    :param groups:    Map of group names to device proportions, the
                      sum of proportion must be less than or equal
                      to 1 (dict[str] = float)
    :return: Dict mapping group_name -> list(devices)
    """
    devauth_DEV = ApiClient(deviceauth.URL_DEVICES)
    devauth_MGMT = ApiClient(deviceauth.URL_MGMT)
    invtry_MGMT = ApiClient(inventory.URL_MGMT)
    user = tenant.users[0]
    grouped_devices = {}
    group = None

    tenant.devices = []
    for group, dev_cnt in device_groups.items():
        grouped_devices[group] = []
        for i in range(dev_cnt):
            device = make_accepted_device(
                devauth_DEV, devauth_MGMT, user.token, tenant.tenant_token
            )
            if group is not None:
                rsp = invtry_MGMT.with_auth(user.token).call(
                    "PUT",
                    inventory.URL_DEVICE_GROUP.format(id=device.id),
                    body={"group": group},
                )
                assert rsp.status_code == 204

            device.group = group
            grouped_devices[group].append(device)
            tenant.devices.append(device)

    # sleep a few seconds waiting for the data propagation to the reporting service
    # and the Elasticsearch indexing to complete
    time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

    return grouped_devices
