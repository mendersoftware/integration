#!/bin/sh
set -e

/etc/init.d/ssh start
cp /usr/share/dbus-1/system.d/io.mender.AuthenticationManager.conf /etc/dbus-1/system-local.conf
dbus-daemon --nofork --nopidfile --system &
sleep 8
mender --no-syslog daemon
sleep 8
mender-connect daemon
