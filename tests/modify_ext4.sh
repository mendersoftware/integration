#!/bin/bash
set -eu

MENDER_CONF="/etc/mender/mender.conf"
TEMPFILE=$(mktemp)
debugfs -R "dump $MENDER_CONF $TEMPFILE" "$IMAGE_TO_EDIT"

sed -i 's/.*UpdatePollIntervalSeconds.*/\  "UpdatePollIntervalSeconds\": 2,/g' "$TEMPFILE"
sed -i 's/.*InventoryPollIntervalSeconds.*/\  "InventoryPollIntervalSeconds\": 2,/g' "$TEMPFILE"

debugfs -w -R "rm $MENDER_CONF" "$IMAGE_TO_EDIT"
printf 'cd %s\nwrite %s %s\n' `dirname $MENDER_CONF` "$TEMPFILE" `basename $MENDER_CONF` | debugfs -w "$IMAGE_TO_EDIT"
