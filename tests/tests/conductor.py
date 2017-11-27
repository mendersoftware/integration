#!/usr/bin/python
# Copyright 2017 Northern.tech AS
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
import requests


class Conductor:
    API_WF_SEARCH = '/api/workflow/search'

    def __init__(self, host):
        self.addr = 'http://%s:8080' % (host,)

    def get_decommission_device_wfs(self, device_id, state='COMPLETED'):
        """
            Get (completed) decommission_device workflows for device.
        """
        qs = {
            'q': 'workflowType IN (%s) AND status IN (%s) AND input.device_id IN (%s)' % \
                    ('decommission_device', state, device_id)
        }

        return self.__get_workflows(qs)


    def __get_workflows(self, query):
        """
            Get workflows according to a search query.
        """
        qs = {
            'q': query,
        }

        rsp = requests.get(self.addr+self.API_WF_SEARCH, qs)
        rsp.raise_for_status()
        return rsp.json()

