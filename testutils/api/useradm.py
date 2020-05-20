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

import testutils.api.client

URL_MGMT = testutils.api.client.GATEWAY_URL + "/api/management/v1/useradm"

URL_LOGIN = "/auth/login"
URL_SETTINGS = "/settings"
URL_2FAQR = "/2faqr"
URL_2FAVERIFY = "/2faverify"
URL_USERS = "/users"
URL_USERS_ID = "/users/{id}"
URL_ROLES = "/roles"
