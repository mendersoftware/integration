#!/usr/bin/python
# Copyright 2019 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from fabric.api import *
import pytest
from common_setup import *
from helpers import Helpers
from MenderAPI import deploy
from common_update import update_image_successful, common_update_procedure
from mendertesting import MenderTesting
import shutil

class TestDBMigration(MenderTesting):

    @pytest.mark.usefixtures("setup_with_legacy_client")
    def test_migrate_from_legacy_mender_v1_failure(self, install_image=conftest.get_valid_image()):
        """
            Start a legacy client (1.7.0) first and update it to the new one.

            The test starts a setup with the 1.7.0 client and then updates it to
            the current version. The update is failing first (due to failure
            returned inside the artifact commit enter state script).
            After the failed first update we are updating cient (1.7.0) again,
            and this time the update should succeed.
        """

        if not env.host_string:
            execute(self.test_migrate_from_legacy_mender_v1_failure,
                    hosts=get_mender_clients(),
                    install_image=install_image)
            return

        dirpath = tempfile.mkdtemp()
        script_content = '#!/bin/sh\nexit 1\n'
        with open(os.path.join(dirpath, "ArtifactCommit_Enter_01"), "w") as fd:
            fd.write(script_content)

        active_part = Helpers.get_active_partition()

        # first start with the failed update
        with Helpers.RebootDetector() as reboot:
            deployment_id, _ = common_update_procedure(install_image,
                                                       scripts=[os.path.join(dirpath, "ArtifactCommit_Enter_01")],
                                                       version=2)

            logging.info("waiting for system to reboot twice")
            reboot.verify_reboot_performed(number_of_reboots=2)

            assert Helpers.get_active_partition() == active_part
            deploy.check_expected_statistics(deployment_id, "failure", 1)

        # do the next update, this time succesfull
        execute(update_image_successful,
                install_image=install_image,
                version=2)

    @pytest.mark.usefixtures("setup_with_legacy_client")
    def test_migrate_from_legacy_mender_v1_success(self, install_image=conftest.get_valid_image()):
        """
            Start a legacy client (1.7.0) first and update it to the new one.

            The test starts a setup with the 1.7.0 client and then updates it to
            the current version. After the first successful update, we are updating 
            the client for the second time, to make sure the DB migration has not left
            any traces in the database that are causing issues.
        """

        if not env.host_string:
            execute(self.test_migrate_from_legacy_mender_v1_success,
                    hosts=get_mender_clients(),
                    install_image=install_image)
            return

        tmpdir = tempfile.mkdtemp()
        test_log = "/var/lib/mender/migration_state_scripts.log"
        try:
            # Test that state scripts are also executed correctly.
            scripts = ["ArtifactInstall_Enter_00", "ArtifactCommit_Enter_00"]
            scripts_paths = []
            for script in scripts:
                script_path = os.path.join(tmpdir, script)
                scripts_paths += [script_path]
                with open(script_path, "w") as fd:
                    fd.write('#!/bin/sh\necho $(basename $0) >> %s\n' % test_log)

            # do the succesfull update twice
            execute(update_image_successful,
                    install_image=install_image,
                    scripts=scripts_paths,
                    version=2)
            assert run("cat %s" % test_log).strip() == "\n".join(scripts)

            execute(update_image_successful,
                    install_image=install_image,
                    scripts=scripts_paths,
                    version=2)
            assert run("cat %s" % test_log).strip() == "\n".join(scripts) + "\n" + "\n".join(scripts)

        finally:
            shutil.rmtree(tmpdir)
