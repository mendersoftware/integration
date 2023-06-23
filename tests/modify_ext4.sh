#!/bin/bash
# Copyright 2023 Northern.tech AS
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

debugfs -w -R "rm $MENDER_CONF" "$IMAGE_TO_EDIT"
printf 'cd %s\nwrite %s %s\n' `dirname $MENDER_CONF` "$TEMPFILE" `basename $MENDER_CONF` | debugfs -w "$IMAGE_TO_EDIT"
