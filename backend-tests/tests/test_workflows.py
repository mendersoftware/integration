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

import pytest
import logging

from testutils.api import workflows
from testutils.api.client import ApiClient


class _TestWorkflowsBase:
    workflows_workflow = ApiClient(
        base_url=workflows.URL_WORKFLOW, host=workflows.HOST, schema="http://"
    )
    workflows_meta = ApiClient(
        base_url=workflows.URL_WORKFLOWS_META, host=workflows.HOST, schema="http://"
    )

    def start_workflow(self, name, version=""):
        req = {"newid": "1", "someid": "2"}
        r = (
            self.workflows_workflow.with_header("Content-Type", "application/json")
            .with_header("X-Workflows-Min-Version", version)
            .call("POST", "/" + name, req,)
        )
        return r

    def new_workflow(self, name, version):
        """create a new workflow"""
        req = {
            "name": name,
            "description": "some",
            "version": version,
            "schemaVersion": 1,
            "tasks": [
                {"name": "t1", "type": "http", "retries": 1, "retryDelaySeconds": 4}
            ],
            "inputParameters": ["newid"],
            "optionalParameters": ["someid"],
        }
        r = self.workflows_meta.with_header("Content-Type", "application/json").call(
            "POST", "", req
        )
        return r

    def test_workflow_min_version(self):
        """
        Check that we can invoke a workflow with minimal required version
        """
        workflow_name = "wf1"
        workflow_version = 4

        # first let's create a workflow
        self.logger.info(
            "creating workflow: %s/v%s" % (workflow_name, str(workflow_version))
        )
        r = self.new_workflow(workflow_name, workflow_version)
        assert r.status_code == 201
        self.logger.info(
            "created workflow: %s/v%s" % (workflow_name, str(workflow_version))
        )

        self.logger.info("starting: %s/v%s" % (workflow_name, str(workflow_version)))
        r = self.start_workflow(workflow_name, str(workflow_version))
        assert r.status_code == 201
        self.logger.info("started: %s/v%s" % (workflow_name, str(workflow_version)))

        self.logger.info(
            "starting: %s/v%s" % (workflow_name, str(workflow_version - 1))
        )
        r = self.start_workflow(workflow_name, str(workflow_version - 1))
        assert r.status_code == 201
        self.logger.info("started: %s/v%s" % (workflow_name, str(workflow_version - 1)))

        self.logger.info(
            "attempting to start: %s/v%s" % (workflow_name, str(workflow_version + 1))
        )
        r = self.start_workflow(workflow_name, str(workflow_version + 1))
        assert r.status_code == 404
        self.logger.info(
            "not started: %s/v%s" % (workflow_name, str(workflow_version + 1))
        )


class TestWorkflowMinVersion(_TestWorkflowsBase):
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)


class TestWorkflowMinVersionEnterprise(_TestWorkflowsBase):
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)
