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

HOST = "mender-useradm:8080"

URL_MGMT = "/api/management/v1/useradm"
URL_MGMT_V2 = "/api/management/v2/useradm"
URL_INTERNAL = "/api/internal/v1/useradm"

URL_LOGIN = "/auth/login"
URL_PASSWORD_RESET_START = "/auth/password-reset/start"
URL_PASSWORD_RESET_COMPLETE = "/auth/password-reset/complete"
URL_SETTINGS = "/settings"
URL_2FAQR = "/2faqr"
URL_2FAVERIFY = "/2faverify"
URL_USERS = "/users"
URL_USERS_ID = "/users/{id}"
URL_ROLES = "/roles"
URL_VERIFY_EMAIL_START = "/auth/verify-email/start"
URL_VERIFY_EMAIL_COMPLETE = "/auth/verify-email/complete"
URL_2FA_ENABLE = "/users/{id}/2fa/enable"
URL_2FA_DISABLE = "/users/{id}/2fa/disable"
URL_EMAILS = "/tenants/{tenant_id}/devices/{device_id}/users"
URL_TENANT_USERS = "/tenants/{tenant_id}/users"
