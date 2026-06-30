#!/bin/bash
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

set -eu

MENDER_CONF="/etc/mender/mender.conf"
TEMPFILE=$(mktemp)
debugfs -R "dump $MENDER_CONF $TEMPFILE" "$IMAGE_TO_EDIT"

sed -i 's/.*UpdatePollIntervalSeconds.*/\  "UpdatePollIntervalSeconds\": 2,/g' "$TEMPFILE"
sed -i 's/.*InventoryPollIntervalSeconds.*/\  "InventoryPollIntervalSeconds\": 2,/g' "$TEMPFILE"

# MEN-9719: the client now defaults RetryPollIntervalSeconds to 300s (changed from
# 0 in mender PR #1971). With the default unlimited retry count the retry backoff
# starts at 60s, doubles, and is capped at this value, so a transiently-failing
# status/inventory push backs off for ~36 minutes before giving up (vs ~180s with the
# old default). That far exceeds the test timeouts and makes failure/rollback tests
# (e.g. test_state_scripts[Corrupted_script_version], test_rootfs_conf_missing_from_new_update)
# never reach their terminal state in the test window. The test server is reliably
# reachable, so pin a short retry interval like the other intervals above. Replace the
# key if present, otherwise add it next to UpdatePollIntervalSeconds.
sed -i 's/.*RetryPollIntervalSeconds.*/\  "RetryPollIntervalSeconds\": 0,/g' "$TEMPFILE"
grep -q RetryPollIntervalSeconds "$TEMPFILE" \
    || sed -i '/"UpdatePollIntervalSeconds"/a\  "RetryPollIntervalSeconds\": 0,' "$TEMPFILE"

debugfs -w -R "rm $MENDER_CONF" "$IMAGE_TO_EDIT"
printf 'cd %s\nwrite %s %s\n' `dirname $MENDER_CONF` "$TEMPFILE" `basename $MENDER_CONF` | debugfs -w "$IMAGE_TO_EDIT"
