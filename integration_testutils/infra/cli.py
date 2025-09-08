# Copyright 2023 Northern.tech AS
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

import os
import pytest
import tempfile

from collections import namedtuple
from contextlib import contextmanager
from typing import List

from integration_testutils.infra.container_manager.docker_manager import DockerNamespace
from integration_testutils.infra.container_manager.kubernetes_manager import (
    KubernetesNamespace,
    isK8S,
)

Microservice = namedtuple("Service", "bin_path data_path")


class BaseCli:
    def __init__(
        self, microservice, containers_namespace="backend-tests", container_manager=None
    ):
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

    def choose_binary_and_config_paths(
        self, service_flavours: List[str], service_name: str
    ):
        """Choose binary and configuration paths depending on service flavour. """
        for service in service_flavours:
            try:
                self.container_manager.execute(self.cid, [service.bin_path, "--help"])
                self.service = service
                break
            except:
                continue
        else:
            raise RuntimeError(f"no runnable binary found in {service_name}")


class CliUseradm(BaseCli):
    service_name = "mender-useradm"

    def __init__(self, containers_namespace="backend-tests", container_manager=None):
        BaseCli.__init__(
            self, self.service_name, containers_namespace, container_manager
        )

        open_source = Microservice("/usr/bin/useradm", "/etc/useradm")
        enterprise = Microservice(
            "/usr/bin/useradm-enterprise", "/etc/useradm-enterprise"
        )
        self.choose_binary_and_config_paths(
            [open_source, enterprise], self.service_name
        )

    def create_user(self, username, password, tenant_id="", roles=[]):
        cmd = [
            self.service.bin_path,
            "create-user",
            "--username",
            username,
            "--password",
            password,
        ]

        if tenant_id != "":
            cmd += ["--tenant-id", tenant_id]

        if len(roles) > 0:
            cmd += ["--roles", ",".join(roles)]

        uid = self.container_manager.execute(self.cid, cmd)
        return uid

    def migrate(self, tenant_id=None):
        if isK8S():
            return

        cmd = [self.service.bin_path, "migrate"]

        if tenant_id is not None:
            cmd.extend(["--tenant", tenant_id])

        self.container_manager.execute(self.cid, cmd)


class CliTenantadm(BaseCli):
    def __init__(self, containers_namespace="backend-tests", container_manager=None):
        BaseCli.__init__(
            self, "mender-tenantadm", containers_namespace, container_manager
        )
        self.service_name = "mender-tenantadm"

        enterprise = Microservice("/usr/bin/tenantadm", "/etc/tenantadm")
        self.choose_binary_and_config_paths([enterprise], self.service_name)

    def __call__(self, *args):
        cmd = [self.service.bin_path, *args]
        return self.container_manager.execute(self.cid, cmd)

    def create_org(self, name, username, password, plan="os", addons=[]) -> str:
        cmd = [
            self.service.bin_path,
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
        for addon in addons:
            cmd.extend(["--addon", addon])

        tid = self.container_manager.execute(self.cid, cmd)
        return tid

    def get_tenant(self, tid: str):
        cmd = [self.service.bin_path, "get-tenant", "--id", tid]

        tenant = self.container_manager.execute(self.cid, cmd)
        return tenant

    def migrate(self):
        if isK8S():
            return

        cmd = [self.service.bin_path, "migrate"]

        self.container_manager.execute(self.cid, cmd)


class CliDeviceauth(BaseCli):
    service_name = "mender-device-auth"

    def __init__(self, containers_namespace="backend-tests", container_manager=None):
        """ Instantiate deviceauth microservice CLI class. Both open source and enterprise versions are supported. """
        BaseCli.__init__(
            self, self.service_name, containers_namespace, container_manager
        )

        open_source = Microservice("/usr/bin/deviceauth", "/etc/deviceauth")
        enterprise = Microservice(
            "/usr/bin/deviceauth-enterprise", "/etc/deviceauth-enterprise"
        )
        self.choose_binary_and_config_paths(
            [open_source, enterprise], self.service_name
        )

    def migrate(self, tenant_id=None):
        if isK8S():
            return

        cmd = [self.service.bin_path, "migrate"]

        if tenant_id is not None:
            cmd.extend(["--tenant", tenant_id])

        self.container_manager.execute(self.cid, cmd)

    @contextmanager
    def add_default_tenant_token(self, tenant_token):
        """
        Stops the container, adds the default_tenant_token to the config file
        at '/etc/deviceauth/config.yaml, and starts the container back up.
        NOTE: Changing the runtime state of a container is prone to errors.
              The caller should ALWAYS wait for the deviceauth container to
              become healthy after entering AND leaving the context.

        :param tenant_token - 'the default tenant token to set'
        """

        # Append the default_tenant_token in the config
        # ('/etc/deviceauth/config.yaml' or '/etc/deviceauth-enterprise/config.yaml')
        config_file = f"{self.service.data_path}/config.yaml"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_config = os.path.join(tmp, "config.tmp.yaml")
            container_config = os.path.join(tmp, "config.yaml")
            self.container_manager.download(self.cid, config_file, container_config)
            tmp_config_content = open(container_config).read().strip()
            tmp_config_content += "\ndefault_tenant_token: {}\n".format(tenant_token)
            open(tmp_config, "w").write(tmp_config_content)
            self.container_manager.upload(self.cid, tmp_config, config_file)
            # Restart the container, so that it is picked up by the device-auth service on startup
            self.container_manager.cmd(self.cid, "stop")
            self.container_manager.cmd(self.cid, "start")
            try:
                yield
            finally:
                try:
                    # Restore the previous configuration state
                    self.container_manager.upload(
                        self.cid, container_config, config_file
                    )
                    self.container_manager.cmd(self.cid, "stop")
                    self.container_manager.cmd(self.cid, "start")
                except Exception as exc:
                    pytest.exit(f"Failed to restore deviceauth container state: {exc}")

                # Clear temp directory
                os.unlink(tmp_config)
                os.unlink(container_config)

    def propagate_inventory_statuses(self, tenant_id=None):
        if isK8S():
            return

        cmd = [self.service.bin_path, "propagate-inventory-statuses"]

        if tenant_id is not None:
            cmd.extend(["--tenant_id", tenant_id])

        self.container_manager.execute(self.cid, cmd)


class CliDeployments(BaseCli):
    service_name = "mender-deployments"

    def __init__(self, containers_namespace="backend-tests", container_manager=None):
        BaseCli.__init__(
            self, self.service_name, containers_namespace, container_manager
        )

        open_source = Microservice("/usr/bin/deployments", "/etc/deployments")
        enterprise = Microservice(
            "/usr/bin/deployments-enterprise", "/etc/deployments-enterprise"
        )
        self.choose_binary_and_config_paths(
            [open_source, enterprise], self.service_name
        )

    def migrate(self, tenant_id=None):
        if isK8S():
            return

        cmd = [self.service.bin_path, "migrate"]

        if tenant_id is not None:
            cmd.extend(["--tenant", tenant_id])

        self.container_manager.execute(self.cid, cmd)


class CliDeviceMonitor(BaseCli):
    def __init__(self, containers_namespace="backend-tests", container_manager=None):
        super().__init__("devicemonitor", containers_namespace, container_manager)
        self.path = "/usr/bin/devicemonitor"

    def migrate(self):
        if isK8S():
            return

        self.container_manager.execute(self.cid, [self.path, "migrate"])
