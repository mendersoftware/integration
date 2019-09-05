# Copyright 2018 Northern.tech AS
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
import api.client

URL_MGMT = api.client.GATEWAY_URL + '/api/management/v1/deployments'
URL_DEVICES = api.client.GATEWAY_URL + '/api/devices/v1/deployments'

URL_NEXT   = '/device/deployments/next'
URL_LOG    = '/device/deployments/{id}/log'
URL_STATUS = '/device/deployments/{id}/status'
URL_DEPLOYMENT  = '/deployments/{id}'
URL_DEPLOYMENTS = '/deployments'
