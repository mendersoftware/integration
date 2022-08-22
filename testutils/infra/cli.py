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

from testutils.infra.container_manager.docker_manager import DockerNamespace
from testutils.infra.container_manager.kubernetes_manager import (
    KubernetesNamespace,
    isK8S,
)


class BaseCli:
    def __init__(self, microservice, containers_namespace, container_manager):
        if isK8S():
            self.container_manager = KubernetesNamespace()
            base_filter = microservice
        elif container_manager is None:
            self.container_manager = DockerNamespace(containers_namespace)
            base_filter = microservice + "[_-]1"
        else:
            self.container_manager = container_manager
            base_filter = microservice + "[_-]1"

        self.cid = self.container_manager.getid([base_filter])


class CliUseradm(BaseCli):
    def __init__(self, containers_namespace="backend-tests", container_manager=None):
        BaseCli.__init__(
            self, "mender-useradm", containers_namespace, container_manager
        )

        # is it an open useradm, or useradm-enterprise?
        for path in ["/usr/bin/useradm", "/usr/bin/useradm-enterprise"]:
            try:
                self.container_manager.execute(self.cid, [path, "--version"])
                self.path = path
            except:
                continue

        if self.path is None:
            raise RuntimeError("no runnable binary found in mender-useradm")

    def create_user(self, username, password, tenant_id=""):
        cmd = [
            self.path,
            "create-user",
            "--username",
            username,
            "--password",
            password,
        ]

        if tenant_id != "":
            cmd += ["--tenant-id", tenant_id]

        uid = self.container_manager.execute(self.cid, cmd)
        return uid

    def migrate(self, tenant_id=None):
        if isK8S():
            return

        cmd = [self.path, "migrate"]

        if tenant_id is not None:
            cmd.extend(["--tenant", tenant_id])

        self.container_manager.execute(self.cid, cmd)


class CliTenantadm(BaseCli):
    def __init__(self, containers_namespace="backend-tests", container_manager=None):
        BaseCli.__init__(
            self, "mender-tenantadm", containers_namespace, container_manager
        )

    def create_org(self, name, username, password, plan="os"):
        cmd = [
            "/usr/bin/tenantadm",
            "create-org",
            "--name",
            name,
            "--username",
            username,
            "--password",
            password,
            "--plan",
            plan,
        ]

        tid = self.container_manager.execute(self.cid, cmd)
        return tid

    def get_tenant(self, tid):
        cmd = ["/usr/bin/tenantadm", "get-tenant", "--id", tid]

        tenant = self.container_manager.execute(self.cid, cmd)
        return tenant

    def migrate(self):
        if isK8S():
            return

        cmd = ["usr/bin/tenantadm", "migrate"]

        self.container_manager.execute(self.cid, cmd)


class CliDeviceauth(BaseCli):
    def __init__(self, containers_namespace="backend-tests", container_manager=None):
        BaseCli.__init__(
            self, "mender-device-auth", containers_namespace, container_manager
        )

    def migrate(self, tenant_id=None):
        if isK8S():
            return

        cmd = ["usr/bin/deviceauth", "migrate"]

        if tenant_id is not None:
            cmd.extend(["--tenant", tenant_id])

        self.container_manager.execute(self.cid, cmd)

    def add_default_tenant_token(self, tenant_token):
        """
        Stops the container, adds the default_tenant_token to the config file
        at '/etc/deviceauth/config.yaml, and starts the container back up.

        :param tenant_token - 'the default tenant token to set'
        """

        # Append the default_tenant_token in the config ('/etc/deviceauth/config.yaml')
        cmd = [
            "/bin/sed",
            "-i",
            "$adefault_tenant_token: {}".format(tenant_token),
            "/etc/deviceauth/config.yaml",
        ]
        self.container_manager.execute(self.cid, cmd)

        # Restart the container, so that it is picked up by the device-auth service on startup
        self.container_manager.cmd(self.cid, "stop")
        self.container_manager.cmd(self.cid, "start")

    def propagate_inventory_statuses(self, tenant_id=None):
        if isK8S():
            return

        cmd = ["usr/bin/deviceauth", "propagate-inventory-statuses"]

        if tenant_id is not None:
            cmd.extend(["--tenant_id", tenant_id])

        self.container_manager.execute(self.cid, cmd)


class CliDeployments(BaseCli):
    def __init__(self, containers_namespace="backend-tests", container_manager=None):
        BaseCli.__init__(
            self, "mender-deployments", containers_namespace, container_manager
        )

        # is it an open version, or enterprise?
        for path in ["/usr/bin/deployments", "/usr/bin/deployments-enterprise"]:
            try:
                self.container_manager.execute(self.cid, [path, "--version"])
                self.path = path
            except:
                continue

        if self.path is None:
            raise RuntimeError("no runnable binary found for 'deployments'")

    def migrate(self, tenant_id=None):
        if isK8S():
            return

        cmd = [self.path, "migrate"]

        if tenant_id is not None:
            cmd.extend(["--tenant", tenant_id])

        self.container_manager.execute(self.cid, cmd)
