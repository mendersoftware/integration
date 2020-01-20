# Copyright 2020 Northern.tech AS
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

URL = 'http://mender-conductor:8080'
URL_WORKFLOW_SEARCH = URL + '/api/workflow/search'
DECOMMISSIONING_DEVICE_WORKFLOW_NAME = 'decommission_device'

def workflow_by_name_query(name):
    qs = {
            'query': 'workflowType IN (%s)' % (name)
    }
    return qs

def get_workflows(params={}):
    r = requests.get(URL_WORKFLOW_SEARCH, params=params)
    assert r.status_code == 200
    return r.json()

# coductor provides workflow input as string
# e.g. "{device_id=foo, request_id=bar, authorization=baz}")
# parse_workflow_input converts the input string to dictionary
def parse_workflow_input(workflow_input):
    d = {}
    workflow_input = workflow_input.replace("{", "").replace("}", "").replace(" ", "")
    for x in workflow_input.split(','):
        k, v = x.split('=')
        d[k] = v
    return d
