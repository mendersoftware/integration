#!/bin/sh

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
mender --no-syslog daemon &
sleep 8
mender-connect daemon &
while true; do sleep 10; done
