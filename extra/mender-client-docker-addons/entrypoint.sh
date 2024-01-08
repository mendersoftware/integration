#!/bin/sh
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

set -e

if [ -n "$SERVER_URL" ]; then
    sed -i -e "s#\"ServerURL\": *\"[^\"]*\"#\"ServerURL\": \"$SERVER_URL\"#" /etc/mender/mender.conf
fi
if [ -n "$TENANT_TOKEN" ]; then
    sed -i -e "s/\"TenantToken\": *\"[^\"]*\"/\"TenantToken\": \"$TENANT_TOKEN\"/" /etc/mender/mender.conf
fi

/etc/init.d/ssh start
cp /usr/share/dbus-1/system.d/io.mender.AuthenticationManager.conf /etc/dbus-1/system-local.conf
dbus-daemon --nofork --nopidfile --system &
sleep 8
mender-auth daemon &
sleep 1
mender-update daemon &
sleep 8
mender-connect daemon &
while true; do sleep 10; done
